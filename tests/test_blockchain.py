import hashlib
import json

from blockchain import Blockchain
from block import tx_signable_payload, tx_id, mine_block, Block, compute_merkle_root
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


def _setup_keys():
    owner_priv, owner_pub = generate_keypair()
    agent_priv, agent_pub = generate_keypair()
    merchant_priv, merchant_pub = generate_keypair()
    return (
        owner_priv, serialize_public_key(owner_pub),
        agent_priv, serialize_public_key(agent_pub),
        merchant_priv, serialize_public_key(merchant_pub),
    )


# init

def test_genesis_exists():
    bc = Blockchain(difficulty=8)
    assert bc.get_chain_length() == 1
    assert bc.chain[0].index == 0


def test_all_nodes_same_genesis():
    bc1 = Blockchain(difficulty=8)
    bc2 = Blockchain(difficulty=8)
    assert bc1.chain[0].hash == bc2.chain[0].hash


# add_transaction

def test_add_mandate_transaction():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_hex, _ap, agent_hex, _mp, _mh = _setup_keys()
    tx = _make_mandate(owner_priv, owner_hex, agent_hex, 100.0)
    assert bc.add_transaction(tx)
    assert len(bc.get_pending_transactions()) == 1


def test_reject_invalid_signature():
    bc = Blockchain(difficulty=8)
    tx = {
        "type": "mandate",
        "owner_pubkey": "badkey",
        "agent_pubkey": "otherkey",
        "max_amount": 100.0,
        "signature": "badsig",
    }
    assert not bc.add_transaction(tx)
    assert len(bc.get_pending_transactions()) == 0


def test_reject_no_signature():
    bc = Blockchain(difficulty=8)
    tx = {"type": "mandate", "owner_pubkey": "a", "agent_pubkey": "b", "max_amount": 100.0}
    assert not bc.add_transaction(tx)


def test_reject_tampered_transaction():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_hex, _ap, agent_hex, _mp, _mh = _setup_keys()
    tx = _make_mandate(owner_priv, owner_hex, agent_hex, 100.0)
    tx["max_amount"] = 999999
    assert not bc.add_transaction(tx)


# mine_pending

def test_mine_block():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_hex, _ap, agent_hex, _mp, _mh = _setup_keys()
    tx = _make_mandate(owner_priv, owner_hex, agent_hex, 100.0)
    bc.add_transaction(tx)
    block = bc.mine_pending()
    assert block is not None
    assert block.index == 1
    assert bc.get_chain_length() == 2
    assert len(bc.get_pending_transactions()) == 0


def test_mine_no_pending():
    bc = Blockchain(difficulty=8)
    assert bc.mine_pending() is None


def test_mine_clears_pending():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_hex, _ap, agent_hex, _mp, _mh = _setup_keys()
    bc.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 100.0))
    bc.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 200.0))
    block = bc.mine_pending()
    assert len(block.transactions) == 2
    assert len(bc.get_pending_transactions()) == 0


def test_mine_links_to_previous():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_hex, _ap, agent_hex, _mp, _mh = _setup_keys()
    genesis_hash = bc.chain[0].hash
    bc.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 100.0))
    block = bc.mine_pending()
    assert block.previous_hash == genesis_hash


def test_mine_multiple_blocks():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_hex, _ap, agent_hex, _mp, _mh = _setup_keys()

    for i in range(3):
        bc.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, float(i)))
        bc.mine_pending()

    assert bc.get_chain_length() == 4
    for i in range(1, 4):
        assert bc.chain[i].previous_hash == bc.chain[i - 1].hash


# spend validation

def test_spend_within_limit():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_hex, agent_priv, agent_hex, _mp, merchant_hex = _setup_keys()

    bc.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 100.0))
    bc.mine_pending()

    assert bc.add_transaction(_make_spend(agent_priv, agent_hex, merchant_hex, 50.0))


def test_spend_exact_limit():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_hex, agent_priv, agent_hex, _mp, merchant_hex = _setup_keys()

    bc.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 100.0))
    bc.mine_pending()

    assert bc.add_transaction(_make_spend(agent_priv, agent_hex, merchant_hex, 100.0))


