import json
import socket
import threading
import time
import pytest

from messages import send_msg, recv_msg, parse_addr, JOIN, PEER_LIST, HEARTBEAT, LEAVE, TX, BLOCK
from tracker import broadcast_peer_list, _register_peer, _deregister_peer, _bump_heartbeat, peers, peers_lock
from peer import Peer
from node import Node
from blockchain import Blockchain
from block import tx_signable_payload
from crypto_utils import generate_keypair, serialize_public_key, sign


def create_test_mandate():
    owner_priv, owner_pub = generate_keypair()
    agent_priv, agent_pub = generate_keypair()
    owner_hex = serialize_public_key(owner_pub)
    agent_hex = serialize_public_key(agent_pub)
    
    tx = {
        "type": "mandate",
        "owner_pubkey": owner_hex,
        "agent_pubkey": agent_hex,
        "max_amount": 100.0,
    }
    tx["signature"] = sign(owner_priv, tx_signable_payload(tx))
    return tx, owner_priv, owner_hex, agent_priv, agent_hex


def create_test_spend(agent_priv, agent_hex, merchant_hex, amount=50.0):
    tx = {
        "type": "spend",
        "agent_pubkey": agent_hex,
        "merchant_pubkey": merchant_hex,
        "amount": amount,
    }
    tx["signature"] = sign(agent_priv, tx_signable_payload(tx))
    return tx


class TestMessageFraming:
    def test_send_recv_message(self):
        msg_out = {"type": "TEST", "data": "hello"}
        
        # Create a socket pair
        server_sock, client_sock = socket.socketpair()
        
        # Send from client
        send_msg(client_sock, msg_out)
        
        # Recv on server
        rfile = server_sock.makefile("r")
        msg_in = recv_msg(rfile)
        
        assert msg_in == msg_out
        rfile.close()
        server_sock.close()
        client_sock.close()

    def test_send_recv_multiple_messages(self):
        """Test sending multiple messages in sequence."""
        messages = [
            {"type": "MSG1", "id": 1},
            {"type": "MSG2", "id": 2},
            {"type": "MSG3", "id": 3},
        ]
        
        server_sock, client_sock = socket.socketpair()
        rfile = server_sock.makefile("r")
        
        for msg_out in messages:
            send_msg(client_sock, msg_out)
            msg_in = recv_msg(rfile)
            assert msg_in == msg_out
        
        rfile.close()
        server_sock.close()
        client_sock.close()

    def test_recv_eof_returns_none(self):
        """Test that recv_msg returns None on EOF."""
        server_sock, client_sock = socket.socketpair()
        rfile = server_sock.makefile("r")
        
        client_sock.close()
        msg = recv_msg(rfile)
        
        assert msg is None
        rfile.close()
        server_sock.close()

    def test_parse_addr(self):
        """Test address parsing."""
        addr = "127.0.0.1:9001"
        host, port = parse_addr(addr)
        assert host == "127.0.0.1"
        assert port == 9001

    def test_parse_addr_ipv6(self):
        """Test IPv6 address parsing."""
        addr = "[::1]:9001"
        host, port = parse_addr(addr)
        # parse_addr splits on last ':' so host keeps the brackets
        assert host == "[::1]"
        assert port == 9001


# ── Tracker Tests ──────────────────────────────────────────────────────────────

