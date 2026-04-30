import argparse
import json
import socket
import threading
import time

from messages import (
    JOIN, PEER_LIST, HEARTBEAT, LEAVE,
    send_msg, recv_msg,
)

peers: dict[str, dict] = {}
peers_lock = threading.Lock()

HEARTBEAT_TIMEOUT = 15.0   # seconds of silence before peer is dropped
SWEEP_INTERVAL    = 2.0    # how often the sweeper checks for dead peers

def log(msg: str) -> None:
    print(f"[tracker {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _build_peer_list_payload() -> dict:
    return {
        "type": PEER_LIST,
        "peers": [
            {"addr": addr, "pubkey": info["pubkey"]}
            for addr, info in peers.items()
        ],
    }


def broadcast_peer_list() -> None:
    with peers_lock:
        payload = _build_peer_list_payload()
        targets = list(peers.items())   # snapshot: list of (addr, info)

    line = (json.dumps(payload) + "\n").encode()
    dead: list[str] = []

    for addr, info in targets:
        try:
            info["conn"].sendall(line)
        except OSError:
            dead.append(addr)

    if dead:
        with peers_lock:
            for addr in dead:
                entry = peers.pop(addr, None)
                if entry:
                    try:
                        entry["conn"].close()
                    except OSError:
                        pass
        log(f"dropped dead peers during broadcast: {dead}")
        # one recursive pass so survivors see the corrected list
        broadcast_peer_list()


def _register_peer(addr: str, pubkey: str, conn: socket.socket) -> None:
    """Add or replace a peer entry and broadcast the updated list.

    If the same addr re-JOINs (e.g. after a crash), the old socket is closed
    before the new entry overwrites it
    """
    with peers_lock:
        old = peers.get(addr)
        if old:
            try:
                old["conn"].close()
            except OSError:
                pass
            log(f"re-JOIN from {addr} — replacing old entry")
        peers[addr] = {
            "pubkey": pubkey,
            "last_heartbeat": time.time(),
            "conn": conn,
        }
    log(f"JOIN  {addr}  (pubkey={pubkey[:16]}...)")
    broadcast_peer_list()


def _deregister_peer(addr: str, reason: str = "LEAVE") -> None:
    """Remove a peer from the registry and broadcast the updated list - idempotent 
    """
    with peers_lock:
        entry = peers.pop(addr, None)
        if entry:
            try:
                entry["conn"].close()
            except OSError:
                pass
    if entry:
        log(f"{reason}  {addr}")
        broadcast_peer_list()


def _bump_heartbeat(addr: str) -> None:
    with peers_lock:
        if addr in peers:
            peers[addr]["last_heartbeat"] = time.time()
        else:
            log(f"HEARTBEAT from unknown addr {addr} — ignoring (must re-JOIN)")

def handle_connection(conn: socket.socket, peername: tuple) -> None:
    rfile = conn.makefile("r")
    registered_addr: str | None = None

    try:
        msg = recv_msg(rfile)
        if msg is None:
            log(f"connection from {peername} closed before JOIN")
            return
        if msg.get("type") != JOIN:
            log(f"unexpected first message from {peername}: {msg.get('type')} — dropping")
            return
        addr   = msg["addr"]
        pubkey = msg.get("pubkey", "")
        registered_addr = addr
        _register_peer(addr, pubkey, conn)
        while True:
            msg = recv_msg(rfile)
            if msg is None:
                break
            t = msg.get("type")
            if t == HEARTBEAT:
                _bump_heartbeat(msg.get("addr", addr))
            elif t == LEAVE:
                _deregister_peer(msg.get("addr", addr), reason="LEAVE")
                registered_addr = None
                break
            else:
                log(f"unknown message type '{t}' from {addr} — ignoring")

    except (ValueError, KeyError) as e:
        log(f"bad message from {peername}: {e} — dropping connection")
    except OSError as e:
        log(f"socket error from {peername}: {e}")
    finally:
        rfile.close()
        try:
            conn.close()
        except OSError:
            pass
        if registered_addr:
            _deregister_peer(registered_addr, reason="EOF/error")

def sweeper() -> None:
    """Background thread: every SWEEP_INTERVAL seconds, evict peers that have
    not sent a heartbeat within HEARTBEAT_TIMEOUT seconds and broadcast the
    updated list if anything was dropped
    """
    while True:
        time.sleep(SWEEP_INTERVAL)
        now  = time.time()
        dead: list[str] = []

        with peers_lock:
            for addr, info in list(peers.items()):
                if now - info["last_heartbeat"] > HEARTBEAT_TIMEOUT:
                    dead.append(addr)
            for addr in dead:
                entry = peers.pop(addr, None)
                if entry:
                    try:
                        entry["conn"].close()
                    except OSError:
                        pass

        if dead:
            log(f"sweep evicted (timeout): {dead}")
            broadcast_peer_list()

def main() -> None:
    parser = argparse.ArgumentParser(description="Allowance blockchain tracker")
    parser.add_argument("--port", type=int, default=9000)
    args = parser.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("0.0.0.0", args.port))
    except OSError as e:
        print(f"[tracker] cannot bind to port {args.port}: {e}")
        raise SystemExit(1)
    server.listen(32)
    log(f"listening on 0.0.0.0:{args.port}")

    t = threading.Thread(target=sweeper, daemon=True, name="sweeper")
    t.start()

    try:
        while True:
            conn, peername = server.accept()
            t = threading.Thread(
                target=handle_connection,
                args=(conn, peername),
                daemon=True,
                name=f"peer-{peername}",
            )
            t.start()
    except KeyboardInterrupt:
        log("shutting down")
    finally:
        with peers_lock:
            for info in peers.values():
                try:
                    info["conn"].close()
                except OSError:
                    pass
        server.close()


if __name__ == "__main__":
    main()
