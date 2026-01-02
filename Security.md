# Security Model

## Trust Assumptions
- VOI validator enforces asset + treasury correctness
- Relayer verifies logs and group semantics
- Algorand escrow enforces nonce monotonicity

## Threats Mitigated
- Replay attacks
- Asset spoofing
- Receiver forgery
- Relayer race conditions
- Indexer inconsistency

## Non-Goals
- Fully trustless bridging
- Light client verification
