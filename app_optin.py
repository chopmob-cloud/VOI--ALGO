#!/usr/bin/env python3
# ============================================================
# Call "optin" on VOI Mint App (.env ONLY)
# ============================================================

import os
from dotenv import load_dotenv, find_dotenv

from algosdk.v2client.algod import AlgodClient
from algosdk import mnemonic, account
from algosdk.transaction import (
    ApplicationNoOpTxn,
    wait_for_confirmation,
)

# ============================================================
# FORCE .env LOAD
# ============================================================

env_path = find_dotenv(usecwd=True)
if not env_path:
    raise RuntimeError("❌ .env file not found")

load_dotenv(env_path, override=True)

REQUIRED_KEYS = [
    "ALGOD_ADDRESS",
    "CREATOR_MNEMONIC",
    "MINT_APP_ID",
    "NUGGET_ASSET_ID",
]

OPTIONAL_EMPTY_KEYS = ["ALGOD_TOKEN"]

missing = []

for k in REQUIRED_KEYS:
    if not os.getenv(k) or os.getenv(k).strip() == "":
        missing.append(k)

for k in OPTIONAL_EMPTY_KEYS:
    if os.getenv(k) is None:
        missing.append(k)

if missing:
    raise RuntimeError(f"❌ Missing .env keys: {', '.join(missing)}")

# ============================================================
# LOAD CONFIG
# ============================================================

ALGOD_ADDRESS = os.environ["ALGOD_ADDRESS"]
ALGOD_TOKEN = os.environ.get("ALGOD_TOKEN", "")

CREATOR_MNEMONIC = os.environ["CREATOR_MNEMONIC"]
MINT_APP_ID = int(os.environ["MINT_APP_ID"])
NUGGET_ASSET_ID = int(os.environ["NUGGET_ASSET_ID"])

# ============================================================
# MAIN
# ============================================================

def main():
    algod = AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

    creator_sk = mnemonic.to_private_key(CREATOR_MNEMONIC)
    creator_addr = account.address_from_private_key(creator_sk)

    print("========================================")
    print("📥 CALLING MINT APP OPT-IN")
    print("App ID :", MINT_APP_ID)
    print("ASA    :", NUGGET_ASSET_ID)
    print("Caller :", creator_addr)
    print("========================================")

    sp = algod.suggested_params()
    sp.flat_fee = True
    sp.fee = 2000  # covers inner opt-in txn

    txn = ApplicationNoOpTxn(
        sender=creator_addr,
        sp=sp,
        index=MINT_APP_ID,
        app_args=[b"optin"],
        foreign_assets=[NUGGET_ASSET_ID],
    )

    txid = algod.send_transaction(txn.sign(creator_sk))
    print("📤 TxID:", txid)

    wait_for_confirmation(algod, txid, 8)

    print("========================================")
    print("✅ MINT APP OPT-IN COMPLETE")
    print("App ID opted into ASA")
    print("========================================")


if __name__ == "__main__":
    main()
