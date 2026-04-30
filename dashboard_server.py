import argparse
import atexit
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from crypto_utils import generate_keypair, serialize_public_key
from node import Node

TRACKER_ADDR = "127.0.0.1:9000"
PEER_ADDRS = ["127.0.0.1:9001", "127.0.0.1:9002", "127.0.0.1:9003", "127.0.0.1:9004"]
DIFFICULTY = 8
WEB_DIR = Path(__file__).parent / "web"


class DemoNetwork:
    def __init__(self):
        self.lock = threading.Lock()
        self.tracker_proc = None
        self.nodes = []
        self.owner_priv = None
        self.owner_hex = None
        self.merchant_hex = None
        self.agents = []
        self.events = []

    def log(self, text):
        self.events.append({"ts": time.time(), "text": text})
        if len(self.events) > 200:
            self.events = self.events[-200:]

    def start(self):
        with self.lock:
            self._stop_locked()
            self._init_keys_locked()
            self._start_tracker_locked()
            self._start_nodes_locked()
            self.log("Network started: tracker + 4 nodes")

    def stop(self):
        with self.lock:
            self._stop_locked()

    def _init_keys_locked(self):
        owner_priv, owner_pub = generate_keypair()
        self.owner_priv = owner_priv
        self.owner_hex = serialize_public_key(owner_pub)

        self.agents = []
        for _ in range(3):
            priv, pub = generate_keypair()
            self.agents.append((priv, serialize_public_key(pub)))

        _merchant_priv, merchant_pub = generate_keypair()
        self.merchant_hex = serialize_public_key(merchant_pub)
        self.events = []

    def _start_tracker_locked(self):
        devnull = open(os.devnull, "w")
        self.tracker_proc = subprocess.Popen(
            [sys.executable, "tracker.py", "--port", "9000"],
            stdout=devnull,
            stderr=devnull,
            stdin=devnull,
        )
        time.sleep(0.7)

    def _start_nodes_locked(self):
        self.nodes = []
        for addr in PEER_ADDRS:
            node = Node(addr, TRACKER_ADDR, difficulty=DIFFICULTY)
            # Disable interactive REPL for dashboard mode.
            node.peer._repl = lambda: None
            thread = threading.Thread(target=node.peer.start, daemon=True)
            thread.start()
            self.nodes.append(node)
            time.sleep(0.2)
        time.sleep(1.0)

    def _stop_locked(self):
        for node in self.nodes:
            try:
                node.stop()
            except Exception:
                pass
        self.nodes = []

        if self.tracker_proc:
            try:
                self.tracker_proc.terminate()
                self.tracker_proc.wait(timeout=2)
            except Exception:
                try:
                    self.tracker_proc.kill()
                except Exception:
                    pass
            self.tracker_proc = None

    def _node(self, idx=0):
        return self.nodes[idx]

    def mandate(self, agent_index: int, max_amount: float, node_index: int = 0):
        with self.lock:
            if not self.nodes:
                return False, "network not started"
            if agent_index < 1 or agent_index > len(self.agents):
                return False, "invalid agent"

            agent_priv, agent_hex = self.agents[agent_index - 1]
            tx = self._node(node_index).create_mandate(
                self.owner_priv,
                self.owner_hex,
                agent_hex,
                float(max_amount),
            )
            accepted = self._node(node_index).submit_transaction(tx)
            if accepted:
                self.log(f"Owner authorized Agent {agent_index} up to ${max_amount:.2f}")
                return True, "mandate accepted"
            self.log(f"Mandate rejected for Agent {agent_index}")
            return False, "mandate rejected"

    def spend(self, agent_index: int, amount: float, node_index: int = 0):
        with self.lock:
            if not self.nodes:
                return False, "network not started"
            if agent_index < 1 or agent_index > len(self.agents):
                return False, "invalid agent"

            agent_priv, agent_hex = self.agents[agent_index - 1]
            tx = self._node(node_index).create_spend(
                agent_priv,
                agent_hex,
                self.merchant_hex,
                float(amount),
            )
            accepted = self._node(node_index).submit_transaction(tx)
            if accepted:
                self.log(f"Agent {agent_index} spend ${amount:.2f} accepted")
                return True, "spend accepted"
            self.log(f"Agent {agent_index} spend ${amount:.2f} rejected")
            return False, "spend rejected"

    def mine(self, node_index: int = 0):
        with self.lock:
            if not self.nodes:
                return False, "network not started"
            block = self._node(node_index).mine()
            if not block:
                return False, "nothing to mine"
            self.log(f"Node {node_index + 1} mined block #{block.index}")
            return True, f"mined block #{block.index}"

    def reset(self):
        self.start()
        return True, "network reset"

    def run_business_demo(self):
        steps = [
            ("mandate", 1, 500.0, 0),
            ("mine", 0),
            ("spend", 1, 200.0, 0),
            ("mine", 0),
            ("spend", 1, 250.0, 0),
            ("mine", 0),
            ("spend", 1, 100.0, 0),
            ("spend", 1, 50.0, 0),
            ("mine", 0),
            ("mandate", 2, 300.0, 1),
            ("mine", 1),
            ("spend", 2, 150.0, 1),
            ("mine", 1),
        ]
        results = []
        with self.lock:
            if not self.nodes:
                return False, "network not started", []

        for step in steps:
            kind = step[0]
            if kind == "mandate":
                ok, msg = self.mandate(step[1], step[2], node_index=step[3])
            elif kind == "spend":
                ok, msg = self.spend(step[1], step[2], node_index=step[3])
            else:
                ok, msg = self.mine(node_index=step[1])
            results.append({"step": step, "ok": ok, "msg": msg})
            time.sleep(0.15)

        return True, "demo sequence executed", results

    def _build_agent_state(self, chain, pending):
        agents = {}
        for i, (_, agent_hex) in enumerate(self.agents, start=1):
            agents[agent_hex] = {
                "agent": i,
                "pubkey": agent_hex,
                "limit": 0.0,
                "spent_confirmed": 0.0,
                "spent_pending": 0.0,
            }

        for block in chain:
            for tx in block["transactions"]:
                if tx.get("type") == "mandate":
                    p = tx["agent_pubkey"]
                    if p in agents:
                        agents[p]["limit"] = float(tx["max_amount"])
                        agents[p]["spent_confirmed"] = 0.0
                elif tx.get("type") == "spend":
                    p = tx["agent_pubkey"]
                    if p in agents:
                        agents[p]["spent_confirmed"] += float(tx["amount"])

        for tx in pending:
            if tx.get("type") == "spend":
                p = tx.get("agent_pubkey")
                if p in agents:
                    agents[p]["spent_pending"] += float(tx["amount"])

        out = []
        for agent in agents.values():
            total = agent["spent_confirmed"] + agent["spent_pending"]
            agent["remaining"] = max(agent["limit"] - total, 0.0)
            agent["utilization"] = 0.0 if agent["limit"] <= 0 else min(total / agent["limit"], 1.0)
            out.append(agent)
        out.sort(key=lambda a: a["agent"])
        return out

    def state(self):
        with self.lock:
            if not self.nodes:
                return {
                    "ready": False,
                    "message": "network offline",
                    "events": self.events,
                }

            node0 = self.nodes[0]
            chain = node0.bc.get_chain()
            pending = node0.bc.get_pending_transactions()

            tips = [n.bc.chain[-1].hash for n in self.nodes]
            consensus = len(set(tips)) == 1

            summary_blocks = []
            for block in chain:
                txs = []
                for tx in block["transactions"]:
                    if tx["type"] == "mandate":
                        txs.append({
                            "type": "mandate",
                            "agent": tx["agent_pubkey"][:10],
                            "max_amount": float(tx["max_amount"]),
                        })
                    elif tx["type"] == "spend":
                        txs.append({
                            "type": "spend",
                            "agent": tx["agent_pubkey"][:10],
                            "amount": float(tx["amount"]),
                        })
                summary_blocks.append({
                    "index": block["index"],
                    "hash": block["hash"],
                    "previous_hash": block["previous_hash"],
                    "tx_count": len(block["transactions"]),
                    "transactions": txs,
                })

            return {
                "ready": True,
                "consensus": consensus,
                "chain_length": len(chain),
                "pending_count": len(pending),
                "difficulty": node0.bc.difficulty,
                "nodes": [
                    {
                        "addr": n.listen_addr,
                        "tip": n.bc.chain[-1].hash,
                        "height": n.bc.get_chain_length(),
                        "peers_seen": len(n.peer.get_peer_list()),
                    }
                    for n in self.nodes
                ],
                "agents": self._build_agent_state(chain, pending),
                "blocks": summary_blocks,
                "events": self.events,
            }