class TestTracker:
    """Test tracker peer registration, heartbeat, and list updates."""

    def setup_method(self):
        """Clear the peers registry before each test."""
        with peers_lock:
            peers.clear()

    def test_register_peer(self):
        """Test registering a peer with the tracker."""
        # Use a socket pair to avoid broadcast_peer_list() socket errors
        server_sock, client_sock = socket.socketpair()
        addr = "127.0.0.1:9001"
        pubkey = "abc123"
        
        # Temporarily disable broadcast by mocking it
        import tracker as tracker_module
        original_broadcast = tracker_module.broadcast_peer_list
        tracker_module.broadcast_peer_list = lambda: None
        
        _register_peer(addr, pubkey, server_sock)
        
        tracker_module.broadcast_peer_list = original_broadcast
        
        with peers_lock:
            assert addr in peers
            assert peers[addr]["pubkey"] == pubkey
        
        server_sock.close()
        client_sock.close()

    def test_deregister_peer(self):
        """Test deregistering a peer."""
        sock = socket.socket()
        addr = "127.0.0.1:9001"
        pubkey = "abc123"
        
        _register_peer(addr, pubkey, sock)
        _deregister_peer(addr, reason="test")
        
        with peers_lock:
            assert addr not in peers

    def test_bump_heartbeat(self):
        """Test updating heartbeat timestamp."""
        server_sock, client_sock = socket.socketpair()
        addr = "127.0.0.1:9001"
        pubkey = "abc123"
        
        import tracker as tracker_module
        original_broadcast = tracker_module.broadcast_peer_list
        tracker_module.broadcast_peer_list = lambda: None
        
        _register_peer(addr, pubkey, server_sock)
        
        tracker_module.broadcast_peer_list = original_broadcast
        
        with peers_lock:
            old_time = peers[addr]["last_heartbeat"]
        
        time.sleep(0.1)
        _bump_heartbeat(addr)
        
        with peers_lock:
            new_time = peers[addr]["last_heartbeat"]
            assert new_time > old_time
        
        server_sock.close()
        client_sock.close()

    def test_heartbeat_unknown_peer(self):
        """Test heartbeat from unknown peer is ignored (no crash)."""
        _bump_heartbeat("127.0.0.1:9999")  # Should not exist
        
        with peers_lock:
            assert "127.0.0.1:9999" not in peers


# ── Peer Handler Tests ─────────────────────────────────────────────────────────

class TestPeerHandlerRegistration:
    """Test that peer handlers can be registered and dispatched."""

    def test_register_single_handler(self):
        """Test registering a handler for a message type."""
        priv, pub = generate_keypair()
        pubkey = serialize_public_key(pub)
        peer = Peer("127.0.0.1:9001", "127.0.0.1:9000", pubkey)
        
        handler_called = []
        
        def test_handler(msg, sender):
            handler_called.append((msg, sender))
        
        peer.register_handler(TX, test_handler)
        
        assert TX in peer._handlers
        assert test_handler in peer._handlers[TX]

    def test_register_multiple_handlers_same_type(self):
        """Test registering multiple handlers for the same message type."""
        priv, pub = generate_keypair()
        pubkey = serialize_public_key(pub)
        peer = Peer("127.0.0.1:9001", "127.0.0.1:9000", pubkey)
        
        def handler1(msg, sender):
            pass
        
        def handler2(msg, sender):
            pass
        
        peer.register_handler(TX, handler1)
        peer.register_handler(TX, handler2)
        
        assert len(peer._handlers[TX]) == 2
        assert handler1 in peer._handlers[TX]
        assert handler2 in peer._handlers[TX]

    def test_dispatch_calls_handler(self):
        """Test that dispatch calls registered handlers."""
        priv, pub = generate_keypair()
        pubkey = serialize_public_key(pub)
        peer = Peer("127.0.0.1:9001", "127.0.0.1:9000", pubkey)
        
        results = []
        
        def test_handler(msg, sender):
            results.append({"msg": msg, "sender": sender})
        
        peer.register_handler(TX, test_handler)
        
        msg = {"type": TX, "tx": {"debug": "test"}}
        peer._dispatch(msg, "127.0.0.1:9002")
        
        assert len(results) == 1
        assert results[0]["msg"] == msg
        assert results[0]["sender"] == "127.0.0.1:9002"

    def test_dispatch_multiple_handlers(self):
        """Test that dispatch calls all registered handlers for a type."""
        priv, pub = generate_keypair()
        pubkey = serialize_public_key(pub)
        peer = Peer("127.0.0.1:9001", "127.0.0.1:9000", pubkey)
        
        results = []
        
        def handler1(msg, sender):
            results.append("handler1")
        
        def handler2(msg, sender):
            results.append("handler2")
        
        peer.register_handler(TX, handler1)
        peer.register_handler(TX, handler2)
        
        msg = {"type": TX, "tx": {"debug": "test"}}
        peer._dispatch(msg, "127.0.0.1:9002")
        
        assert len(results) == 2
        assert "handler1" in results
        assert "handler2" in results