def test_spend_exceeds_limit():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_hex, agent_priv, agent_hex, _mp, merchant_hex = _setup_keys()

    bc.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 100.0))
    bc.mine_pending()

    assert not bc.add_transaction(_make_spend(agent_priv, agent_hex, merchant_hex, 150.0))


def test_spend_no_mandate():
    bc = Blockchain(difficulty=8)
    agent_priv, agent_pub = generate_keypair()
    _mp, merchant_pub = generate_keypair()
    spend = _make_spend(agent_priv, serialize_public_key(agent_pub), serialize_public_key(merchant_pub), 10.0)
    assert not bc.add_transaction(spend)


def test_cumulative_spend_limit():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_hex, agent_priv, agent_hex, _mp, merchant_hex = _setup_keys()

    bc.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 100.0))
    bc.mine_pending()

    bc.add_transaction(_make_spend(agent_priv, agent_hex, merchant_hex, 60.0))
    bc.mine_pending()

    assert not bc.add_transaction(_make_spend(agent_priv, agent_hex, merchant_hex, 50.0))
    assert bc.add_transaction(_make_spend(agent_priv, agent_hex, merchant_hex, 40.0))


def test_pending_spends_counted():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_hex, agent_priv, agent_hex, _mp, merchant_hex = _setup_keys()

    bc.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 100.0))
    bc.mine_pending()

    assert bc.add_transaction(_make_spend(agent_priv, agent_hex, merchant_hex, 60.0))
    assert not bc.add_transaction(_make_spend(agent_priv, agent_hex, merchant_hex, 50.0))
    assert bc.add_transaction(_make_spend(agent_priv, agent_hex, merchant_hex, 30.0))


def test_mandate_update_resets_allowance():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_hex, agent_priv, agent_hex, _mp, merchant_hex = _setup_keys()

    bc.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 100.0))
    bc.mine_pending()

    bc.add_transaction(_make_spend(agent_priv, agent_hex, merchant_hex, 80.0))
    bc.mine_pending()

    bc.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 200.0))
    bc.mine_pending()

    assert bc.add_transaction(_make_spend(agent_priv, agent_hex, merchant_hex, 150.0))


def test_multiple_agents_independent():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_pub = generate_keypair()
    owner_hex = serialize_public_key(owner_pub)

    agent1_priv, agent1_pub = generate_keypair()
    agent1_hex = serialize_public_key(agent1_pub)
    agent2_priv, agent2_pub = generate_keypair()
    agent2_hex = serialize_public_key(agent2_pub)

    _, merchant_pub = generate_keypair()
    merchant_hex = serialize_public_key(merchant_pub)

    bc.add_transaction(_make_mandate(owner_priv, owner_hex, agent1_hex, 100.0))
    bc.add_transaction(_make_mandate(owner_priv, owner_hex, agent2_hex, 50.0))
    bc.mine_pending()

    assert bc.add_transaction(_make_spend(agent1_priv, agent1_hex, merchant_hex, 80.0))
    assert bc.add_transaction(_make_spend(agent2_priv, agent2_hex, merchant_hex, 50.0))


# validate_and_add_block

def test_validate_and_add_block():
    bc1 = Blockchain(difficulty=8)
    bc2 = Blockchain(difficulty=8)
    owner_priv, owner_hex, _ap, agent_hex, _mp, _mh = _setup_keys()

    bc1.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 100.0))
    block = bc1.mine_pending()

    assert bc2.validate_and_add_block(block.to_dict())
    assert bc2.get_chain_length() == 2


def test_validate_block_removes_pending():
    bc1 = Blockchain(difficulty=8)
    bc2 = Blockchain(difficulty=8)
    owner_priv, owner_hex, _ap, agent_hex, _mp, _mh = _setup_keys()

    tx = _make_mandate(owner_priv, owner_hex, agent_hex, 100.0)
    bc1.add_transaction(tx)
    bc2.add_transaction(tx)
    assert len(bc2.get_pending_transactions()) == 1

    block = bc1.mine_pending()
    bc2.validate_and_add_block(block.to_dict())
    assert len(bc2.get_pending_transactions()) == 0


