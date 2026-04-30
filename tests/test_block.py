import hashlib
import json

from block import (
    tx_signable_payload,
    tx_id,
    verify_transaction,
    compute_merkle_root,
    Block,
    mine_block,
    GENESIS_PREV_HASH,
    DEFAULT_DIFFICULTY,
)
from crypto_utils import generate_keypair, serialize_public_key, sign


def _make_mandate(owner_priv, owner_pub_hex, agent_pub_hex, max_amount):
    tx = {
        "type": "mandate",
        "owner_pubkey": owner_pub_hex,
        "agent_pubkey": agent_pub_hex,
        "max_amount": max_amount,
    }
    tx["signature"] = sign(owner_priv, tx_signable_payload(tx))
    return tx


def _make_spend(agent_priv, agent_pub_hex, merchant_pub_hex, amount):
    tx = {
        "type": "spend",
        "agent_pubkey": agent_pub_hex,
        "merchant_pubkey": merchant_pub_hex,
        "amount": amount,
    }
    tx["signature"] = sign(agent_priv, tx_signable_payload(tx))
    return tx


# tx_signable_payload

def test_tx_signable_payload_excludes_signature():
    tx = {"type": "mandate", "owner_pubkey": "a", "agent_pubkey": "b", "max_amount": 10, "signature": "sig123"}
    payload = tx_signable_payload(tx)
    assert b"signature" not in payload
    assert b"sig123" not in payload


def test_tx_signable_payload_key_order_independent():
    tx1 = {"type": "spend", "agent_pubkey": "a", "merchant_pubkey": "b", "amount": 5, "signature": "s"}
    tx2 = {"amount": 5, "merchant_pubkey": "b", "type": "spend", "agent_pubkey": "a", "signature": "s"}
    assert tx_signable_payload(tx1) == tx_signable_payload(tx2)


# tx_id

def test_tx_id_is_64_char_hex():
    tx = {"type": "mandate", "owner_pubkey": "a", "agent_pubkey": "b", "max_amount": 10, "signature": "s"}
    tid = tx_id(tx)
    assert len(tid) == 64
    int(tid, 16)


def test_tx_id_different_for_different_txs():
    tx1 = {"type": "mandate", "owner_pubkey": "a", "agent_pubkey": "b", "max_amount": 10, "signature": "s"}
    tx2 = {"type": "mandate", "owner_pubkey": "a", "agent_pubkey": "b", "max_amount": 20, "signature": "s"}
    assert tx_id(tx1) != tx_id(tx2)


def test_tx_id_ignores_signature_field():
    tx1 = {"type": "mandate", "owner_pubkey": "a", "agent_pubkey": "b", "max_amount": 10, "signature": "sig1"}
    tx2 = {"type": "mandate", "owner_pubkey": "a", "agent_pubkey": "b", "max_amount": 10, "signature": "sig2"}
    assert tx_id(tx1) == tx_id(tx2)


# verify_transaction

def test_verify_mandate_signature():
    owner_priv, owner_pub = generate_keypair()
    _agent_priv, agent_pub = generate_keypair()
    tx = _make_mandate(owner_priv, serialize_public_key(owner_pub), serialize_public_key(agent_pub), 100.0)
    assert verify_transaction(tx)


def test_verify_spend_signature():
    agent_priv, agent_pub = generate_keypair()
    _merchant_priv, merchant_pub = generate_keypair()
    tx = _make_spend(agent_priv, serialize_public_key(agent_pub), serialize_public_key(merchant_pub), 50.0)
    assert verify_transaction(tx)


def test_verify_tampered_amount():
    agent_priv, agent_pub = generate_keypair()
    _merchant_priv, merchant_pub = generate_keypair()
    tx = _make_spend(agent_priv, serialize_public_key(agent_pub), serialize_public_key(merchant_pub), 50.0)
    tx["amount"] = 999
    assert not verify_transaction(tx)


def test_verify_tampered_pubkey():
    owner_priv, owner_pub = generate_keypair()
    _agent_priv, agent_pub = generate_keypair()
    _, other_pub = generate_keypair()
    tx = _make_mandate(owner_priv, serialize_public_key(owner_pub), serialize_public_key(agent_pub), 100.0)
    tx["agent_pubkey"] = serialize_public_key(other_pub)
    assert not verify_transaction(tx)


