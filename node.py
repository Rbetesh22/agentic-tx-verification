import threading
import time
import json
import signal
import sys
import argparse

from peer import Peer
from messages import TX, BLOCK, CHAIN_REQUEST, CHAIN_RESPONSE
from blockchain import Blockchain
from block import tx_signable_payload, tx_id
from crypto_utils import generate_keypair, serialize_public_key, sign


class Node:
    def __init__(self, listen_addr, tracker_addr, difficulty=16):
        self.listen_addr = listen_addr
        self.tracker_addr = tracker_addr

        priv, pub = generate_keypair()
        self.private_key = priv
        self.pubkey = serialize_public_key(pub)

        self.bc = Blockchain(difficulty=difficulty)
        self.lock = threading.Lock()

        # track seen messages to avoid rebroadcast loops
        self._seen_txs = set()
        self._seen_blocks = set()

        self.peer = Peer(listen_addr, tracker_addr, self.pubkey)
        self.peer.register_handler(TX, self._handle_tx)
        self.peer.register_handler(BLOCK, self._handle_block)
        self.peer.register_handler(CHAIN_REQUEST, self._handle_chain_request)
        self.peer.register_handler(CHAIN_RESPONSE, self._handle_chain_response)

    def _log(self, msg):
        print(f"[node {self.listen_addr}] {msg}", flush=True)

    def _handle_tx(self, msg, sender_addr):
        tx = msg.get("tx")
        if not tx:
            return
        tid = tx_id(tx)
        if tid in self._seen_txs:
            return
        self._seen_txs.add(tid)

        with self.lock:
            accepted = self.bc.add_transaction(tx)
        if accepted:
            self._log(f"accepted tx {tid[:8]} from {sender_addr}")
            self.peer.broadcast(msg)
        else:
            self._log(f"rejected tx {tid[:8]} from {sender_addr}")

    def _handle_block(self, msg, sender_addr):
        block_dict = msg.get("block")
        if not block_dict:
            return
        bhash = block_dict.get("hash", "")
        if bhash in self._seen_blocks:
            return
        self._seen_blocks.add(bhash)

        with self.lock:
            accepted = self.bc.validate_and_add_block(block_dict)
        if accepted:
            self._log(f"accepted block #{block_dict['index']} from {sender_addr}")
            self.peer.broadcast(msg)
        else:
            self._log(f"rejected block #{block_dict.get('index','?')} from {sender_addr}")

    def _handle_chain_request(self, msg, sender_addr):
        reply_to = msg.get("from", sender_addr)
        with self.lock:
            chain = self.bc.get_chain()
        self.peer.send_to(reply_to, {"type": CHAIN_RESPONSE, "chain": chain})
        self._log(f"sent chain ({len(chain)} blocks) to {reply_to}")

    def _handle_chain_response(self, msg, sender_addr):
        chain_dicts = msg.get("chain")
        if not chain_dicts:
            return
        with self.lock:
            replaced = self.bc.replace_chain(chain_dicts)
        if replaced:
            self._log(f"adopted chain ({len(chain_dicts)} blocks) from {sender_addr}")
        else:
            self._log(f"kept current chain (received {len(chain_dicts)} blocks from {sender_addr})")

    def submit_transaction(self, tx_dict):
        tid = tx_id(tx_dict)
        self._seen_txs.add(tid)
        with self.lock:
            accepted = self.bc.add_transaction(tx_dict)
        if accepted:
            self.peer.broadcast({"type": TX, "tx": tx_dict})
            self._log(f"submitted tx {tid[:8]}")
        return accepted

    def mine(self):
        with self.lock:
            block = self.bc.mine_pending()
        if block:
            self._seen_blocks.add(block.hash)
            self.peer.broadcast({"type": BLOCK, "block": block.to_dict()})
            self._log(f"mined block #{block.index} hash={block.hash[:12]}...")
        return block

    def request_chain(self):
        peers = self.peer.get_peer_list()
        if peers:
            target = peers[0]["addr"]
            self.peer.send_to(target, {
                "type": CHAIN_REQUEST,
                "from": self.listen_addr,
            })
            self._log(f"requested chain from {target}")

    def create_mandate(self, owner_priv, owner_pub_hex, agent_pub_hex, max_amount, period_seconds=None, start_ts=None):
        tx = {
            "type": "mandate",
            "owner_pubkey": owner_pub_hex,
            "agent_pubkey": agent_pub_hex,
            "max_amount": max_amount,
        }
        # Optional time window for periodic budgets
        if period_seconds is not None:
            tx["period_seconds"] = int(period_seconds)
        if start_ts is not None:
            tx["start_ts"] = float(start_ts)
        tx["signature"] = sign(owner_priv, tx_signable_payload(tx))
        return tx

    def create_spend(self, agent_priv, agent_pub_hex, merchant_pub_hex, amount):
        tx = {
            "type": "spend",
            "agent_pubkey": agent_pub_hex,
            "merchant_pubkey": merchant_pub_hex,
            "amount": amount,
        }
        tx["signature"] = sign(agent_priv, tx_signable_payload(tx))
        return tx

    def start(self):
        self.peer.start()

    def stop(self):
        self.peer.stop()


def main():
    parser = argparse.ArgumentParser(description="Allowance blockchain node")
    parser.add_argument("--addr", required=True)
    parser.add_argument("--tracker", required=True)
    parser.add_argument("--difficulty", type=int, default=16)
    args = parser.parse_args()

    node = Node(args.addr, args.tracker, difficulty=args.difficulty)

    def _sigint(sig, frame):
        print()
        node.stop()
        sys.exit(0)
    signal.signal(signal.SIGINT, _sigint)

    node.start()


if __name__ == "__main__":
    main()
