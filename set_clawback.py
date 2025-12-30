#!/usr/bin/env python3
# ============================================================
# Set ASA Clawback → Mint App (ENV ONLY, MANAGER-SIGNED)
# ============================================================

import os
from dotenv import load_dotenv, find_dotenv

from algosdk.v2client.algod import AlgodClient
from algosdk import mnemonic, account
from algosdk.logic import get_application_address
from algosdk.transaction import AssetConfigTxn, wait_for_confirmation

# ============================================================
# FORCE .env LOAD
# ============================================================

env_path = find_dotenv(usecwd=True)
if not env_path:
    raise RuntimeError("❌ .env file not found")

load_dotenv(env_path, override=True)

REQUIRED_KEYS = [
    "ALGOD_ADDRESS",
    "ASA_MANAGER_MNEMONIC",
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
# LOAD CONFIG (ENV IS TRUTH)
# ============================================================

ALGOD_ADDRESS = os.environ["ALGOD_ADDRESS"]
ALGOD_TOKEN = os.environ.get("ALGOD_TOKEN", "")

ASA_MANAGER_MNEMONIC = os.environ["ASA_MANAGER_MNEMONIC"]
MINT_APP_ID = int(os.environ["MINT_APP_ID"])
NUGGET_ASSET_ID = int(os.environ["NUGGET_ASSET_ID"])

# ============================================================
# MAIN
# ============================================================

def main():
    algod = AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

    # 🔑 ASA MANAGER KEY (ONLY VALID SIGNER)
    manager_sk = mnemonic.to_private_key(ASA_MANAGER_MNEMONIC)
    manager_addr = account.address_from_private_key(manager_sk)

    # 🔍 Verify on-chain manager
    asset = algod.asset_info(NUGGET_ASSET_ID)
    onchain_manager = asset["params"].get("manager")

    if onchain_manager != manager_addr:
        raise RuntimeError(
            "❌ ASA manager mismatch\n"
            f"On-chain manager : {onchain_manager}\n"
            f".env manager     : {manager_addr}"
        )

    mint_app_addr = get_application_address(MINT_APP_ID)

    print("========================================")
    print("🔧 SETTING ASA CLAWBACK")
    print("ASA ID        :", NUGGET_ASSET_ID)
    print("Manager       :", manager_addr)
    print("Mint App ID   :", MINT_APP_ID)
    print("Clawback Addr :", mint_app_addr)
    print("========================================")

    sp = algod.suggested_params()
    sp.flat_fee = True
    sp.fee = 1000

    txn = AssetConfigTxn(
        sender=manager_addr,
        sp=sp,
        index=NUGGET_ASSET_ID,
        clawback=mint_app_addr,
        manager=manager_addr,  # unchanged
        strict_empty_address_check=False,
    )

    # ✅ SIGN WITH MANAGER KEY
    txid = algod.send_transaction(txn.sign(manager_sk))
    print("📤 TxID:", txid)

    wait_for_confirmation(algod, txid, 8)

    print("========================================")
    print("✅ CLAWBACK SET SUCCESSFULLY")
    print("Clawback →", mint_app_addr)
    print("========================================")

if __name__ == "__main__":
    main()