def test_verify_no_signature():
    tx = {"type": "mandate", "owner_pubkey": "a", "agent_pubkey": "b", "max_amount": 10}
    assert not verify_transaction(tx)


def test_verify_empty_signature():
    tx = {"type": "mandate", "owner_pubkey": "a", "agent_pubkey": "b", "max_amount": 10, "signature": ""}
    assert not verify_transaction(tx)


def test_verify_unknown_type():
    tx = {"type": "unknown", "signature": "abc"}
    assert not verify_transaction(tx)


def test_mandate_signed_by_owner_not_agent():
    owner_priv, owner_pub = generate_keypair()
    agent_priv, agent_pub = generate_keypair()
    tx = {
        "type": "mandate",
        "owner_pubkey": serialize_public_key(owner_pub),
        "agent_pubkey": serialize_public_key(agent_pub),
        "max_amount": 100.0,
    }
    tx["signature"] = sign(agent_priv, tx_signable_payload(tx))
    assert not verify_transaction(tx)


def test_spend_signed_by_agent_not_merchant():
    agent_priv, agent_pub = generate_keypair()
    merchant_priv, merchant_pub = generate_keypair()
    tx = {
        "type": "spend",
        "agent_pubkey": serialize_public_key(agent_pub),
        "merchant_pubkey": serialize_public_key(merchant_pub),
        "amount": 50.0,
    }
    tx["signature"] = sign(merchant_priv, tx_signable_payload(tx))
    assert not verify_transaction(tx)


# merkle tree

def test_merkle_empty():
    assert compute_merkle_root([]) == hashlib.sha256(b"").hexdigest()


def test_merkle_single():
    tx = {"type": "mandate", "owner_pubkey": "a", "agent_pubkey": "b", "max_amount": 10, "signature": "s"}
    root = compute_merkle_root([tx])
    assert len(root) == 64
    assert root == tx_id(tx)


def test_merkle_two():
    tx1 = {"type": "mandate", "owner_pubkey": "a", "agent_pubkey": "b", "max_amount": 10, "signature": "s1"}
    tx2 = {"type": "mandate", "owner_pubkey": "a", "agent_pubkey": "c", "max_amount": 20, "signature": "s2"}
    root = compute_merkle_root([tx1, tx2])
    expected = hashlib.sha256(bytes.fromhex(tx_id(tx1)) + bytes.fromhex(tx_id(tx2))).hexdigest()
    assert root == expected


def test_merkle_three_odd():
    txs = [
        {"type": "mandate", "owner_pubkey": "a", "agent_pubkey": str(i), "max_amount": i, "signature": f"s{i}"}
        for i in range(3)
    ]
    root = compute_merkle_root(txs)
    ids = [bytes.fromhex(tx_id(tx)) for tx in txs]
    ids.append(ids[-1])
    h01 = hashlib.sha256(ids[0] + ids[1]).digest()
    h23 = hashlib.sha256(ids[2] + ids[3]).digest()
    expected = hashlib.sha256(h01 + h23).hexdigest()
    assert root == expected


def test_merkle_four_even():
    txs = [
        {"type": "mandate", "owner_pubkey": "a", "agent_pubkey": str(i), "max_amount": i, "signature": f"s{i}"}
        for i in range(4)
    ]
    root = compute_merkle_root(txs)
    ids = [bytes.fromhex(tx_id(tx)) for tx in txs]
    h01 = hashlib.sha256(ids[0] + ids[1]).digest()
    h23 = hashlib.sha256(ids[2] + ids[3]).digest()
    expected = hashlib.sha256(h01 + h23).hexdigest()
    assert root == expected


def test_merkle_order_matters():
    tx1 = {"type": "mandate", "owner_pubkey": "a", "agent_pubkey": "b", "max_amount": 10, "signature": "s1"}
    tx2 = {"type": "mandate", "owner_pubkey": "a", "agent_pubkey": "c", "max_amount": 20, "signature": "s2"}
    assert compute_merkle_root([tx1, tx2]) != compute_merkle_root([tx2, tx1])


# block

def test_genesis_block():
    g = Block.create_genesis()
    assert g.index == 0
    assert g.previous_hash == GENESIS_PREV_HASH
    assert g.timestamp == 0.0
    assert g.transactions == []
    assert g.nonce == 0
    assert g.hash == g.compute_hash()


