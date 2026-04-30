import json
import socket

#message type constants
JOIN           = "JOIN"
PEER_LIST      = "PEER_LIST"
HEARTBEAT      = "HEARTBEAT"
LEAVE          = "LEAVE"
TX             = "TX"
BLOCK          = "BLOCK"
CHAIN_REQUEST  = "CHAIN_REQUEST"
CHAIN_RESPONSE = "CHAIN_RESPONSE"


def send_msg(sock: socket.socket, msg: dict) -> None:
    """Serialize msg as JSON and write"""
    sock.sendall((json.dumps(msg) + "\n").encode())


def recv_msg(rfile) -> dict | None:
    line = rfile.readline()
    if not line:
        return None
    return json.loads(line)


def parse_addr(addr: str) -> tuple[str, int]:
    host, port = addr.rsplit(":", 1)
    return host, int(port)
