import subprocess
import threading
import time
import sys
import os

from crypto_utils import generate_keypair, serialize_public_key, sign
from block import tx_signable_payload
from blockchain import Blockchain

TRACKER_ADDR = "127.0.0.1:9000"
PEER_ADDRS = ["127.0.0.1:9001", "127.0.0.1:9002", "127.0.0.1:9003", "127.0.0.1:9004"]
DIFFICULTY = 8

# suppress noisy output from peer/tracker
DEVNULL = open(os.devnull, "w")


def banner(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def step(n, text):
    print(f"  [{n}] {text}")


def wait(seconds=2):
    time.sleep(seconds)


def main():
    banner("ALLOWANCE BLOCKCHAIN — LIVE DEMO")
    print("  A blockchain that tracks AI agent spending on behalf of owners.")
    print("  Owners set spending limits. Agents spend. The chain enforces.\n")

    # generate keys
    step(0, "Generating keys for owner, 3 agents, and 1 merchant...")
    owner_priv, owner_pub = generate_keypair()
    owner_hex = serialize_public_key(owner_pub)

    agents = []
    for i in range(3):
        priv, pub = generate_keypair()
        agents.append((priv, serialize_public_key(pub)))

    merchant_priv, merchant_pub = generate_keypair()
    merchant_hex = serialize_public_key(merchant_pub)

    print(f"    Owner:    {owner_hex[:16]}...")
    for i, (_, ahex) in enumerate(agents):
        print(f"    Agent {i+1}:  {ahex[:16]}...")
    print(f"    Merchant: {merchant_hex[:16]}...")

    # start tracker
    banner("STARTING P2P NETWORK")
    step(1, "Starting tracker...")
    tracker_proc = subprocess.Popen(
        [sys.executable, "tracker.py"],
        stdout=DEVNULL, stderr=DEVNULL,
    )
    wait(1)

    # start nodes — import here so tracker is running first
    from node import Node

    nodes = []
    step(2, f"Starting 4 peer nodes...")
    for i, addr in enumerate(PEER_ADDRS):
        node = Node(addr, TRACKER_ADDR, difficulty=DIFFICULTY)
        t = threading.Thread(target=node.peer.start, daemon=True)
        # override the REPL so it doesn't block
        node.peer._repl = lambda: None
        t.start()
        nodes.append(node)
        wait(0.5)

    wait(2)
    step(3, "Peer discovery complete. All nodes connected.")
    for n in nodes:
        peers = n.peer.get_peer_list()
        print(f"    {n.listen_addr} sees {len(peers)} peers")

    # mandate
    banner("STEP 1: OWNER AUTHORIZES AGENT 1 TO SPEND $500")
    agent1_priv, agent1_hex = agents[0]
    mandate = nodes[0].create_mandate(owner_priv, owner_hex, agent1_hex, 500.0)
    ok = nodes[0].submit_transaction(mandate)
    step(4, f"Mandate submitted: {'accepted' if ok else 'REJECTED'}")
    print(f"    Agent 1 ({agent1_hex[:16]}...) can spend up to $500")

    wait(1)
    step(5, "Mining block with mandate...")
    block = nodes[0].mine()
    print(f"    Block #{block.index} mined, hash={block.hash[:16]}...")
    wait(2)

    # verify propagation
    step(6, "Checking chain propagation across all nodes...")
    for n in nodes:
        print(f"    {n.listen_addr}: chain length = {n.bc.get_chain_length()}")

    # spend 1
    banner("STEP 2: AGENT 1 SPENDS $200 AT MERCHANT")
    spend1 = nodes[0].create_spend(agent1_priv, agent1_hex, merchant_hex, 200.0)
    ok = nodes[0].submit_transaction(spend1)
    step(7, f"Spend $200: {'accepted' if ok else 'REJECTED'}")

    step(8, "Mining block with spend...")
    block = nodes[0].mine()
    print(f"    Block #{block.index} mined, hash={block.hash[:16]}...")
    wait(2)

    # spend 2
    banner("STEP 3: AGENT 1 SPENDS $250 AT MERCHANT")
    spend2 = nodes[0].create_spend(agent1_priv, agent1_hex, merchant_hex, 250.0)
    ok = nodes[0].submit_transaction(spend2)
    step(9, f"Spend $250: {'accepted' if ok else 'REJECTED'}")

    step(10, "Mining block with spend...")
    block = nodes[0].mine()
    print(f"    Block #{block.index} mined, hash={block.hash[:16]}...")
    wait(2)

    # overspend
    banner("STEP 4: AGENT 1 TRIES TO SPEND $100 (OVER LIMIT)")
    print("    Total so far: $200 + $250 = $450. Limit is $500.")
    print("    $450 + $100 = $550 > $500 — should be REJECTED\n")
    spend3 = nodes[0].create_spend(agent1_priv, agent1_hex, merchant_hex, 100.0)
    ok = nodes[0].submit_transaction(spend3)
    step(11, f"Spend $100: {'accepted' if ok else 'REJECTED (over limit)'}")

    # valid final spend
    banner("STEP 5: AGENT 1 SPENDS $50 (WITHIN LIMIT)")
    print("    $450 + $50 = $500 — exactly at limit, should be ACCEPTED\n")
    spend4 = nodes[0].create_spend(agent1_priv, agent1_hex, merchant_hex, 50.0)
    ok = nodes[0].submit_transaction(spend4)
    step(12, f"Spend $50: {'accepted' if ok else 'REJECTED'}")

    step(13, "Mining final block...")
    block = nodes[0].mine()
    print(f"    Block #{block.index} mined, hash={block.hash[:16]}...")
    wait(2)

    # second agent
    banner("STEP 6: OWNER AUTHORIZES AGENT 2, AGENT 2 SPENDS")
    agent2_priv, agent2_hex = agents[1]
    mandate2 = nodes[1].create_mandate(owner_priv, owner_hex, agent2_hex, 300.0)
    ok = nodes[1].submit_transaction(mandate2)
    step(14, f"Mandate for Agent 2 ($300 limit): {'accepted' if ok else 'REJECTED'}")

    step(15, "Mining mandate block...")
    block = nodes[1].mine()
    print(f"    Block #{block.index} mined on node 2, hash={block.hash[:16]}...")
    wait(2)

    spend5 = nodes[1].create_spend(agent2_priv, agent2_hex, merchant_hex, 150.0)
    ok = nodes[1].submit_transaction(spend5)
    step(16, f"Agent 2 spends $150: {'accepted' if ok else 'REJECTED'}")

    step(17, "Mining spend block...")
    block = nodes[1].mine()
    print(f"    Block #{block.index} mined on node 2, hash={block.hash[:16]}...")
    wait(2)

    # final state
    banner("FINAL CHAIN STATE")
    node0 = nodes[0]
    chain = node0.bc.get_chain()
    for b in chain:
        tx_summary = []
        for tx in b["transactions"]:
            if tx["type"] == "mandate":
                tx_summary.append(f"mandate(max=${tx['max_amount']})")
            elif tx["type"] == "spend":
                tx_summary.append(f"spend(${tx['amount']})")
        txs = ", ".join(tx_summary) if tx_summary else "genesis"
        print(f"  Block #{b['index']}  hash={b['hash'][:16]}...  txs=[{txs}]")

    print()
    step("*", "Checking all nodes have identical chains...")
    hashes = []
    for n in nodes:
        tip = n.bc.chain[-1].hash
        hashes.append(tip)
        print(f"    {n.listen_addr}: {n.bc.get_chain_length()} blocks, tip={tip[:16]}...")

    if len(set(hashes)) == 1:
        print("\n  ALL NODES IN CONSENSUS")
    else:
        print("\n  WARNING: nodes have different chain tips")

    banner("DEMO COMPLETE")

    # cleanup
    for n in nodes:
        try:
            n.stop()
        except:
            pass
    tracker_proc.terminate()
    tracker_proc.wait()


if __name__ == "__main__":
    main()