# ── Node Handler Integration Tests ─────────────────────────────────────────────

class TestNodeHandlers:
    """Test that Node handlers correctly process blockchain messages."""

    def test_node_tx_handler_accepts_valid_tx(self):
        """Test that node accepts a valid transaction."""
        node = Node("127.0.0.1:9001", "127.0.0.1:9000", difficulty=8)
        
        mandate, _, _, _, _ = create_test_mandate()
        
        msg = {"type": TX, "tx": mandate}
        sender = "127.0.0.1:9002"
        
        # Call handler
        node._handle_tx(msg, sender)
        
        # Transaction should be in pending
        pending = node.bc.get_pending_transactions()
        assert len(pending) == 1
        assert pending[0] == mandate

    def test_node_tx_handler_rejects_invalid_tx(self):
        """Test that node rejects an invalid transaction."""
        node = Node("127.0.0.1:9001", "127.0.0.1:9000", difficulty=8)
        
        # Invalid tx: missing signature
        invalid_tx = {
            "type": "mandate",
            "owner_pubkey": "abc",
            "agent_pubkey": "def",
            "max_amount": 100.0,
        }
        
        msg = {"type": TX, "tx": invalid_tx}
        sender = "127.0.0.1:9002"
        
        # Call handler
        node._handle_tx(msg, sender)
        
        # Transaction should NOT be in pending
        pending = node.bc.get_pending_transactions()
        assert len(pending) == 0

    def test_node_tx_duplicate_ignored(self):
        """Test that duplicate transactions are not rebroadcast."""
        node = Node("127.0.0.1:9001", "127.0.0.1:9000", difficulty=8)
        
        mandate, _, _, _, _ = create_test_mandate()
        msg = {"type": TX, "tx": mandate}
        sender = "127.0.0.1:9002"
        
        # First call
        node._handle_tx(msg, sender)
        pending1 = node.bc.get_pending_transactions()
        
        # Second call (same tx)
        node._handle_tx(msg, sender)
        pending2 = node.bc.get_pending_transactions()
        
        # Should still have only 1 tx (not duplicated)
        assert len(pending1) == 1
        assert len(pending2) == 1

    def test_node_mining_creates_block(self):
        """Test that node.mine() creates and returns a block."""
        node = Node("127.0.0.1:9001", "127.0.0.1:9000", difficulty=8)
        
        mandate, _, _, _, _ = create_test_mandate()
        node.bc.add_transaction(mandate)
        
        block = node.mine()
        
        assert block is not None
        assert block.index == 1
        assert len(block.transactions) == 1
        assert node.bc.get_chain_length() == 2

    def test_node_mining_clears_pending(self):
        """Test that mining clears pending transactions."""
        node = Node("127.0.0.1:9001", "127.0.0.1:9000", difficulty=8)
        
        mandate, _, _, _, _ = create_test_mandate()
        node.bc.add_transaction(mandate)
        
        assert len(node.bc.get_pending_transactions()) == 1
        
        node.mine()
        
        assert len(node.bc.get_pending_transactions()) == 0

    def test_node_block_handler_accepts_valid_block(self):
        """Test that node accepts a valid block."""
        node1 = Node("127.0.0.1:9001", "127.0.0.1:9000", difficulty=8)
        node2 = Node("127.0.0.1:9002", "127.0.0.1:9000", difficulty=8)
        
        # Node 1 mines a block
        mandate, _, _, _, _ = create_test_mandate()
        node1.bc.add_transaction(mandate)
        block = node1.mine()
        
        # Node 2 receives the block
        msg = {"type": BLOCK, "block": block.to_dict()}
        sender = "127.0.0.1:9001"
        
        node2._handle_block(msg, sender)
        
        # Node 2 should have the block
        assert node2.bc.get_chain_length() == 2

    def test_node_chain_request_handler(self):
        """Test that node responds to chain requests."""
        node = Node("127.0.0.1:9001", "127.0.0.1:9000", difficulty=8)
        
        # Mine a block
        mandate, _, _, _, _ = create_test_mandate()
        node.bc.add_transaction(mandate)
        node.mine()
        
        chain_before = node.bc.get_chain()
        
        msg = {"type": "CHAIN_REQUEST", "from": "127.0.0.1:9002"}
        sender = "127.0.0.1:9002"
        
        # Handler would send chain via node.peer.send_to()
        # For testing, we just verify it doesn't crash
        node._handle_chain_request(msg, sender)
        
        # Chain should not have changed
        chain_after = node.bc.get_chain()
        assert len(chain_before) == len(chain_after)


