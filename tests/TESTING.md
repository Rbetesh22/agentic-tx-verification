# TESTING

106 tests, ~0.6s total.

```bash
python -m pytest -q            # Run all tests
python -m pytest -v            # Verbose output
python -m pytest tests/test_crypto.py -v  # Single file
```

---

## Coverage

- **tests/test_crypto.py** (13 tests) — Keypair generation, signing, verification
- **tests/test_block.py** (34 tests) — Block structure, Merkle trees, mining
- **tests/test_blockchain.py** (36 tests) — Transaction validation, spending limits, fork resolution
- **tests/test_network.py** (23 tests) — Message framing, tracker, peer handlers, node handlers, consensus

Also: `demo.py` runs end-to-end scenario with tracker + 4 nodes.
