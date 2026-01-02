# VOI Log Validator (V4)

This application validates deposits and emits deterministic logs
consumed by the relayer.

## Template Parameters
- TREASURY_ADDR (32-byte pubkey)
- ASA_ID
- LOG_PREFIX

## Log Format
LOG_PREFIX | deposit_id | receiver | amount | axfer_txid