def test_genesis_merkle_root():
    g = Block.create_genesis()
    assert g.merkle_root == hashlib.sha256(b"").hexdigest()


def test_block_auto_computes_merkle_and_hash():
    b = Block(index=1, previous_hash="a" * 64, timestamp=1.0, transactions=[])
    assert b.merkle_root == compute_merkle_root([])
    assert b.hash == b.compute_hash()


def test_block_hash_changes_with_nonce():
    b1 = Block(index=1, previous_hash="a" * 64, timestamp=1.0, transactions=[], nonce=0)
    b2 = Block(index=1, previous_hash="a" * 64, timestamp=1.0, transactions=[], nonce=1)
    assert b1.hash != b2.hash


def test_block_hash_changes_with_timestamp():
    b1 = Block(index=1, previous_hash="a" * 64, timestamp=1.0, transactions=[])
    b2 = Block(index=1, previous_hash="a" * 64, timestamp=2.0, transactions=[])
    assert b1.hash != b2.hash


def test_block_hash_changes_with_prev_hash():
    b1 = Block(index=1, previous_hash="a" * 64, timestamp=1.0, transactions=[])
    b2 = Block(index=1, previous_hash="b" * 64, timestamp=1.0, transactions=[])
    assert b1.hash != b2.hash


def test_block_hash_changes_with_transactions():
    tx = {"type": "mandate", "owner_pubkey": "a", "agent_pubkey": "b", "max_amount": 10, "signature": "s"}
    b1 = Block(index=1, previous_hash="a" * 64, timestamp=1.0, transactions=[])
    b2 = Block(index=1, previous_hash="a" * 64, timestamp=1.0, transactions=[tx])
    assert b1.hash != b2.hash


def test_block_serialization_roundtrip():
    g = Block.create_genesis()
    d = g.to_dict()
    restored = Block.from_dict(d)
    assert restored.hash == g.hash
    assert restored.index == g.index
    assert restored.merkle_root == g.merkle_root
    assert restored.nonce == g.nonce
    assert restored.previous_hash == g.previous_hash
    assert restored.timestamp == g.timestamp
    assert restored.transactions == g.transactions


def test_block_with_txs_serialization():
    owner_priv, owner_pub = generate_keypair()
    _, agent_pub = generate_keypair()
    tx = _make_mandate(owner_priv, serialize_public_key(owner_pub), serialize_public_key(agent_pub), 100.0)
    b = Block(index=1, previous_hash="a" * 64, timestamp=1.0, transactions=[tx])
    restored = Block.from_dict(b.to_dict())
    assert restored.hash == b.hash
    assert restored.transactions == b.transactions


def test_block_to_dict_is_json_serializable():
    g = Block.create_genesis()
    json_str = json.dumps(g.to_dict())
    assert isinstance(json_str, str)


# mining

def test_mine_block_easy():
    difficulty = 8
    b = Block(index=1, previous_hash="a" * 64, timestamp=1.0, transactions=[])
    b = mine_block(b, difficulty)
    assert int(b.hash, 16) < 2 ** (256 - difficulty)
    assert b.hash == b.compute_hash()


def test_mine_block_with_transactions():
    owner_priv, owner_pub = generate_keypair()
    _, agent_pub = generate_keypair()
    tx = _make_mandate(owner_priv, serialize_public_key(owner_pub), serialize_public_key(agent_pub), 100.0)

    b = Block(index=1, previous_hash="a" * 64, timestamp=1.0, transactions=[tx])
    b = mine_block(b, 8)
    assert int(b.hash, 16) < 2 ** (256 - 8)
    assert b.merkle_root == compute_merkle_root([tx])


def test_mine_block_nonce_incremented():
    b = Block(index=1, previous_hash="a" * 64, timestamp=1.0, transactions=[])
    original_hash = b.hash
    b = mine_block(b, 12)
    assert b.hash != original_hash or b.nonce == 0


def test_mine_block_default_difficulty():
    b = Block(index=1, previous_hash="a" * 64, timestamp=1.0, transactions=[])
    b = mine_block(b)
    assert int(b.hash, 16) < 2 ** (256 - DEFAULT_DIFFICULTY)
