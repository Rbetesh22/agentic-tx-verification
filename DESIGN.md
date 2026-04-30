**Allowance**

Toy blockchain where AI agents can spend money on behalf of owners, but only up to limits the owners approve. Every approved action gets written to a shared chain so peers can verify later what was allowed and what actually happened.

We talked through a few other blockchain ideas at first like voting, medical records, and supply-chain transfer, but this one seemed the most straightforward to implement while still showing authorization, validation, and tamper resistance.

**P2P Network**

1 tracker + 4 peers. All peers run the same blockchain code and all keep their own local copy of the chain.

For the demo, peers can act as owners, agents, or merchants depending on which commands are run.

**Tracker**

Tracker only does peer discovery. It is not involved in mining or transaction validation.

New peer sends JOIN with its address and public key. Tracker stores it and broadcasts updated peer list.
Peers send HEARTBEAT every 5 seconds. If tracker misses 3 in a row, that peer is removed.
Peer can also send LEAVE before shutting down.
Messages between peers

After joining, peers communicate directly over TCP using JSON messages.

TX - broadcast a new transaction
BLOCK - broadcast a mined block
CHAIN_REQUEST - request full blockchain
CHAIN_RESPONSE - send full blockchain back

If a new peer joins late, it requests the current chain from another peer and validates it before syncing.

**Blockchain**
Block
index
prev_hash
merkle_root
timestamp
nonce
transactions

Block hash is SHA-256 of the fields above.

**Transactions**

Two transaction types.

Mandate - owner gives an agent permission to spend up to some amount:
{ type: "mandate", owner_pubkey, agent_pubkey, max_amount, signature }

Spend - agent attempts payment to merchant:
{ type: "spend", agent_pubkey, merchant_pubkey, amount, signature }

Every transaction is signed using ECDSA.

**Merkle tree structure**

Inside each block, transactions are not just stored as a plain list. Each transaction is first hashed individually with SHA-256 to create the leaf nodes of a Merkle tree.

Then hashes are combined in pairs and hashed again:

H12 = SHA256(H1 || H2)

This repeats upward until one final hash remains. That final top hash is the merkle_root stored in the block header.

_Reason for doing this:_

if even one transaction changes, the root changes
peers can quickly verify block transaction integrity by recomputing the root
it gives us one fixed summary hash representing the whole transaction set

So when a peer receives a block, it recomputes the Merkle tree from the included transactions and checks that the final root matches the merkle_root field inside the block.

**Privacy / signatures**

Each peer stores public keys of known peers and uses them to verify signatures before accepting transactions.

We may also hash certain payload fields before writing them to chain, mainly to show that data can be validated without exposing everything directly.

**Mining**

Peers collect valid pending transactions and try to mine a block using proof-of-work.

Mining means finding a nonce such that the block hash has at least N leading zero bits. Difficulty will stay low so blocks can be mined quickly during demo.

**Block verification**

When a peer receives a block, it checks:

prev_hash points to current tip
block hash satisfies difficulty
recomputed Merkle root matches merkle_root
all signatures are valid
each spend transaction stays within previously approved mandate

If any of these fail, block is rejected.

**Fork resolution**

Sometimes two peers may mine around the same time.

If that happens, peers temporarily keep whichever block they saw first. If one branch becomes longer, peers request that longer chain, validate all of it, and switch.

**Demo plan**

Each peer runs a CLI.

mandate <agent> <max> - owner creates spending authorization
spend <merchant> <amount> - agent attempts purchase
chain - print current blockchain
peers - print connected peers

**tentative flow:**

owner authorizes agent for some max amount

agent submits spend requests

peers validate whether spend is legal

accepted transactions get mined into blocks

Tamper-resistance tests

Overspend - agent tries to spend more than mandate allows. Transaction gets rejected.

Bad signature - fake or modified transaction fails signature verification.

Edited history - if peer manually changes old block data, Merkle root and block hashes no longer line up, so chain is rejected by others.

Fork - two miners produce blocks close together, then network resolves once one side becomes longer.

**Extra Credit**

Dynamic difficulty adjustment every 5 blocks

Optional hashing of sensitive payload fields