def test_reject_block_bad_prev_hash():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_hex, _ap, agent_hex, _mp, _mh = _setup_keys()
    tx = _make_mandate(owner_priv, owner_hex, agent_hex, 100.0)
    block = Block(index=1, previous_hash="bad" * 21 + "b", timestamp=1.0, transactions=[tx])
    block = mine_block(block, 8)
    assert not bc.validate_and_add_block(block.to_dict())


def test_reject_block_wrong_index():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_hex, _ap, agent_hex, _mp, _mh = _setup_keys()
    tx = _make_mandate(owner_priv, owner_hex, agent_hex, 100.0)
    block = Block(index=5, previous_hash=bc.chain[0].hash, timestamp=1.0, transactions=[tx])
    block = mine_block(block, 8)
    assert not bc.validate_and_add_block(block.to_dict())


def test_reject_block_bad_difficulty():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_hex, _ap, agent_hex, _mp, _mh = _setup_keys()
    tx = _make_mandate(owner_priv, owner_hex, agent_hex, 100.0)
    block = Block(index=1, previous_hash=bc.chain[0].hash, timestamp=1.0, transactions=[tx], nonce=0)
    block.hash = block.compute_hash()
    if int(block.hash, 16) >= 2 ** (256 - 8):
        assert not bc.validate_and_add_block(block.to_dict())


def test_reject_block_tampered_hash():
    bc1 = Blockchain(difficulty=8)
    bc2 = Blockchain(difficulty=8)
    owner_priv, owner_hex, _ap, agent_hex, _mp, _mh = _setup_keys()

    bc1.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 100.0))
    block = bc1.mine_pending()
    d = block.to_dict()
    d["hash"] = "0" * 64
    assert not bc2.validate_and_add_block(d)


def test_reject_block_tampered_merkle():
    bc1 = Blockchain(difficulty=8)
    bc2 = Blockchain(difficulty=8)
    owner_priv, owner_hex, _ap, agent_hex, _mp, _mh = _setup_keys()

    bc1.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 100.0))
    block = bc1.mine_pending()
    d = block.to_dict()
    d["merkle_root"] = "f" * 64
    header = json.dumps({
        "index": d["index"], "previous_hash": d["previous_hash"],
        "timestamp": d["timestamp"], "merkle_root": d["merkle_root"], "nonce": d["nonce"],
    }, sort_keys=True, separators=(",", ":")).encode()
    d["hash"] = hashlib.sha256(header).hexdigest()
    assert not bc2.validate_and_add_block(d)


def test_reject_block_with_invalid_tx_signature():
    bc = Blockchain(difficulty=8)
    tx = {
        "type": "mandate",
        "owner_pubkey": "badkey",
        "agent_pubkey": "otherkey",
        "max_amount": 100.0,
        "signature": "badsig",
    }
    block = Block(index=1, previous_hash=bc.chain[0].hash, timestamp=1.0, transactions=[tx])
    block = mine_block(block, 8)
    assert not bc.validate_and_add_block(block.to_dict())


def test_reject_block_with_overspend():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_hex, agent_priv, agent_hex, _mp, merchant_hex = _setup_keys()

    bc.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 100.0))
    bc.mine_pending()

    overspend = _make_spend(agent_priv, agent_hex, merchant_hex, 200.0)
    block = Block(index=2, previous_hash=bc.chain[-1].hash, timestamp=1.0, transactions=[overspend])
    block = mine_block(block, 8)
    assert not bc.validate_and_add_block(block.to_dict())


# fork resolution

def test_replace_with_longer_chain():
    bc1 = Blockchain(difficulty=8)
    bc2 = Blockchain(difficulty=8)
    owner_priv, owner_hex, _ap, agent_hex, _mp, _mh = _setup_keys()

    for i in range(2):
        bc1.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 100.0 + i))
        bc1.mine_pending()

    assert bc1.get_chain_length() == 3
    assert bc2.replace_chain(bc1.get_chain())
    assert bc2.get_chain_length() == 3


