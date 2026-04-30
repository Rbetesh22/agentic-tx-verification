# peer.py — networking layer for an Allowance blockchain peer.
#
# Exposes a Peer class that Person B (chain) and Person C (tx / app) import.
# The class handles all socket work; callers register handlers for message types
# and call broadcast() or send_to() to send.
#
# Usage (standalone demo):
#   python peer.py --addr 127.0.0.1:9001 --tracker 127.0.0.1:9000 --pubkey A
#
# Handler contract (for B and C):
#   def my_handler(msg: dict, sender_addr: str) -> None: ...
#   peer.register_handler("TX", my_handler)
#   # handlers run on network threads — protect your own shared state with locks.

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

HEARTBEAT_INTERVAL = 5.0   # seconds between heartbeats to tracker


# ── Peer class ─────────────────────────────────────────────────────────────────

class Peer:
    """Full networking node: registers with the tracker, maintains a peer list,
    listens for inbound peer messages, and broadcasts outbound messages.

    Instantiate, call register_handler() for any message types you care about,
    then call start().  Call stop() (or send SIGINT) to exit cleanly.
    """

    def __init__(self, listen_addr: str, tracker_addr: str, pubkey: str) -> None:
        self.listen_addr  = listen_addr    # "host:port" — our listening address
        self.tracker_addr = tracker_addr   # "host:port" — tracker location
        self.pubkey       = pubkey

        # peer list from tracker: list of {"addr": str, "pubkey": str}
        self._peer_list: list[dict] = []
        self._peer_list_lock = threading.Lock()

        # registered message handlers: type_str -> callable(msg, sender_addr)
        self._handlers: dict[str, list] = {}

        self._tracker_sock: socket.socket | None = None
        self._listen_sock:  socket.socket | None = None
        self._stopping = False
        self._threads:  list[threading.Thread] = []

    # ── handler registration ──────────────────────────────────────────────────

    def register_handler(self, msg_type: str, fn) -> None:
        """Register fn as a callback for messages of msg_type.

        Multiple handlers per type are allowed; all are called in order.
        fn receives (msg_dict, sender_addr) and runs on a network thread.
        """
        self._handlers.setdefault(msg_type, []).append(fn)

    def _dispatch(self, msg: dict, sender_addr: str) -> None:
        """Route an incoming message to all registered handlers for its type.

        Unknown message types are logged and silently dropped; no handler is
        an error for type-specific messages only if the type is unexpected.
        """
        t = msg.get("type")
        for fn in self._handlers.get(t, []):
            try:
                fn(msg, sender_addr)
            except Exception as e:
                self._log(f"handler error for {t}: {e}")
        if t not in self._handlers:
            self._log(f"no handler for '{t}' from {sender_addr} — dropping")

    # ── peer list ─────────────────────────────────────────────────────────────

    def get_peer_list(self) -> list[dict]:
        """Return a snapshot of the current peer list, excluding self.

        Safe to call from any thread.
        """
        with self._peer_list_lock:
            return [
                p for p in self._peer_list
                if p["addr"] != self.listen_addr
            ]

    def _update_peer_list(self, peers: list[dict]) -> None:
        """Replace the peer list with a fresh snapshot from the tracker."""
        with self._peer_list_lock:
            self._peer_list = peers
        self._log(f"peer list updated: {[p['addr'] for p in peers]}")

    # ── outbound messaging ────────────────────────────────────────────────────

    def send_to(self, addr: str, msg: dict) -> bool:
        """Open a short-lived TCP connection to addr, send msg, then close.

        Returns True on success, False on any socket error.  Does not raise.
        """
        try:
            with socket.create_connection(parse_addr(addr), timeout=2) as s:
                send_msg(s, msg)
            return True
        except OSError as e:
            self._log(f"send_to {addr} failed: {e}")
            return False

    def broadcast(self, msg: dict) -> None:
        """Send msg to every peer in the current list (excluding self).

        Failures are logged but do not stop the rest of the broadcast.
        Tracker remains the source of truth for membership — failed peers are
        NOT removed here; the tracker's sweeper will drop them.
        """
        for entry in self.get_peer_list():
            self.send_to(entry["addr"], msg)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Connect to the tracker, bind the listening socket, and spawn threads.

        Blocks until stop() is called or a fatal error occurs.
        """
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

        self._log("started — type 'help' for commands")
        self._repl()   # blocks until 'quit'

    def stop(self) -> None:
        """Send LEAVE to the tracker, close sockets, and join threads."""
        if self._stopping:
            return
        self._stopping = True
        self._log("stopping…")

        # send LEAVE — best effort (tracker may already be gone)
        if self._tracker_sock:
            try:
                send_msg(self._tracker_sock, {"type": LEAVE, "addr": self.listen_addr})
            except OSError:
                pass
            try:
                self._tracker_sock.close()
            except OSError:
                pass

        # closing the listen socket unblocks accept()
        if self._listen_sock:
            try:
                self._listen_sock.close()
            except OSError:
                pass

        for t in self._threads:
            t.join(timeout=3)

    # ── internal threads ──────────────────────────────────────────────────────

    def _connect_tracker(self) -> None:
        """Open a persistent TCP connection to the tracker and send JOIN.

        Raises SystemExit on connection failure (no tracker = no network).
        """
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
        """Bind the peer's listening socket on its configured addr:port.

        Raises SystemExit if the port is already in use.
        """
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
        """Read messages from the tracker's persistent socket in a loop.

        The only expected inbound message type is PEER_LIST.  On EOF the peer
        keeps running with its last-known list (tracker crashed or restarted).
        """
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
        """Send a HEARTBEAT to the tracker every HEARTBEAT_INTERVAL seconds.

        This is the only thread that writes to _tracker_sock, so no lock is
        needed.  Exits quietly if the tracker socket is closed.
        """
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
        """Accept inbound peer connections forever, spawning a handler per conn.

        Exits cleanly when _listen_sock is closed by stop().
        """
        while not self._stopping:
            try:
                conn, peername = self._listen_sock.accept()
            except OSError:
                break   # socket closed by stop()
            t = threading.Thread(
                target=self._handle_peer_conn,
                args=(conn, peername),
                daemon=True,
                name=f"inbound-{peername}",
            )
            t.start()

    def _handle_peer_conn(self, conn: socket.socket, peername: tuple) -> None:
        """Handle one inbound peer connection: read exactly one message, dispatch, close.

        Peer-to-peer is open-send-close per message, so we read one line and
        exit.  Malformed JSON is logged and the connection is dropped silently.
        """
        rfile = conn.makefile("r")
        sender_addr = f"{peername[0]}:{peername[1]}"
        try:
            msg = recv_msg(rfile)
            if msg is None:
                return
            # prefer the self-reported addr from CHAIN_REQUEST etc. if present
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

    # ── REPL ──────────────────────────────────────────────────────────────────

    def _repl(self) -> None:
        """Simple stdin command loop for manual testing and demo.

        Runs on the main thread.  Type 'help' for available commands.
        When stdin is not a terminal (e.g. piped or redirected), the REPL is
        skipped and the main thread just blocks until stop() is called.
        """
        import sys
        if not sys.stdin.isatty():
            # Non-interactive mode: keep main thread alive until SIGINT/stop().
            while not self._stopping:
                time.sleep(1)
            return

        while not self._stopping:
            try:
                line = input("peer> ").strip()
            except EOFError:
                # Ctrl-D in an interactive terminal — treat same as quit.
                break
            except KeyboardInterrupt:
                break

            if not line:
                continue

            parts = line.split(None, 1)
            cmd   = parts[0].lower()
            arg   = parts[1] if len(parts) > 1 else ""

            if cmd == "help":
                print("  peers              — show current peer list")
                print("  tx <text>          — broadcast a debug TX")
                print("  block <text>       — broadcast a debug BLOCK")
                print("  send <addr> <text> — send a debug TX to one peer")
                print("  quit               — leave and exit")

            elif cmd == "peers":
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

            else:
                print(f"  unknown command '{cmd}' — type 'help'")

        self.stop()

    # ── utility ───────────────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        """Print a timestamped log line prefixed with this peer's addr."""
        print(f"[{self.listen_addr} {time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── default stub handlers ──────────────────────────────────────────────────────

def _stub_handler(msg: dict, sender: str) -> None:
    """Placeholder handler that prints received message type.

    Person B replaces BLOCK/CHAIN_* handlers; Person C replaces TX handler.
    """
    print(f"  [got {msg['type']} from {sender}] {json.dumps(msg)[:120]}", flush=True)


# ── entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    """Parse CLI args, wire up stub handlers, and start the peer."""
    parser = argparse.ArgumentParser(description="Allowance blockchain peer")
    parser.add_argument("--addr",    required=True, help="this peer's listen addr, e.g. 127.0.0.1:9001")
    parser.add_argument("--tracker", required=True, help="tracker addr, e.g. 127.0.0.1:9000")
    parser.add_argument("--pubkey",  default="",    help="this peer's public key (hex or label)")
    args = parser.parse_args()

    peer = Peer(args.addr, args.tracker, args.pubkey)

    # stub handlers — B and C will replace these in their own entry points
    for msg_type in (TX, BLOCK, CHAIN_REQUEST, CHAIN_RESPONSE):
        peer.register_handler(msg_type, _stub_handler)

    # SIGINT → clean stop
    def _sigint(sig, frame):
        print()
        peer.stop()
        sys.exit(0)
    signal.signal(signal.SIGINT, _sigint)

    peer.start()


if __name__ == "__main__":
    main()
