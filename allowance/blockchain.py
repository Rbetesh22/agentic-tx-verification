import time

from allowance.block import (
    Block,
    compute_merkle_root,
    mine_block,
    verify_transaction,
    tx_id,
    DEFAULT_DIFFICULTY,
)


class Blockchain:
    def __init__(self, difficulty: int = DEFAULT_DIFFICULTY):
        self.chain: list[Block] = [Block.create_genesis()]
        self.pending_transactions: list[dict] = []
        self.difficulty = difficulty

    def add_transaction(self, tx: dict) -> bool:
        if not verify_transaction(tx):
            return False

        if tx["type"] == "spend":
            if not self._validate_spend(tx):
                return False

        self.pending_transactions.append(tx)
        return True

    def mine_pending(self) -> "Block | None":
        if not self.pending_transactions:
            return None

        last = self.chain[-1]
        block = Block(
            index=len(self.chain),
            previous_hash=last.hash,
            timestamp=time.time(),
            transactions=list(self.pending_transactions),
        )
        block = mine_block(block, self.difficulty)
        self.chain.append(block)
        self.pending_transactions.clear()
        return block

    def validate_and_add_block(self, block_dict: dict) -> bool:
        block = Block.from_dict(block_dict)
        last = self.chain[-1]

        if block.index != len(self.chain):
            return False
        if block.previous_hash != last.hash:
            return False
        if block.hash != block.compute_hash():
            return False
        if int(block.hash, 16) >= 2 ** (256 - self.difficulty):
            return False
        if block.merkle_root != compute_merkle_root(block.transactions):
            return False

        for tx in block.transactions:
            if not verify_transaction(tx):
                return False
            if tx["type"] == "spend":
                if not self._validate_spend(tx, chain=self.chain + [block]):
                    return False

        self.chain.append(block)
        mined_ids = {tx_id(tx) for tx in block.transactions}
        self.pending_transactions = [
            tx for tx in self.pending_transactions if tx_id(tx) not in mined_ids
        ]
        return True

    def replace_chain(self, chain_dicts: list[dict]) -> bool:
        if len(chain_dicts) <= len(self.chain):
            return False

        new_chain = [Block.from_dict(d) for d in chain_dicts]
        if not self._validate_chain(new_chain):
            return False

        self.chain = new_chain
        on_chain_ids = set()
        for block in self.chain:
            for tx in block.transactions:
                on_chain_ids.add(tx_id(tx))
        self.pending_transactions = [
            tx for tx in self.pending_transactions if tx_id(tx) not in on_chain_ids
        ]
        return True

    def get_chain(self) -> list[dict]:
        return [block.to_dict() for block in self.chain]

    def get_pending_transactions(self) -> list[dict]:
        return list(self.pending_transactions)

    def get_chain_length(self) -> int:
        return len(self.chain)

    def _validate_chain(self, chain: list[Block]) -> bool:
        if not chain:
            return False

        genesis = Block.create_genesis()
        if chain[0].hash != genesis.hash:
            return False

        for i in range(1, len(chain)):
            block = chain[i]
            prev = chain[i - 1]

            if block.previous_hash != prev.hash:
                return False
            if block.hash != block.compute_hash():
                return False
            if int(block.hash, 16) >= 2 ** (256 - self.difficulty):
                return False
            if block.merkle_root != compute_merkle_root(block.transactions):
                return False

            for tx in block.transactions:
                if not verify_transaction(tx):
                    return False
                if tx["type"] == "spend":
                    if not self._validate_spend(tx, chain=chain[:i + 1]):
                        return False

        return True

    def _find_mandate(self, agent_pubkey: str, chain: list[Block] | None = None) -> "tuple[dict, int] | None":
        chain = chain if chain is not None else self.chain
        result = None
        for block in chain:
            for tx in block.transactions:
                if tx.get("type") == "mandate" and tx.get("agent_pubkey") == agent_pubkey:
                    result = (tx, block.index)
        return result

    def _total_spent(self, agent_pubkey: str, after_block: int = 0, chain: list[Block] | None = None, exclude_tx: dict | None = None) -> float:
        chain = chain if chain is not None else self.chain
        total = 0.0
        for block in chain:
            if block.index <= after_block:
                continue
            for tx in block.transactions:
                if tx.get("type") == "spend" and tx.get("agent_pubkey") == agent_pubkey:
                    if exclude_tx is not None and tx is exclude_tx:
                        continue
                    total += tx["amount"]
        return total

    def _pending_spent(self, agent_pubkey: str) -> float:
        total = 0.0
        for tx in self.pending_transactions:
            if tx.get("type") == "spend" and tx.get("agent_pubkey") == agent_pubkey:
                total += tx["amount"]
        return total

    def _validate_spend(self, tx: dict, chain: list[Block] | None = None) -> bool:
        chain = chain if chain is not None else self.chain

        mandate_info = self._find_mandate(tx["agent_pubkey"], chain)
        if mandate_info is None:
            return False

        mandate, mandate_block_idx = mandate_info
        spent_on_chain = self._total_spent(tx["agent_pubkey"], after_block=mandate_block_idx, chain=chain, exclude_tx=tx)

        # also count pending spends to prevent over-commitment in the mempool
        if chain is self.chain:
            spent_on_chain += self._pending_spent(tx["agent_pubkey"])

        return spent_on_chain + tx["amount"] <= mandate["max_amount"]
