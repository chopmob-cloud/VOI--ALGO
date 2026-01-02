#!/usr/bin/env python3
import os
import sys
import time
import base64
import hashlib
from dotenv import load_dotenv, find_dotenv

from algosdk.v2client.algod import AlgodClient
from algosdk import mnemonic, account, encoding
from algosdk.transaction import (
    AssetTransferTxn,
    ApplicationNoOpTxn,
    calculate_group_id,
    wait_for_confirmation,
)

# ============================================================
# Helpers
# ============================================================

def need(key: str) -> str:
    v = os.getenv(key)
    if v is None or str(v).strip() == "":
        raise RuntimeError(f"Missing env var: {key}")
    return str(v).strip()

def opt(key: str, default: str = "") -> str:
    v = os.getenv(key)
    if v is None:
        return default
    return str(v).strip()

def u64_to_8bytes(n: int) -> bytes:
    if n < 0 or n >= 2**64:
        raise ValueError("amount out of uint64 range")
    return int(n).to_bytes(8, "big")

def make_deposit_id(tag: str) -> bytes:
    """
    Must be EXACTLY 32 bytes for V4 TEAL: len(arg1) == 32
    We'll do sha256(tag|time_ns|pid) => 32 bytes.
    """
    seed = f"{tag}|{time.time_ns()}|{os.getpid()}".encode("utf-8")
    return hashlib.sha256(seed).digest()  # 32 bytes

def get_asa_balance(algod: AlgodClient, addr: str, asa_id: int) -> int:
    acct = algod.account_info(addr)
    for a in acct.get("assets", []):
        if int(a.get("asset-id", -1)) == asa_id:
            return int(a.get("amount", 0))
    return 0

# ============================================================
# Main
# ============================================================

def main():
    # Load .env from current folder (Windows friendly)
    env_path = find_dotenv(usecwd=True)
    if env_path:
        load_dotenv(env_path, override=True)
    else:
        # allow running without dotenv if env vars are already set
        pass

    VOI_ALGOD_ADDRESS = need("VOI_ALGOD_ADDRESS")
    VOI_ALGOD_TOKEN = opt("VOI_ALGOD_TOKEN", "")
    VOI_TREASURY_ADDRESS = need("VOI_TREASURY_ADDRESS")

    VOI_NUGGET_ASA_ID = int(need("VOI_NUGGET_ASA_ID"))
    VOI_LOG_APP_ID = int(need("VOI_LOG_APP_ID"))
    VOI_LOG_PREFIX = need("VOI_LOG_PREFIX")  # informational here

    # Sender mnemonic (you asked for this naming)
    VOI_SENDER_MNEMONIC = need("VOI_SENDER_MNEMONIC")

    algod = AlgodClient(VOI_ALGOD_TOKEN, VOI_ALGOD_ADDRESS)

    sender_sk = mnemonic.to_private_key(VOI_SENDER_MNEMONIC)          # bytes
    sender_addr = account.address_from_private_key(sender_sk)         # 58-char address

    print("============================================================")
    print("🧪 VOI DEPOSIT + V4 LOG VALIDATOR TEST")
    print("============================================================")
    print("Sender (VOI) :", sender_addr)
    print("Treasury     :", VOI_TREASURY_ADDRESS)
    print("ASA ID       :", VOI_NUGGET_ASA_ID)
    print("Log App ID   :", VOI_LOG_APP_ID)
    print("Prefix       :", VOI_LOG_PREFIX)
    print("Algod        :", VOI_ALGOD_ADDRESS)
    if env_path:
        print("Env          :", env_path)
    print("============================================================")

    # Inputs (optional CLI)
    if len(sys.argv) >= 2:
        receiver_addr = sys.argv[1].strip()
    else:
        receiver_addr = input("Receiver (Algorand address): ").strip()

    if len(sys.argv) >= 3:
        amount_int = int(sys.argv[2])
    else:
        amount_int = int(input("Amount (integer): ").strip())

    if len(sys.argv) >= 4:
        tag = sys.argv[3].strip()
    else:
        tag = input("Deposit tag (unique string): ").strip()

    # Validate receiver address and convert to 32 raw bytes (TEAL requires len == 32)
    try:
        receiver_pk = encoding.decode_address(receiver_addr)  # bytes length 32
    except Exception as e:
        raise RuntimeError(f"Receiver address invalid: {e}")

    # Validate sender ASA balance
    bal = get_asa_balance(algod, sender_addr, VOI_NUGGET_ASA_ID)
    print(f"✅ Sender ASA balance: {bal}")
    if bal < amount_int:
        raise RuntimeError(f"Insufficient ASA balance: have {bal}, need {amount_int}")

    # Build deposit_id (32 bytes)
    deposit_id = make_deposit_id(tag)
    print("\nDEBUG:")
    print(" deposit_id len :", len(deposit_id))
    print(" deposit_id hex :", deposit_id.hex())

    # V4 TEAL expects 8 bytes amount
    amount_8 = u64_to_8bytes(amount_int)

    # Suggested params
    sp = algod.suggested_params()

    # TXN 0: ASA transfer sender -> treasury
    # Must be gtxn[0] and must match ASA + amount + receiver in TEAL :contentReference[oaicite:3]{index=3}
    sp0 = sp
    sp0.flat_fee = True
    sp0.fee = 1000

    axfer = AssetTransferTxn(
        sender=sender_addr,
        sp=sp0,
        receiver=VOI_TREASURY_ADDRESS,
        amt=amount_int,
        index=VOI_NUGGET_ASA_ID,
    )

    # TXN 1: app call with args:
    # ["deposit", deposit_id(32), receiver_pk(32), amount8(8)]
    # Must include box reference for deposit_id because TEAL does box_get/box_put using arg1 :contentReference[oaicite:4]{index=4}
    sp1 = algod.suggested_params()
    sp1.flat_fee = True
    # Give extra headroom for box ops; adjust if needed
    sp1.fee = 4000

    app_args = [
        b"deposit",
        deposit_id,
        receiver_pk,
        amount_8,
    ]

    app_call = ApplicationNoOpTxn(
        sender=sender_addr,
        sp=sp1,
        index=VOI_LOG_APP_ID,
        app_args=app_args,
        # IMPORTANT: box reference.
        # (0, name) => current app’s box with name=deposit_id
        boxes=[(0, deposit_id)],
    )

    # Group them: [axfer, app_call] (TEAL asserts GroupIndex==1 for app call) :contentReference[oaicite:5]{index=5}
    gid = calculate_group_id([axfer, app_call])
    axfer.group = gid
    app_call.group = gid

    signed0 = axfer.sign(sender_sk)
    signed1 = app_call.sign(sender_sk)

    try:
        txid = algod.send_transactions([signed0, signed1])
        print(f"\n📤 Sent group tx: {txid}")
        wait_for_confirmation(algod, txid, 12)
        print("✅ Confirmed")
        print("\n✅ Deposit emitted. Check relayer logs.")
        print("Deposit ID (base64):", base64.b64encode(deposit_id).decode())
    except Exception as e:
        print("\n❌ Transaction failed:")
        print(str(e))
        raise

if __name__ == "__main__":
    main()
