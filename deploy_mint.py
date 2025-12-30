#!/usr/bin/env python3
# ============================================================
# Deploy VOI Mint App (v2) — CLAWBACK MODEL (.env ONLY)
# ============================================================

import base64
import os

from dotenv import load_dotenv, find_dotenv
from algosdk.v2client.algod import AlgodClient
from algosdk import mnemonic, account
from algosdk.logic import get_application_address
from algosdk.transaction import (
    ApplicationCreateTxn,
    StateSchema,
    wait_for_confirmation,
)
from pyteal import *

# ============================================================
# FORCE .env LOAD (NO FALLBACKS)
# ============================================================

env_path = find_dotenv(usecwd=True)
if not env_path:
    raise RuntimeError("❌ .env file not found (required)")

load_dotenv(env_path, override=False)

# Required keys (must be non-empty)
REQUIRED_KEYS = [
    "ALGOD_ADDRESS",
    "CREATOR_MNEMONIC",
    "RELAYER_ADDRESS",
    "NUGGET_ASSET_ID",
]

# Keys allowed to be empty but must exist
OPTIONAL_EMPTY_KEYS = [
    "ALGOD_TOKEN",
]

missing = []

for k in REQUIRED_KEYS:
    val = os.getenv(k)
    if val is None or val.strip() == "":
        missing.append(k)

for k in OPTIONAL_EMPTY_KEYS:
    if os.getenv(k) is None:
        missing.append(k)

if missing:
    raise RuntimeError(f"❌ Missing required .env keys: {', '.join(missing)}")

# ============================================================
# LOAD CONFIG (ENV IS SINGLE SOURCE OF TRUTH)
# ============================================================

ALGOD_ADDRESS = os.environ["ALGOD_ADDRESS"]
ALGOD_TOKEN = os.environ.get("ALGOD_TOKEN", "")

CREATOR_MNEMONIC = os.environ["CREATOR_MNEMONIC"]
RELAYER_ADDRESS = os.environ["RELAYER_ADDRESS"]
NUGGET_ASSET_ID = int(os.environ["NUGGET_ASSET_ID"])

LOG_PREFIX = Bytes("NUGGET_MINT_V2|")

# ============================================================
# HELPERS
# ============================================================

def compile_program(algod: AlgodClient, teal_source: str) -> bytes:
    return base64.b64decode(algod.compile(teal_source)["result"])

# ============================================================
# PYTEAL APPROVAL PROGRAM
# ============================================================

def approval_program(relayer_addr: str, asa_id: int):
    creator = Global.creator_address()
    relayer = Addr(relayer_addr)

    # ---------- opt-in (creator only)
    do_optin = Seq(
        Assert(Txn.sender() == creator),
        Assert(Txn.application_args.length() == Int(1)),

        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: Int(asa_id),
            TxnField.asset_receiver: Global.current_application_address(),
            TxnField.asset_amount: Int(0),
        }),
        InnerTxnBuilder.Submit(),
        Approve(),
    )

    # ---------- mint (relayer only)
    deposit_id = Txn.application_args[1]
    amount = Btoi(Txn.application_args[2])

    box = App.box_get(deposit_id)
    mint_source = Txn.accounts[1]
    receiver = Txn.accounts[2]

    do_mint = Seq(
        Assert(Txn.sender() == relayer),
        Assert(Txn.application_args.length() == Int(3)),
        Assert(Len(deposit_id) == Int(32)),
        Assert(amount > Int(0)),
        Assert(Txn.accounts.length() >= Int(3)),

        # replay protection
        box,
        Assert(Not(box.hasValue())),
        App.box_put(deposit_id, Bytes("1")),

        # clawback transfer
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: Int(asa_id),
            TxnField.asset_sender: mint_source,
            TxnField.asset_receiver: receiver,
            TxnField.asset_amount: amount,
        }),
        InnerTxnBuilder.Submit(),

        Log(Concat(LOG_PREFIX, deposit_id, Itob(amount), receiver)),
        Approve(),
    )

    return Cond(
        [Txn.application_id() == Int(0), Approve()],
        [Txn.application_args.length() == Int(1),
            Cond(
                [Txn.application_args[0] == Bytes("optin"), do_optin],
                [Int(1), Reject()],
            )
        ],
        [Txn.application_args[0] == Bytes("mint"), do_mint],
        [Int(1), Reject()],
    )

def clear_program():
    return Approve()

# ============================================================
# MAIN
# ============================================================

def main():
    algod = AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

    creator_sk = mnemonic.to_private_key(CREATOR_MNEMONIC)
    creator_addr = account.address_from_private_key(creator_sk)

    approval_teal = compileTeal(
        approval_program(RELAYER_ADDRESS, NUGGET_ASSET_ID),
        Mode.Application,
        version=8,
    )
    clear_teal = compileTeal(clear_program(), Mode.Application, version=8)

    approval_bin = compile_program(algod, approval_teal)
    clear_bin = compile_program(algod, clear_teal)

    sp = algod.suggested_params()
    sp.flat_fee = True
    sp.fee = 4000

    txn = ApplicationCreateTxn(
        sender=creator_addr,
        sp=sp,
        on_complete=0,  # NoOp
        approval_program=approval_bin,
        clear_program=clear_bin,
        global_schema=StateSchema(0, 0),
        local_schema=StateSchema(0, 0),
        foreign_assets=[NUGGET_ASSET_ID],
    )

    txid = algod.send_transaction(txn.sign(creator_sk))
    print("📤 Create tx:", txid)

    confirmed = wait_for_confirmation(algod, txid, 8)
    app_id = confirmed["application-index"]
    app_addr = get_application_address(app_id)

    print("========================================")
    print("✅ VOI Mint App DEPLOYED")
    print("App ID      :", app_id)
    print("App Address :", app_addr)
    print("Relayer     :", RELAYER_ADDRESS)
    print("ASA         :", NUGGET_ASSET_ID)
    print("========================================")
    print("NEXT (CRITICAL):")
    print("1) Set ASA clawback = app address")
    print("2) Call app with arg: optin (creator)")
    print("3) Start relayer")
    print("========================================")

if __name__ == "__main__":
    main()
