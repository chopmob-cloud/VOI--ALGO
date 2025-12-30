#!/usr/bin/env python3
# ============================================================
# Opt-in RELAYER account to VOI Nugget ASA
# ENV ONLY • PORTABLE • SAFE TO RE-RUN
# ============================================================

import os
from dotenv import load_dotenv, find_dotenv

from algosdk.v2client.algod import AlgodClient
from algosdk import mnemonic, account
from algosdk.transaction import AssetTransferTxn, wait_for_confirmation

# ============================================================
# FORCE .env LOAD (CURRENT WORKING DIRECTORY)
# ============================================================

env_path = find_dotenv(usecwd=True)
if not env_path:
    raise RuntimeError("❌ .env file not found in current directory")

load_dotenv(env_path, override=True)

# ============================================================
# ENV VALIDATION
# ============================================================

REQUIRED_KEYS = [
    "VOI_ALGOD_ADDRESS",
    "RELAYER_MNEMONIC",
    "VOI_NUGGET_ASA_ID",
]

OPTIONAL_KEYS_MAY_BE_EMPTY = [
    "VOI_ALGOD_TOKEN",
]

missing = [k for k in REQUIRED_KEYS if not os.getenv(k) or os.getenv(k).strip() == ""]
if missing:
    raise RuntimeError(f"❌ Missing required .env keys: {', '.join(missing)}")

for k in OPTIONAL_KEYS_MAY_BE_EMPTY:
    if os.getenv(k) is None:
        raise RuntimeError(f"❌ Optional key must exist (may be empty): {k}")

# ============================================================
# LOAD CONFIG
# ============================================================

VOI_ALGOD_ADDRESS = os.environ["VOI_ALGOD_ADDRESS"]
VOI_ALGOD_TOKEN = os.environ.get("VOI_ALGOD_TOKEN", "")

RELAYER_MNEMONIC = os.environ["RELAYER_MNEMONIC"]
VOI_NUGGET_ASA_ID = int(os.environ["VOI_NUGGET_ASA_ID"])

# ============================================================
# MAIN
# ============================================================

def main():
    algod = AlgodClient(VOI_ALGOD_TOKEN, VOI_ALGOD_ADDRESS)

    relayer_sk = mnemonic.to_private_key(RELAYER_MNEMONIC)
    relayer_addr = account.address_from_private_key(relayer_sk)

    acct = algod.account_info(relayer_addr)

    print("========================================")
    print("🔧 RELAYER ASA OPT-IN")
    print("Relayer address :", relayer_addr)
    print("ASA ID          :", VOI_NUGGET_ASA_ID)
    print("Balance (µVOI)  :", acct.get("amount", 0))
    print("========================================")

    # Check if already opted in
    for a in acct.get("assets", []):
        if a.get("asset-id") == VOI_NUGGET_ASA_ID:
            print("✅ Already opted into ASA", VOI_NUGGET_ASA_ID)
            return

    # Suggested params
    sp = algod.suggested_params()
    sp.flat_fee = True
    sp.fee = 1000

    txn = AssetTransferTxn(
        sender=relayer_addr,
        sp=sp,
        receiver=relayer_addr,
        amt=0,
        index=VOI_NUGGET_ASA_ID,
    )

    txid = algod.send_transaction(txn.sign(relayer_sk))
    print("📤 Opt-in tx sent:", txid)

    wait_for_confirmation(algod, txid, 8)

    # Verify
    acct2 = algod.account_info(relayer_addr)
    ok = any(a.get("asset-id") == VOI_NUGGET_ASA_ID for a in acct2.get("assets", []))

    print("----------------------------------------")
    print("Opt-in present:", ok)

    if not ok:
        raise RuntimeError(
            "❌ Opt-in failed. Ensure relayer has sufficient VOI for minimum balance."
        )

    print("========================================")
    print("🎉 RELAYER OPT-IN SUCCESSFUL")
    print("========================================")

if __name__ == "__main__":
    main()
