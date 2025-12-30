#!/usr/bin/env python3
# ============================================================
# Test Emit Mint — NUGGET_MINT_V2 (SERVER / VOI)
# ============================================================

import os
import hashlib
from dotenv import load_dotenv

from algosdk.v2client.algod import AlgodClient
from algosdk import mnemonic, account
from algosdk.transaction import ApplicationNoOpTxn, wait_for_confirmation

# ============================================================
# HARD SERVER ENV PATH (NO FALLBACKS)
# ============================================================

ENV_FILE = "/opt/relayers/voi_to_algo/env/voi.env"

if not os.path.exists(ENV_FILE):
    raise RuntimeError(f"❌ Missing env file: {ENV_FILE}")

load_dotenv(ENV_FILE, override=True)

def need(k: str) -> str:
    v = os.getenv(k)
    if v is None or v.strip() == "":
        raise RuntimeError(f"❌ Missing env key: {k}")
    return v

# ============================================================
# ENV VALUES
# ============================================================

VOI_ALGOD_ADDRESS = need("VOI_ALGOD_ADDRESS")
VOI_ALGOD_TOKEN   = os.getenv("VOI_ALGOD_TOKEN", "")

RELAYER_MNEMONIC  = need("RELAYER_MNEMONIC")
VOI_MINT_APP_ID   = int(need("VOI_MINT_APP_ID"))
VOI_NUGGET_ASA_ID = int(need("VOI_NUGGET_ASA_ID"))

# ============================================================
# MAIN
# ============================================================

def main():
    algod = AlgodClient(VOI_ALGOD_TOKEN, VOI_ALGOD_ADDRESS)

    relayer_sk = mnemonic.to_private_key(RELAYER_MNEMONIC)
    relayer_addr = account.address_from_private_key(relayer_sk)

    print("=" * 44)
    print("🧪 VOI → ALGO RELAYER TEST (NUGGET_MINT_V2)")
    print("Mint App :", VOI_MINT_APP_ID)
    print("Relayer  :", relayer_addr)
    print("=" * 44)

    mint_source_addr = input("Mint source (VOI address holding ASA): ").strip()
    receiver_addr    = input("Receiver (VOI escrow / relayer address): ").strip()
    amount           = int(input("Amount (integer): ").strip())
    tag              = input("Deposit tag (unique string): ").strip()

    if amount <= 0:
        raise RuntimeError("Amount must be > 0")

    # 32-byte deposit ID (box key)
    deposit_id = hashlib.sha256(tag.encode()).digest()

    sp = algod.suggested_params()
    sp.flat_fee = True
    sp.fee = 4000

    # ========================================================
    # DEPLOYED APP REQUIREMENTS (ALL SATISFIED HERE):
    # - Txn.accounts.length() >= 3
    # - accounts[0] = mint source (ASA holder)
    # - accounts[1] = receiver
    # - boxes must declare deposit_id
    # ========================================================

    txn = ApplicationNoOpTxn(
        sender=relayer_addr,
        sp=sp,
        index=VOI_MINT_APP_ID,
        app_args=[
            b"mint",
            deposit_id,
            amount.to_bytes(8, "big"),
        ],
        accounts=[
            mint_source_addr,  # Txn.accounts[0] → clawback source
            receiver_addr,     # Txn.accounts[1] → receiver
            relayer_addr,      # Txn.accounts[2] → placeholder
        ],
        foreign_assets=[VOI_NUGGET_ASA_ID],
        boxes=[(VOI_MINT_APP_ID, deposit_id)],  # ✅ REQUIRED
    )

    txid = algod.send_transaction(txn.sign(relayer_sk))
    print("📤 Sent mint tx:", txid)

    wait_for_confirmation(algod, txid, 8)
    print("✅ Mint executed successfully")
    print("Deposit ID:", deposit_id.hex())

# ============================================================

if __name__ == "__main__":
    main()