def test_reject_shorter_chain():
    bc1 = Blockchain(difficulty=8)
    bc2 = Blockchain(difficulty=8)
    owner_priv, owner_hex, _ap, agent_hex, _mp, _mh = _setup_keys()

    bc2.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 100.0))
    bc2.mine_pending()

    assert not bc2.replace_chain(bc1.get_chain())
    assert bc2.get_chain_length() == 2


def test_reject_invalid_incoming_chain():
    bc = Blockchain(difficulty=8)
    fake_genesis = Block(index=0, previous_hash="0" * 64, timestamp=999.0, transactions=[])
    fake_chain = [fake_genesis.to_dict()]
    b2 = Block(index=1, previous_hash=fake_genesis.hash, timestamp=1.0, transactions=[])
    b2 = mine_block(b2, 8)
    fake_chain.append(b2.to_dict())
    assert not bc.replace_chain(fake_chain)


def test_replace_chain_clears_pending():
    bc1 = Blockchain(difficulty=8)
    bc2 = Blockchain(difficulty=8)
    owner_priv, owner_hex, _ap, agent_hex, _mp, _mh = _setup_keys()

    tx = _make_mandate(owner_priv, owner_hex, agent_hex, 100.0)
    bc1.add_transaction(tx)
    bc1.mine_pending()

    bc2.add_transaction(tx)
    assert len(bc2.get_pending_transactions()) == 1

    bc1.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 200.0))
    bc1.mine_pending()

    bc2.replace_chain(bc1.get_chain())
    assert len(bc2.get_pending_transactions()) == 0


def test_reject_empty_chain():
    bc = Blockchain(difficulty=8)
    assert not bc.replace_chain([])


# serialization

def test_get_chain_returns_list_of_dicts():
    bc = Blockchain(difficulty=8)
    chain = bc.get_chain()
    assert isinstance(chain, list)
    assert isinstance(chain[0], dict)


def test_get_chain_json_serializable():
    bc = Blockchain(difficulty=8)
    owner_priv, owner_hex, agent_priv, agent_hex, _mp, merchant_hex = _setup_keys()
    bc.add_transaction(_make_mandate(owner_priv, owner_hex, agent_hex, 100.0))
    bc.mine_pending()
    bc.add_transaction(_make_spend(agent_priv, agent_hex, merchant_hex, 25.0))
    bc.mine_pending()

    json_str = json.dumps(bc.get_chain())
    assert isinstance(json_str, str)
    restored = json.loads(json_str)
    assert len(restored) == 3


# end-to-end

def test_full_demo_scenario():
    bc = Blockchain(difficulty=8)

    owner_priv, owner_pub = generate_keypair()
    agent_priv, agent_pub = generate_keypair()
    merchant_priv, merchant_pub = generate_keypair()
    owner_hex = serialize_public_key(owner_pub)
    agent_hex = serialize_public_key(agent_pub)
    merchant_hex = serialize_public_key(merchant_pub)

    mandate = _make_mandate(owner_priv, owner_hex, agent_hex, 500.0)
    assert bc.add_transaction(mandate)
    assert bc.mine_pending().index == 1

    assert bc.add_transaction(_make_spend(agent_priv, agent_hex, merchant_hex, 200.0))
    assert bc.mine_pending().index == 2

    assert bc.add_transaction(_make_spend(agent_priv, agent_hex, merchant_hex, 250.0))
    assert bc.mine_pending().index == 3

    assert not bc.add_transaction(_make_spend(agent_priv, agent_hex, merchant_hex, 100.0))

    assert bc.add_transaction(_make_spend(agent_priv, agent_hex, merchant_hex, 50.0))
    assert bc.mine_pending().index == 4

    assert bc.get_chain_length() == 5
    for i in range(1, 5):
        assert bc.chain[i].previous_hash == bc.chain[i - 1].hash

    bc2 = Blockchain(difficulty=8)
    assert bc2.replace_chain(bc.get_chain())
    assert bc2.get_chain_length() == 5
