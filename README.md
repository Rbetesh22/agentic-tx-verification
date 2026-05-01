# Allowance

P2P blockchain that enforces AI agent spending limits approved by owners.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install cryptography
```

## How to use

```bash
python demo.py           # Run live demo (tracker + 4 nodes)
python -m pytest -q      # Run 106 tests
python dashboard_server.py  # Run dashboard at http://127.0.0.1:8080
python tracker.py --port 9000             # Start tracker
python node.py --addr 127.0.0.1:9001 --tracker 127.0.0.1:9000  # Start node
```

## Files

- block.py — Block structure, Merkle tree, mining
- blockchain.py — Ledger, validation, fork resolution
- crypto_utils.py — key gen, signing, verification
- peer.py — P2P networking, peer discovery
- tracker.py — omnipotent peer tracker
- node.py — Node (Peer + Blockchain), message handlers
- messages.py — JSON message framing
- demo.py — Live scenario: owner -> agent -> merchant spending
- dashboard_server.py — API + static dashboard server
- web/ - Frontend UI (business workflow dashboard)
- tests/ — 106 unit/integration tests
- DESIGN.md — Architecture
- TESTING.md - Test descriptions

---
### AI Assistance

- GitHub Copilot used for:
  - Assistance in networking and blockchain logic
  - Test generation in [tests/test\_\*.py](tests/)
  - frontend demo
  - Makefile

## Limitations / next steps

### Currently:

- Single tracker (centralized discovery; no backup)
- Proof-of-work difficulty is fixed (no dynamic adjustment)
- All nodes store full blockchain (no light clients)

### In the future we hope to add:

Dynamic difficulty adjustments based on block arrival time, signature aggregation to reduce block size, batch verification for faster block validation, and a persistent database
