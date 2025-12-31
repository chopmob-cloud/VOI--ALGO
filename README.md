# VOI--ALGO
VOI to Algorand Mainnet Bridge

Needs finishing and tweaks need to follow, should be done by end of the first week in Jan 2026

This will change as V1 was burn, log, release- which worked

I changed it to capture, log, release - which is having issues!!!

So ill keep this updated.

```mermaid
flowchart TD
    U[USER (VOI)]
    VEA[VOI ESCROW APP]
    R[RELAYER (server)]
    AEA[ALGORAND ESCROW APP]
    AU[Algorand User]

    U -->|1) ASA transfer + AppCall<br/>(bridge_deposit)| VEA
    VEA -->|2) Emits structured log| R
    R -->|3) Reads VOI log| R
    R -->|4) Calls Algorand escrow withdraw| AEA
    AEA -->|5) Sends ASA| AU
```


