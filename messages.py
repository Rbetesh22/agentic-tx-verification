# messages.py — shared message-type constants and framing helpers.
# All network I/O in tracker.py and peer.py should go through send_msg / recv_msg
# so the newline framing is defined exactly once.
#

import json
import socket

# ── message type constants ─────────────────────────────────────────────────────
JOIN           = "JOIN"
PEER_LIST      = "PEER_LIST"
HEARTBEAT      = "HEARTBEAT"
LEAVE          = "LEAVE"
TX             = "TX"
BLOCK          = "BLOCK"
CHAIN_REQUEST  = "CHAIN_REQUEST"
CHAIN_RESPONSE = "CHAIN_RESPONSE"

# ── framing helpers ────────────────────────────────────────────────────────────

def send_msg(sock: socket.socket, msg: dict) -> None:
    """Serialize msg as JSON and write it as a single newline-terminated line."""
    sock.sendall((json.dumps(msg) + "\n").encode())


def recv_msg(rfile) -> dict | None:
    """Read one newline-terminated line from rfile and parse it as JSON.

    Returns None on EOF; raises ValueError on bad JSON so callers can drop
    the connection cleanly.
    """
    line = rfile.readline()
    if not line:
        return None
    return json.loads(line)


def parse_addr(addr: str) -> tuple[str, int]:
    """Split 'host:port' into (host, int(port)) for use with socket.connect."""
    host, port = addr.rsplit(":", 1)
    return host, int(port)
