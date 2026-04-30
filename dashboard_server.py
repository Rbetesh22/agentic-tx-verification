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

from shopping_agent import AGENT as SHOPPING_AGENT

TRACKER_ADDR = "127.0.0.1:9000"
PEER_ADDRS = ["127.0.0.1:9001", "127.0.0.1:9002", "127.0.0.1:9003", "127.0.0.1:9004"]
DIFFICULTY = 8
WEB_DIR = Path(__file__).parent / "web"



class DemoNetwork:
    def __init__(self):
        self.lock = threading.Lock()
        self.tracker_proc = None
        self.nodes = []
        self.shopper_priv = None
        self.shopper_hex = None
        self.merchant_hex = None
        self.budget = 0.0
        self.events = []

        # Shopping workflow state
        self.pending_findings = []  # Items found by agent, awaiting approval
        self.approved_items = []    # Items approved by user
        self.search_in_progress = False
        self.last_preferences = None

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
            self.log("🚀 Shopping Agent ready: tracker + 4 nodes started")

    def stop(self):
        with self.lock:
            self._stop_locked()

    def _init_keys_locked(self):
        shopper_priv, shopper_pub = generate_keypair()
        self.shopper_priv = shopper_priv
        self.shopper_hex = serialize_public_key(shopper_pub)

        _merchant_priv, merchant_pub = generate_keypair()
        self.merchant_hex = serialize_public_key(merchant_pub)
        self.budget = 0.0
        self.events = []

        # Reset shopping state
        self.pending_findings = []
        self.approved_items = []
        self.search_in_progress = False
        self.last_preferences = None

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

    def set_budget(self, amount: float, period_days: int = None, node_index: int = 0):
        """Set the shopper's budget (as a mandate transaction)."""
        with self.lock:
            if not self.nodes:
                return False, "network not started"
            self.budget = float(amount)
            # determine period in days (default weekly)
            period_days = int(period_days) if period_days is not None else getattr(self, "_last_period_days", 7)
            self._last_period_days = period_days
            period_seconds = int(period_days) * 24 * 3600
            start_ts = time.time()
            # create a mandate tx on behalf of the merchant with period metadata
            tx = self._node(node_index).create_mandate(
                self.shopper_priv,
                self.shopper_hex,
                self.shopper_hex,  # Mandate to self
                float(amount),
                period_seconds=period_seconds,
                start_ts=start_ts,
            )
            accepted = self._node(node_index).submit_transaction(tx)
            if accepted:
                # Confirm the mandate immediately so budget enforcement/state update
                # are visible before any approval attempts.
                mined = self._node(node_index).mine()
                self.log(f"💳 Budget set: ${amount:.2f} ({period_days}d)")
                if mined is not None:
                    self.log(f"⛓️ Mandate confirmed in block #{mined.index}")
                return True, f"budget ${amount:.2f} approved"
            self.log(f"💳 Budget set to ${amount:.2f} (pending)")
            return True, f"budget ${amount:.2f} pending"


    def search_products(self, budget: float, style: str, size: str, occasion: str = None) -> tuple[bool, str]:
        """Agent searches for products matching user preferences."""
        with self.lock:
            if not self.nodes:
                return False, "network not started"
            
            self.search_in_progress = True
            self.pending_findings = []
            self.last_preferences = {
                "budget": budget,
                "style": style,
                "size": size,
                "occasion": occasion,
            }
            
            # Agent searches
            findings = SHOPPING_AGENT.search_products(
                budget=budget,
                style=style,
                size=size,
                occasion=occasion,
                max_results=5,
            )
            
            if not findings:
                self.search_in_progress = False
                self.log(f"🔍 Agent searched (${budget:.2f}, {style}) → No matches found")
                return False, "no products match your preferences"
            
            # Store findings for approval
            self.pending_findings = findings
            self.search_in_progress = False
            self.log(f"🔍 Agent searched (${budget:.2f}, {style}) → Found {len(findings)} items")
            
            return True, f"found {len(findings)} items for your approval"

    def approve_purchase(self, product_idx: int) -> tuple[bool, str]:
        """User approves an item for purchase."""
        with self.lock:
            if not self.nodes:
                return False, "network not started"
            
            if not (0 <= product_idx < len(self.pending_findings)):
                return False, "invalid product selection"
            
            product = self.pending_findings[product_idx]
            price = float(product["price"])
            
            # Create spend transaction
            tx = self._node(0).create_spend(
                self.shopper_priv,
                self.shopper_hex,
                self.merchant_hex,
                price,
            )
            
            accepted = self._node(0).submit_transaction(tx)
            if accepted:
                self.approved_items.append(product)
                self.log(f"✅ Approved: {product['name']} (${price:.2f}) from {product['brand']}")
                return True, f"approved {product['name']}"
            
            # If rejected due to budget
            self.log(f"❌ Rejected: {product['name']} (${price:.2f}) - budget limit")
            return False, f"{product['name']} would exceed budget"

    def reject_purchase(self, product_idx: int) -> tuple[bool, str]:
        """User rejects an item (doesn't purchase)."""
        with self.lock:
            if not (0 <= product_idx < len(self.pending_findings)):
                return False, "invalid product selection"
            
            product = self.pending_findings[product_idx]
            self.log(f"👎 Rejected: {product['name']} from {product['brand']}")
            return True, f"rejected {product['name']}"
    def mine(self, node_index: int = 0):
        with self.lock:
            if not self.nodes:
                return False, "nothing to mine"
            block = self._node(node_index).mine()
            if not block:
                return False, "nothing to mine"
            tx_count = len(block.transactions)
            self.log(f"⛏️ Block #{block.index} mined ({tx_count} tx)")
            return True, f"block #{block.index} ({tx_count} tx)"

    def reset(self):
        self.start()
        return True, "reset complete"


    def _build_shopper_state(self, chain, pending):
        """Build state for the shopper's budget and purchases."""
        limit = 0.0
        spent_confirmed = 0.0
        spent_pending = 0.0
        purchases = []

        # Track confirmed transactions
        for block in chain:
            for tx in block["transactions"]:
                if tx.get("type") == "mandate" and tx.get("agent_pubkey") == self.shopper_hex:
                    limit = float(tx["max_amount"])
                elif tx.get("type") == "spend" and tx.get("agent_pubkey") == self.shopper_hex:
                    amt = float(tx["amount"])
                    spent_confirmed += amt
                    purchases.append({"amount": amt, "confirmed": True})

        # Track pending purchases
        for tx in pending:
            if tx.get("type") == "spend" and tx.get("agent_pubkey") == self.shopper_hex:
                amt = float(tx["amount"])
                spent_pending += amt
                purchases.append({"amount": amt, "confirmed": False})

        total = spent_confirmed + spent_pending
        remaining = max(limit - total, 0.0)
        return {
            "budget": limit,
            "spent": spent_confirmed,
            "pending": spent_pending,
            "total": total,
            "remaining": remaining,
            "utilization": 0.0 if limit <= 0 else min(total / limit, 1.0),
            "purchases": purchases,
        }

    def state(self):
        with self.lock:
            if not self.nodes:
                return {
                    "ready": False,
                    "message": "network offline",
                    "events": self.events,
                                    "search_in_progress": False,
                                    "pending_findings": [],
                }

            node0 = self.nodes[0]
            chain = node0.bc.get_chain()
            pending = node0.bc.get_pending_transactions()

            tips = [n.bc.chain[-1].hash for n in self.nodes]
            consensus = len(set(tips)) == 1
            
            # Build transaction log from blockchain
            tx_events = []
            for block_idx, block in enumerate(chain):
                if block_idx == 0:
                    continue  # Skip genesis block
                block_ts = block.get("timestamp", time.time())
                for tx in block["transactions"]:
                    tx_type = tx.get("type")
                    if tx.get("agent_pubkey") == self.shopper_hex:
                        if tx_type == "mandate":
                            amt = float(tx.get("max_amount", 0))
                            period = tx.get("period_seconds", 7 * 24 * 3600)
                            period_days = period // (24 * 3600)
                            tx_events.append({
                                "ts": block_ts,
                                "text": f"💳 Mandate: ${amt:.2f} ({period_days}d budget)",
                            })
                        elif tx_type == "spend":
                            amt = float(tx.get("amount", 0))
                            tx_events.append({
                                "ts": block_ts,
                                "text": f"🛍️ Spend: ${amt:.2f} confirmed on chain",
                            })
                
                # Log block creation
                if block_idx > 0:
                    tx_count = len(block["transactions"])
                    tx_events.append({
                        "ts": block_ts,
                        "text": f"⛓️ Block #{block_idx} confirmed ({tx_count} tx)",
                    })
            
            # Combine transaction events with manual events, sorted by timestamp
            combined_events = self.events + tx_events
            combined_events.sort(key=lambda e: e.get("ts", 0))
            # Keep only last 100 combined
            combined_events = combined_events[-100:]

            return {
                "ready": True,
                "consensus": consensus,
                "chain_length": len(chain),
                "pending_count": len(pending),
                "difficulty": node0.bc.difficulty,
                "shopper": self._build_shopper_state(chain, pending),
                "nodes": [
                    {
                        "addr": n.listen_addr,
                        "tip": n.bc.chain[-1].hash,
                        "height": n.bc.get_chain_length(),
                    }
                    for n in self.nodes
                ],
                "events": combined_events,
                # Include shopping state
                "search_in_progress": self.search_in_progress,
                "pending_findings": self.pending_findings,
                "approved_items": self.approved_items,
                "last_preferences": self.last_preferences,
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
            ok, msg = NETWORK.mine()
            self._json(200, {"ok": ok, "msg": msg})
            return
        if action == "set_budget":
            amt = float(data.get("amount", 200))
            period_days = data.get("period_days")
            try:
                pd = int(period_days) if period_days is not None else None
            except Exception:
                pd = None
            ok, msg = NETWORK.set_budget(amt, period_days=pd)
            self._json(200, {"ok": ok, "msg": msg})
            return
        if action == "search":
            budget = float(data.get("budget", 200))
            style = data.get("style", "casual")
            size = data.get("size", "M")
            occasion = data.get("occasion")
            ok, msg = NETWORK.search_products(budget, style, size, occasion)
            self._json(200, {"ok": ok, "msg": msg})
            return
        if action == "approve":
            product_idx = int(data.get("product_idx", 0))
            ok, msg = NETWORK.approve_purchase(product_idx)
            self._json(200, {"ok": ok, "msg": msg})
            return
        if action == "reject":
            product_idx = int(data.get("product_idx", 0))
            ok, msg = NETWORK.reject_purchase(product_idx)
            self._json(200, {"ok": ok, "msg": msg})
            return

        self._json(400, {"ok": False, "error": "unknown action"})


def main():
    parser = argparse.ArgumentParser(description="Shopping Agent dashboard web server")
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
