import argparse
import json
import signal
import socket
import sys
import threading
import time

from messages import (
    JOIN, PEER_LIST, HEARTBEAT, LEAVE,
    TX, BLOCK, CHAIN_REQUEST, CHAIN_RESPONSE,
    send_msg, recv_msg, parse_addr,
)

HEARTBEAT_INTERVAL = 5.0   # 5 seconds btwn heartbeats to tracker

class Peer:
    """Full networking node: registers with the tracker, maintains peer list,
    listens for inbound peer messages, and broadcasts outbound
    """

    def __init__(self, listen_addr: str, tracker_addr: str, pubkey: str) -> None:
        self.listen_addr  = listen_addr   
        self.tracker_addr = tracker_addr 
        self.pubkey       = pubkey

        self._peer_list: list[dict] = []
        self._peer_list_lock = threading.Lock()

        self._handlers: dict[str, list] = {}

        self._tracker_sock: socket.socket | None = None
        self._listen_sock:  socket.socket | None = None
        self._stopping = False
        self._threads:  list[threading.Thread] = []

    def register_handler(self, msg_type: str, fn) -> None:
        self._handlers.setdefault(msg_type, []).append(fn)

    def _dispatch(self, msg: dict, sender_addr: str) -> None:
        t = msg.get("type")
        for fn in self._handlers.get(t, []):
            try:
                fn(msg, sender_addr)
            except Exception as e:
                self._log(f"handler error for {t}: {e}")
        if t not in self._handlers:
            self._log(f"no handler for '{t}' from {sender_addr} — dropping")

    def get_peer_list(self) -> list[dict]:
        """Returns snapshot of the current peer list excluding self.
        """
        with self._peer_list_lock:
            return [
                p for p in self._peer_list
                if p["addr"] != self.listen_addr
            ]

    def _update_peer_list(self, peers: list[dict]) -> None:
        """Replaces the peer list with fresh snapshot from the tracker"""
        with self._peer_list_lock:
            self._peer_list = peers
        self._log(f"peer list updated: {[p['addr'] for p in peers]}")

    # outbound

    def send_to(self, addr: str, msg: dict) -> bool:
        """Open TCP connection to addr, send msg, then close,

        returns true on success, and false on error
        """
        try:
            with socket.create_connection(parse_addr(addr), timeout=2) as s:
                send_msg(s, msg)
            return True
        except OSError as e:
            self._log(f"send_to {addr} failed: {e}")
            return False

    def broadcast(self, msg: dict) -> None:
        """Send msg to every peer in the current list (excluding itself)
        """
        for entry in self.get_peer_list():
            self.send_to(entry["addr"], msg)

    def start(self) -> None:
        self._connect_tracker()
        self._bind_listen_socket()

        threads = [
            threading.Thread(target=self._tracker_reader,  daemon=True, name="tracker-reader"),
            threading.Thread(target=self._heartbeat_sender, daemon=True, name="heartbeat"),
            threading.Thread(target=self._accept_loop,      daemon=True, name="accept"),
        ]
        self._threads = threads
        for t in threads:
            t.start()
        self._repl()

    def stop(self) -> None:
        """Send LEAVE to the tracker then close sockets and join threads"""
        if self._stopping:
            return
        self._stopping = True
        self._log("stopping…")
        if self._tracker_sock:
            try:
                send_msg(self._tracker_sock, {"type": LEAVE, "addr": self.listen_addr})
            except OSError:
                pass
            try:
                self._tracker_sock.close()
            except OSError:
                pass
        if self._listen_sock:
            try:
                self._listen_sock.close()
            except OSError:
                pass

        for t in self._threads:
            t.join(timeout=3)

    def _connect_tracker(self) -> None:
        try:
            s = socket.create_connection(parse_addr(self.tracker_addr), timeout=5)
        except OSError as e:
            print(f"[peer] cannot reach tracker at {self.tracker_addr}: {e}")
            raise SystemExit(1)
        s.settimeout(None)  # timeout=5 above was for connect only; switch to blocking
        send_msg(s, {"type": JOIN, "addr": self.listen_addr, "pubkey": self.pubkey})
        self._tracker_sock = s
        self._log(f"joined tracker at {self.tracker_addr}")

    def _bind_listen_socket(self) -> None:
        host, port = parse_addr(self.listen_addr)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError as e:
            print(f"[peer] cannot bind {self.listen_addr}: {e}")
            raise SystemExit(1)
        s.listen(16)
        self._listen_sock = s
        self._log(f"listening for peers on {self.listen_addr}")

    def _tracker_reader(self) -> None:
        rfile = self._tracker_sock.makefile("r")
        try:
            while not self._stopping:
                msg = recv_msg(rfile)
                if msg is None:
                    self._log("tracker connection closed — running on stale peer list")
                    break
                if msg.get("type") == PEER_LIST:
                    self._update_peer_list(msg.get("peers", []))
                else:
                    self._log(f"unexpected message from tracker: {msg.get('type')}")
        except (ValueError, OSError) as e:
            if not self._stopping:
                self._log(f"tracker reader error: {e}")
        finally:
            rfile.close()

    def _heartbeat_sender(self) -> None:
        while not self._stopping:
            time.sleep(HEARTBEAT_INTERVAL)
            if self._stopping:
                break
            try:
                send_msg(
                    self._tracker_sock,
                    {"type": HEARTBEAT, "addr": self.listen_addr},
                )
            except OSError:
                break   # tracker gone; reader thread will log the EOF

    def _accept_loop(self) -> None:
        while not self._stopping:
            try:
                conn, peername = self._listen_sock.accept()
            except OSError:
                break
            t = threading.Thread(
                target=self._handle_peer_conn,
                args=(conn, peername),
                daemon=True,
                name=f"inbound-{peername}",
            )
            t.start()

    def _handle_peer_conn(self, conn: socket.socket, peername: tuple) -> None:
        rfile = conn.makefile("r")
        sender_addr = f"{peername[0]}:{peername[1]}"
        try:
            msg = recv_msg(rfile)
            if msg is None:
                return
            # prefer self reported addr from CHAIN_REQUEST etc. if present
            sender_addr = msg.get("from", sender_addr)
            self._dispatch(msg, sender_addr)
        except (ValueError, OSError) as e:
            self._log(f"bad message from {peername}: {e}")
        finally:
            rfile.close()
            try:
                conn.close()
            except OSError:
                pass

    def _repl(self) -> None:
        """simple stdin command loop for manual testing and demo.
        """
        import sys
        if not sys.stdin.isatty():
            while not self._stopping:
                time.sleep(1)
            return

        while not self._stopping:
            try:
                line = input("peer> ").strip()
            except EOFError:
                # Ctrl D in terminal, treat same as quit.
                break
            except KeyboardInterrupt:
                break

            if not line:
                continue

            parts = line.split(None, 1)
            cmd   = parts[0].lower()
            arg   = parts[1] if len(parts) > 1 else ""
            if cmd == "peers":
                pl = self.get_peer_list()
                if pl:
                    for p in pl:
                        print(f"  {p['addr']}  pubkey={p['pubkey']}")
                else:
                    print("  (no peers)")

            elif cmd == "tx":
                self.broadcast({"type": TX, "tx": {"debug": arg}})
                print(f"  broadcast TX: {arg!r}")

            elif cmd == "block":
                self.broadcast({"type": BLOCK, "block": {"debug": arg}})
                print(f"  broadcast BLOCK: {arg!r}")

            elif cmd == "send":
                sub = arg.split(None, 1)
                if len(sub) < 2:
                    print("  usage: send <addr> <text>")
                else:
                    ok = self.send_to(sub[0], {"type": TX, "tx": {"debug": sub[1]}})
                    print(f"  {'ok' if ok else 'failed'}")

            elif cmd == "quit":
                break

        self.stop()
    def _log(self, msg: str) -> None:
        """Print a timestamped log line prefixed with this peer's addr."""
        print(f"[{self.listen_addr} {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _stub_handler(msg: dict, sender: str) -> None:
    print("x")



def main() -> None:
    parser = argparse.ArgumentParser(description="Allowance blockchain peer")
    parser.add_argument("--addr",    required=True)
    parser.add_argument("--tracker", required=True)
    parser.add_argument("--pubkey",  default="")
    args = parser.parse_args()

    peer = Peer(args.addr, args.tracker, args.pubkey)

    for msg_type in (TX, BLOCK, CHAIN_REQUEST, CHAIN_RESPONSE):
        peer.register_handler(msg_type, _stub_handler)
    # stop on Ctrl C
    def _sigint(sig, frame):
        print()
        peer.stop()
        sys.exit(0)
    signal.signal(signal.SIGINT, _sigint)

    peer.start()


if __name__ == "__main__":
    main()
