import hashlib
import json
import time
from dataclasses import dataclass

from allowance.crypto_utils import verify

# cleans up the transaction for signing 
def tx_signable_payload(tx: dict) -> bytes:
    d = {k: v for k, v in sorted(tx.items()) if k != "signature"}
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")

# assigns transaction ID
def tx_id(tx: dict) -> str:
    return hashlib.sha256(tx_signable_payload(tx)).hexdigest()

# checks transaction signature
def verify_transaction(tx: dict) -> bool:
    sig = tx.get("signature")
    if not sig:
        return False

    payload = tx_signable_payload(tx)

    if tx.get("type") == "mandate":
        return verify(tx["owner_pubkey"], sig, payload)
    elif tx.get("type") == "spend":
        return verify(tx["agent_pubkey"], sig, payload)
    return False


def compute_merkle_root(transactions: list[dict]) -> str:
    if not transactions:
        return hashlib.sha256(b"").hexdigest()

    nodes = [bytes.fromhex(tx_id(tx)) for tx in transactions]

    while len(nodes) > 1:
        if len(nodes) % 2 == 1:
            nodes.append(nodes[-1])
        next_level = []
        for i in range(0, len(nodes), 2):
            combined = hashlib.sha256(nodes[i] + nodes[i + 1]).digest()
            next_level.append(combined)
        nodes = next_level

    return nodes[0].hex()


GENESIS_PREV_HASH = "0" * 64
DEFAULT_DIFFICULTY = 16


@dataclass
class Block:
    index: int
    previous_hash: str
    timestamp: float
    transactions: list[dict]
    nonce: int = 0
    merkle_root: str = ""
    hash: str = ""

    def __post_init__(self):
        if not self.merkle_root:
            self.merkle_root = compute_merkle_root(self.transactions)
        if not self.hash:
            self.hash = self.compute_hash()

    def compute_hash(self) -> str:
        header = json.dumps(
            {
                "index": self.index,
                "previous_hash": self.previous_hash,
                "timestamp": self.timestamp,
                "merkle_root": self.merkle_root,
                "nonce": self.nonce,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(header).hexdigest()

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "previous_hash": self.previous_hash,
            "timestamp": self.timestamp,
            "transactions": self.transactions,
            "nonce": self.nonce,
            "merkle_root": self.merkle_root,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Block":
        return cls(
            index=d["index"],
            previous_hash=d["previous_hash"],
            timestamp=d["timestamp"],
            transactions=d["transactions"],
            nonce=d["nonce"],
            merkle_root=d["merkle_root"],
            hash=d["hash"],
        )

    @staticmethod
    def create_genesis() -> "Block":
        return Block(
            index=0,
            previous_hash=GENESIS_PREV_HASH,
            timestamp=0.0,
            transactions=[],
            nonce=0,
        )


def mine_block(block: Block, difficulty: int = DEFAULT_DIFFICULTY) -> Block:
    target = 2 ** (256 - difficulty)
    block.merkle_root = compute_merkle_root(block.transactions)
    while int(block.compute_hash(), 16) >= target:
        block.nonce += 1
    block.hash = block.compute_hash()
    return block
