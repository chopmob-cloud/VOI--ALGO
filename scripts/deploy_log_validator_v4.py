#!/usr/bin/env python3
import os
import base64
from dotenv import load_dotenv, find_dotenv

from algosdk.v2client.algod import AlgodClient
from algosdk import mnemonic, account
from algosdk.transaction import (
    ApplicationCreateTxn,
    StateSchema,
    OnComplete,
    wait_for_confirmation,
)

def need(k: str) -> str:
    v = os.getenv(k)
    if not v or not v.strip():
        raise RuntimeError(f"Missing env key: {k}")
    return v.strip()

def compile_teal(algod: AlgodClient, teal_src: str) -> bytes:
    resp = algod.compile(teal_src)
    # VOI algod returns base64 in resp["result"]
    return base64.b64decode(resp["result"])

def main():
    env_path = find_dotenv(usecwd=True)
    if not env_path:
        raise RuntimeError("❌ .env not found in current directory")
    load_dotenv(env_path, override=True)

    VOI_ALGOD_ADDRESS = need("VOI_ALGOD_ADDRESS")
    VOI_ALGOD_TOKEN = os.getenv("VOI_ALGOD_TOKEN", "")
    CREATOR_MNEMONIC = need("CREATOR_MNEMONIC")

    VOI_NUGGET_ASA_ID = int(need("VOI_NUGGET_ASA_ID"))
    VOI_TREASURY_ADDRESS = need("VOI_TREASURY_ADDRESS")
    VOI_LOG_PREFIX = need("VOI_LOG_PREFIX")  # e.g. NUGGET_V4|

    algod = AlgodClient(VOI_ALGOD_TOKEN, VOI_ALGOD_ADDRESS)

    creator_sk = mnemonic.to_private_key(CREATOR_MNEMONIC)
    creator_addr = account.address_from_private_key(creator_sk)

    # NOTE:
    # - This app validates a 2-txn group:
    #   gtxn[0] = axfer (NUGGET) sender->treasury amount
    #   gtxn[1] = app call with args:
    #     [ "deposit", deposit_id(32), algo_receiver(32 bytes), amount(8 bytes big-endian) ]
    # - Replay protection: box name = deposit_id(32). Must not already exist.
    # - Log bytes:
    #     prefix | deposit_id | algo_receiver | amount(8) | gtxn0_txid(32)
    #
    # TEAL v8, boxes supported.
    APPROVAL_TEAL = f"""#pragma version 8

// scratch[0] = treasury (bytes)
// scratch[1] = asa id (uint64)
// scratch[2] = prefix (bytes)
addr {VOI_TREASURY_ADDRESS}
store 0

int {VOI_NUGGET_ASA_ID}
store 1

byte "{VOI_LOG_PREFIX}"
store 2

// -------- router ----------
txn ApplicationID
int 0
==
bnz on_create

txn OnCompletion
int NoOp
==
bnz on_noop

int 0
return

on_create:
int 1
return

on_noop:
// require 4 args
txn NumAppArgs
int 4
==
assert

// arg0 == "deposit"
txna ApplicationArgs 0
byte "deposit"
==
assert

// deposit_id must be 32 bytes
txna ApplicationArgs 1
len
int 32
==
assert

// receiver must be 32 bytes (Algorand address raw bytes)
txna ApplicationArgs 2
len
int 32
==
assert

// amount must be 8 bytes
txna ApplicationArgs 3
len
int 8
==
assert

// group size 2 and we are index 1
global GroupSize
int 2
==
assert

txn GroupIndex
int 1
==
assert

// gtxn[0] must be axfer
gtxn 0 TypeEnum
int axfer
==
assert

// gtxn[0] xfer_asset == ASA
gtxn 0 XferAsset
load 1
==
assert

// gtxn[0] receiver == treasury
gtxn 0 AssetReceiver
load 0
==
assert

// gtxn[0] amount == btoi(arg3)
gtxn 0 AssetAmount
txna ApplicationArgs 3
btoi
==
assert

// gtxn[0] sender == txn sender
gtxn 0 Sender
txn Sender
==
assert

// replay protection: box(deposit_id) must NOT exist
txna ApplicationArgs 1
box_get
// stack: value, exists
swap
pop            // drop value, keep exists
int 0
==
assert

// box_put(deposit_id, itob(1))
txna ApplicationArgs 1
int 1
itob
box_put

// log: prefix|deposit_id|receiver|amount8|txid32
load 2
txna ApplicationArgs 1
concat
txna ApplicationArgs 2
concat
txna ApplicationArgs 3
concat
gtxn 0 TxID
concat
log

int 1
return
"""

    CLEAR_TEAL = """#pragma version 8
int 1
return
"""

    print("========================================")
    print("🚀 DEPLOYING VOI LOG VALIDATOR V4")
    print("========================================")
    print("Creator :", creator_addr)
    print("Algod   :", VOI_ALGOD_ADDRESS)
    print("Treasury:", VOI_TREASURY_ADDRESS)
    print("ASA     :", VOI_NUGGET_ASA_ID)
    print("Prefix  :", VOI_LOG_PREFIX)
    print("========================================")

    print("📜 Compiling approval TEAL...")
    approval = compile_teal(algod, APPROVAL_TEAL)

    print("📜 Compiling clear TEAL...")
    clear = compile_teal(algod, CLEAR_TEAL)

    sp = algod.suggested_params()
    sp.flat_fee = True
    sp.fee = 2000

    print("📤 Sending create transaction...")
    txn = ApplicationCreateTxn(
        sender=creator_addr,
        sp=sp,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval,
        clear_program=clear,
        global_schema=StateSchema(0, 0),
        local_schema=StateSchema(0, 0),
    )

    txid = algod.send_transaction(txn.sign(creator_sk))
    wait_for_confirmation(algod, txid, 12)

    info = algod.pending_transaction_info(txid)
    app_id = info["application-index"]

    print("========================================")
    print("✅ V4 APP DEPLOYED")
    print("========================================")
    print("VOI_LOG_APP_ID:", app_id)
    print("========================================")

if __name__ == "__main__":
    main()