NETWORK = DemoNetwork()


class DashboardHandler(BaseHTTPRequestHandler):
    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, rel_path, content_type):
        path = WEB_DIR / rel_path
        if not path.exists():
            self.send_error(404)
            return
        content = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._serve_file("index.html", "text/html; charset=utf-8")
            return
        if self.path == "/app.js":
            self._serve_file("app.js", "text/javascript; charset=utf-8")
            return
        if self.path == "/styles.css":
            self._serve_file("styles.css", "text/css; charset=utf-8")
            return
        if self.path == "/api/state":
            self._json(200, NETWORK.state())
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/api/action":
            self.send_error(404)
            return

        try:
            content_len = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_len)
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            self._json(400, {"ok": False, "error": "invalid json"})
            return

        action = data.get("action")
        if action == "reset":
            ok, msg = NETWORK.reset()
            self._json(200, {"ok": ok, "msg": msg})
            return
        if action == "mine":
            ok, msg = NETWORK.mine(node_index=int(data.get("node", 1)) - 1)
            self._json(200, {"ok": ok, "msg": msg})
            return
        if action == "mandate":
            ok, msg = NETWORK.mandate(
                agent_index=int(data.get("agent", 1)),
                max_amount=float(data.get("amount", 500)),
                node_index=int(data.get("node", 1)) - 1,
            )
            self._json(200, {"ok": ok, "msg": msg})
            return
        if action == "spend":
            ok, msg = NETWORK.spend(
                agent_index=int(data.get("agent", 1)),
                amount=float(data.get("amount", 100)),
                node_index=int(data.get("node", 1)) - 1,
            )
            self._json(200, {"ok": ok, "msg": msg})
            return
        if action == "run_demo":
            ok, msg, results = NETWORK.run_business_demo()
            self._json(200, {"ok": ok, "msg": msg, "results": results})
            return

        self._json(400, {"ok": False, "error": "unknown action"})


def main():
    parser = argparse.ArgumentParser(description="Allowance dashboard web server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    NETWORK.start()
    atexit.register(NETWORK.stop)

    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"dashboard running at http://{args.host}:{args.port}")

    def _shutdown(_sig, _frame):
        server.shutdown()
        NETWORK.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    server.serve_forever()


if __name__ == "__main__":
    main()
