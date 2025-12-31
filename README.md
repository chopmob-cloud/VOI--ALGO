# VOI--ALGO
VOI to Algorand Mainnet Bridge

Needs finishing and tweaks need to follow, should be done by end of the first week in Jan 2026

This will change as V1 was burn, log, release- which worked

I changed it to capture, log, release - which is having issues!!!

So ill keep this updated.

VOI USER
  |
  | 1) Atomic group
  |    - AppCall("bridge_deposit", ...)
  |    - ASA transfer → escrow
  v
ESCROW APP
  |
  | 2) Emits LOG (validated on-chain)
  v
RELAYER (off-chain)
  |
  | 3) Sees log, verifies nonce
  | 4) Calls withdraw() as admin
  v
ALGO USER RECEIVES ASA

