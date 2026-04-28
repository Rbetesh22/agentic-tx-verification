# tracker.py — peer-discovery tracker for the Allowance blockchain network.
#
# Responsibilities:
#   - Accept persistent TCP connections from peers (JOIN).
#   - Push an updated PEER_LIST to all live peers whenever membership changes.
#   - Drop peers that miss 3 consecutive heartbeats (>15 s silence).
#   - Does NOT touch the blockchain.
#
# Usage:
#   python tracker.py [--port 9000]

import argparse
import json
import socket
import threading
import time

from messages import (
    JOIN, PEER_LIST, HEARTBEAT, LEAVE,
    send_msg, recv_msg,
)

# ── shared state ───────────────────────────────────────────────────────────────

# peers: addr -> {"pubkey": str, "last_heartbeat": float, "conn": socket}
peers: dict[str, dict] = {}
peers_lock = threading.Lock()

HEARTBEAT_TIMEOUT = 15.0   # seconds of silence before a peer is dropped
SWEEP_INTERVAL    = 2.0    # how often the sweeper checks for dead peers

# ── helpers ────────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    """Print a timestamped log line to stdout."""
    print(f"[tracker {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _build_peer_list_payload() -> dict:
    """Build a PEER_LIST message dict from the current peers registry.

    Caller must hold peers_lock.
    """
    return {
        "type": PEER_LIST,
        "peers": [
            {"addr": addr, "pubkey": info["pubkey"]}
            for addr, info in peers.items()
        ],
    }


def broadcast_peer_list() -> None:
    """Send the current PEER_LIST to every registered peer.

    Builds the payload and snapshots targets under the lock, then releases the
    lock before doing I/O so one slow peer cannot stall JOIN/LEAVE for others.
    Dead sockets are collected and removed after the broadcast loop, then the
    list is broadcast one more time so survivors see a clean view.
    """
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
    before the new entry overwrites it.
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
    """Remove a peer from the registry and broadcast the updated list.

    Safe to call when the addr is not present (idempotent).
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
    """Update the last_heartbeat timestamp for a known peer.

    If the addr is not in the registry (peer timed out and was swept before
    this heartbeat arrived), log and ignore — the peer must re-JOIN.
    """
    with peers_lock:
        if addr in peers:
            peers[addr]["last_heartbeat"] = time.time()
        else:
            log(f"HEARTBEAT from unknown addr {addr} — ignoring (must re-JOIN)")

# ── handler thread ─────────────────────────────────────────────────────────────

def handle_connection(conn: socket.socket, peername: tuple) -> None:
    """Manage the lifecycle of one persistent peer connection.

    Reads newline-delimited JSON messages in a loop and dispatches on type.
    On EOF or any socket/parse error the peer is deregistered and the socket
    is closed.  The first message MUST be JOIN; anything else drops the conn.
    """
    rfile = conn.makefile("r")
    registered_addr: str | None = None

    try:
        # ── expect JOIN as first message ──────────────────────────────────────
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

        # ── main read loop ────────────────────────────────────────────────────
        while True:
            msg = recv_msg(rfile)
            if msg is None:
                break   # EOF — peer closed the connection
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

# ── sweeper thread ─────────────────────────────────────────────────────────────

def sweeper() -> None:
    """Background thread: every SWEEP_INTERVAL seconds, evict peers that have
    not sent a heartbeat within HEARTBEAT_TIMEOUT seconds and broadcast the
    updated list if anything was dropped.
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

# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    """Parse args, bind the listening socket, start the sweeper, then accept
    connections forever, spawning a daemon handler thread for each one.
    """
    parser = argparse.ArgumentParser(description="Allowance blockchain tracker")
    parser.add_argument("--port", type=int, default=9000)
    args = parser.parse_args()

    # ── bind ──────────────────────────────────────────────────────────────────
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("0.0.0.0", args.port))
    except OSError as e:
        print(f"[tracker] cannot bind to port {args.port}: {e}")
        raise SystemExit(1)
    server.listen(32)
    log(f"listening on 0.0.0.0:{args.port}")

    # ── sweeper ───────────────────────────────────────────────────────────────
    t = threading.Thread(target=sweeper, daemon=True, name="sweeper")
    t.start()

    # ── accept loop ───────────────────────────────────────────────────────────
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
        # best-effort close of all peer sockets so they detect EOF immediately
        with peers_lock:
            for info in peers.values():
                try:
                    info["conn"].close()
                except OSError:
                    pass
        server.close()


if __name__ == "__main__":
    main()
