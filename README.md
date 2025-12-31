# VOI--ALGO
VOI to Algorand Mainnet Bridge

Needs finishing and tweaks need to follow, should be done by end of the first week in Jan 2026

This is the new design - its coming - scripts currently are now outdated.

```mermaid
flowchart TD
    U["USER (VOI)"]
    VEA["VOI ESCROW APP"]
    R["RELAYER (server)"]
    AEA["ALGORAND ESCROW APP"]
    AU["Algorand User"]

    U -->|1 ASA transfer + AppCall| VEA
    VEA -->|2 Emits structured log| R
    R -->|3 Reads VOI log| R
    R -->|4 Escrow withdraw| AEA
    AEA -->|5 Sends ASA| AU
```




