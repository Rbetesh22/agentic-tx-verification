## Project: Allowance

Blockchain that records AI agents spending money on behalf of their owners. Each owner sets a spending limit and the chain keeps a tamperproof record of what the agent actually spent and where

## P2P Network

1 tracker, 4 peers. The 3 peers act as agents, and 1 acts as a merchant. All run the same code and all participate equally in blockchain.

### Tracker

Only handles peer discovery (doesn't touch the blockchain)

- New peer sends `JOIN` with its address and public key, tracker adds it to the list and pushes the updated list to everyone
- Peers send `HEARTBEAT` every 5 seconds. If one misses 3 in a row, the tracker drops the peer and broadcasts the new list
- Peers can also send `LEAVE` to exit more cleanly

### Messages between peers

Once peers have the list, they talk directly over TCP in JSON format

- `TX` - new transaction
- `BLOCK` - newly mined block
- `CHAIN_REQUEST` - ask a peer for their chain
- `CHAIN_RESPONSE` - reply with the chain

New peer joining network asks an existing peer for the current chain, then adopts it after validating.

## Blockchain

### Block

```
index
prev_hash     (SHA256 of previous block)
merkle_root   (root of transactions in this block)
timestamp
nonce         (PoW solution)
transactions
```

Block hash is SHA256 of above fields

### Transactions

Two types:

**Mandate** - owner authorizes their agent with a spending limit:
`{ type: "mandate", owner_pubkey, agent_pubkey, max_amount, signature }`

**Spend** - agent pays some merchant:
`{ type: "spend", agent_pubkey, merchant_pubkey, amount, signature }`

### Mining

Proof of work. Find a `nonce` so the block's hash has at least N leading zero bits. Starting difficulty is low so mining is fast for demo purposes

### Block verification

Checks:

1. `prev_hash` matches the current chain tip
2. Block hash meets the difficulty target
3. Merkle root matches the transactions
4. Every transaction has a valid signature
5. Every spend respects its mandate's `max_amount`

If any check fails block gets rejected

### Fork resolution

Longest chain wins. So if a peer sees a longer chain, it requests the full chain, verifies every block, and swaps in the longer one if it's valid