# ── Integration Test: Spending Limit Across Network ────────────────────────────

class TestSpendingLimitNetwork:
    """Test that spending limits are enforced when transactions propagate."""

    def test_overspend_rejected_by_all_nodes(self):
        """Test that overspend is rejected by all independent nodes."""
        node1 = Node("127.0.0.1:9001", "127.0.0.1:9000", difficulty=8)
        node2 = Node("127.0.0.1:9002", "127.0.0.1:9000", difficulty=8)
        node3 = Node("127.0.0.1:9003", "127.0.0.1:9000", difficulty=8)
        
        mandate, owner_priv, owner_hex, agent_priv, agent_hex = create_test_mandate()
        merchant_priv, merchant_pub = generate_keypair()
        merchant_hex = serialize_public_key(merchant_pub)
        
        # All nodes add the mandate
        for node in [node1, node2, node3]:
            node.bc.add_transaction(mandate)
            node.bc.mine_pending()
        
        # Create valid spend
        spend1 = create_test_spend(agent_priv, agent_hex, merchant_hex, 60.0)
        
        # All nodes accept spend1
        for node in [node1, node2, node3]:
            result = node.bc.add_transaction(spend1)
            assert result
        
        # Create another valid spend (total = 110, limit still 100)
        spend2 = create_test_spend(agent_priv, agent_hex, merchant_hex, 50.0)
        
        # All nodes should REJECT spend2 (overspend)
        for node in [node1, node2, node3]:
            result = node.bc.add_transaction(spend2)
            assert not result  # All reject independently


# ── Consensus Test ────────────────────────────────────────────────────────────

class TestConsensus:
    """Test that multiple nodes reach consensus."""

    def test_fork_resolution_longest_chain_wins(self):
        """Test that longer valid chain is adopted."""
        node1 = Node("127.0.0.1:9001", "127.0.0.1:9000", difficulty=8)
        node2 = Node("127.0.0.1:9002", "127.0.0.1:9000", difficulty=8)
        
        mandate, _, _, _, _ = create_test_mandate()
        
        # Node 1: mine 2 blocks
        node1.bc.add_transaction(mandate)
        node1.bc.mine_pending()
        node1.bc.add_transaction(mandate)
        node1.bc.mine_pending()
        
        assert node1.bc.get_chain_length() == 3
        assert node2.bc.get_chain_length() == 1  # Still has only genesis
        
        # Node 2 receives node 1's chain
        chain = node1.bc.get_chain()
        node2.bc.replace_chain(chain)
        
        # Node 2 should now have the longer chain
        assert node2.bc.get_chain_length() == 3
        
        # Chains should be identical
        assert node2.bc.chain[-1].hash == node1.bc.chain[-1].hash

    def test_invalid_fork_rejected(self):
        """Test that invalid chains are not adopted."""
        node1 = Node("127.0.0.1:9001", "127.0.0.1:9000", difficulty=8)
        node2 = Node("127.0.0.1:9002", "127.0.0.1:9000", difficulty=8)
        
        mandate, _, _, _, _ = create_test_mandate()
        
        # Node 1: mine a block
        node1.bc.add_transaction(mandate)
        node1.bc.mine_pending()
        
        # Get chain and tamper with a transaction
        chain = node1.bc.get_chain()
        tampered_chain = [b.to_dict() for b in node1.bc.chain]
        tampered_chain[1]["transactions"][0]["amount"] = 9999  # Tamper
        
        # Node 2 tries to adopt tampered chain
        result = node2.bc.replace_chain(tampered_chain)
        
        # Should REJECT the invalid chain
        assert not result
        assert node2.bc.get_chain_length() == 1  # Still only genesis
