#!/usr/bin/env python3
import os
from dotenv import load_dotenv
from algosdk.v2client.algod import AlgodClient
from algosdk import mnemonic, account
from algosdk.transaction import ApplicationCreateTxn, wait_for_confirmation
from pyteal import *

# --------------------------------------------------
# Load env
# --------------------------------------------------
load_dotenv()

ALGOD_ADDR = os.getenv("VOI_ALGOD_ADDRESS")
ALGOD_TOKEN = os.getenv("VOI_ALGOD_TOKEN", "")
ASA_ID = int(os.getenv("VOI_NUGGET_ASA_ID"))
CREATOR_MNEMONIC = os.getenv("CREATOR_MNEMONIC")

if not all([ALGOD_ADDR, ASA_ID, CREATOR_MNEMONIC]):
    raise RuntimeError("❌ Missing env vars")

# --------------------------------------------------
# PyTeal (UNCHANGED LOGIC)
# --------------------------------------------------
def approval():
    ADMIN = Bytes("admin")
    ASAID = Bytes("asa_id")
    NONCE = Bytes("nonce")

    on_create = Seq(
        Assert(Txn.application_args.length() == Int(1)),
        App.globalPut(ADMIN, Txn.sender()),
        App.globalPut(ASAID, Btoi(Txn.application_args[0])),
        App.globalPut(NONCE, Int(0)),
        Approve(),
    )

    is_admin = Txn.sender() == App.globalGet(ADMIN)

    optin = Seq(
        Assert(is_admin),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: App.globalGet(ASAID),
            TxnField.asset_receiver: Global.current_application_address(),
            TxnField.asset_amount: Int(0),
            TxnField.fee: Int(0),
        }),
        InnerTxnBuilder.Submit(),
        Approve(),
    )

    withdraw = Seq(
        Assert(is_admin),
        Assert(Txn.application_args.length() == Int(4)),
        Assert(Btoi(Txn.application_args[3]) == App.globalGet(NONCE) + Int(1)),
        App.globalPut(NONCE, Btoi(Txn.application_args[3])),

        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields({
            TxnField.type_enum: TxnType.AssetTransfer,
            TxnField.xfer_asset: App.globalGet(ASAID),
            TxnField.asset_receiver: Txn.application_args[1],
            TxnField.asset_amount: Btoi(Txn.application_args[2]),
            TxnField.fee: Int(0),
        }),
        InnerTxnBuilder.Submit(),
        Approve(),
    )

    bridge_deposit = Seq(
        Assert(Txn.application_args.length() == Int(4)),
        Assert(Global.group_size() == Int(2)),
        Assert(Txn.group_index() == Int(0)),
        Assert(Len(Txn.application_args[1]) == Int(32)),

        Assert(Gtxn[1].type_enum() == TxnType.AssetTransfer),
        Assert(Gtxn[1].xfer_asset() == App.globalGet(ASAID)),
        Assert(Gtxn[1].asset_receiver() == Global.current_application_address()),
        Assert(Gtxn[1].sender() == Txn.sender()),
        Assert(Gtxn[1].asset_amount() == Btoi(Txn.application_args[2])),

        Log(Concat(
            Bytes("WNUGGET_DEP_V1|"),
            Txn.sender(),
            Txn.application_args[1],
            Itob(Btoi(Txn.application_args[2])),
            Txn.application_args[3],
            Txn.tx_id(),
        )),
        Approve(),
    )

    handle = Cond(
        [Txn.application_args[0] == Bytes("optin"), optin],
        [Txn.application_args[0] == Bytes("withdraw"), withdraw],
        [Txn.application_args[0] == Bytes("bridge_deposit"), bridge_deposit],
    )

    return Cond(
        [Txn.application_id() == Int(0), on_create],
        [Txn.on_completion() == OnComplete.NoOp, handle],
        [Txn.on_completion() == OnComplete.UpdateApplication, Return(is_admin)],
        [Txn.on_completion() == OnComplete.DeleteApplication, Return(is_admin)],
        [Int(1), Reject()],
    )

def clear():
    return Approve()

# --------------------------------------------------
# Deploy
# --------------------------------------------------
def main():
    algod = AlgodClient(ALGOD_TOKEN, ALGOD_ADDR)
    sk = mnemonic.to_private_key(CREATOR_MNEMONIC)
    sender = account.address_from_private_key(sk)

    approval_teal = compileTeal(approval(), Mode.Application, version=8)
    clear_teal = compileTeal(clear(), Mode.Application, version=8)

    approval_bin = bytes.fromhex(algod.compile(approval_teal)["result"])
    clear_bin = bytes.fromhex(algod.compile(clear_teal)["result"])

    sp = algod.suggested_params()
    sp.flat_fee = True
    sp.fee = 2000

    txn = ApplicationCreateTxn(
        sender=sender,
        sp=sp,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval_bin,
        clear_program=clear_bin,
        global_schema=StateSchema(3, 0),
        local_schema=StateSchema(0, 0),
        app_args=[ASA_ID.to_bytes(8, "big")],
    )

    txid = algod.send_transaction(txn.sign(sk))
    result = wait_for_confirmation(algod, txid, 12)

    print("========================================")
    print("✅ VOI ESCROW DEPLOYED")
    print("APP ID:", result["application-index"])
    print("========================================")

if __name__ == "__main__":
    main()
