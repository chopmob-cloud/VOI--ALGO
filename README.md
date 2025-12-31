# VOI--ALGO
VOI to Algorand Mainnet Bridge

Needs finishing and tweaks need to follow, should be done by end of the first week in Jan 2026

This is the new design - its coming - scripts currently are now outdated.

```mermaid
flowchart TD
    %% =========================
    %% USER SIDE
    %% =========================
    U["User Wallet<br/>VOI Network"]

    %% =========================
    %% VOI CHAIN
    %% =========================
    subgraph VOI["VOI Network"]
        T["Treasury Wallet<br/>(Holds NUGGET ASA)"]
        A["V4 Log Validator App<br/>(No Custody)"]
        I["VOI Indexer"]
    end

    %% =========================
    %% RELAYER
    %% =========================
    subgraph RELAYER["Relayer (Off-chain)"]
        L["Log Listener"]
        D["Deduplication & Validation"]
        X["Payout Executor"]
    end

    %% =========================
    %% ALGORAND
    %% =========================
    subgraph ALGO["Algorand Network"]
        P["Algorand Treasury / Escrow"]
        RCV["User Algorand Address"]
    end

    %% =========================
    %% FLOWS
    %% =========================
    U -->|ASA Transfer| T
    U -->|App Call Deposit Metadata| A

    A -->|Emit Log| I

    I -->|Indexed Logs| L
    L --> D
    D -->|Valid Deposit| X

    X -->|Submit Tx| P
    P -->|Funds Released| RCV
```





