#!/usr/bin/env python3
# ============================================================
# VOI → Algorand Relayer — SERVER MODE
# ============================================================

import base64
import json
import os
import sys
import time
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from algosdk.v2client import algod, indexer
from algosdk import mnemonic, account, encoding
from algosdk.transaction import ApplicationNoOpTxn, wait_for_confirmation

# ============================================================
# PATHS (FIXED)
# ============================================================

BASE_DIR = "/opt/relayers/voi_to_algo"
ENV_FILE = f"{BASE_DIR}/env/voi.env"
LOG_OUT = f"{BASE_DIR}/logs/out.log"
LOG_ERR = f"{BASE_DIR}/logs/err.log"

# ============================================================
# LOGGING (stdout / stderr → files)
# ============================================================

os.makedirs(f"{BASE_DIR}/logs", exist_ok=True)

sys.stdout = open(LOG_OUT, "a", buffering=1)
sys.stderr = open(LOG_ERR, "a", buffering=1)

print("🔁 Relayer starting…")

# ============================================================
# LOAD ENV (ONLY FROM voi.env)
# ============================================================

if not os.path.exists(ENV_FILE):
    raise RuntimeError(f"❌ Missing env file: {ENV_FILE}")

load_dotenv(ENV_FILE, override=True)

def require(key: str, allow_empty: bool = False) -> str:
    v = os.getenv(key)
    if v is None:
        raise RuntimeError(f"❌ Missing env key: {key}")
    if not allow_empty and v.strip() == "":
        raise RuntimeError(f"❌ Empty env key: {key}")
    return v

VOI_ALGOD_ADDRESS = require("VOI_ALGOD_ADDRESS")
VOI_ALGOD_TOKEN = require("VOI_ALGOD_TOKEN", allow_empty=True)
VOI_INDEXER_URL = require("VOI_INDEXER_URL")

VOI_MINT_APP_ID = int(require("VOI_MINT_APP_ID"))
VOI_MINT_LOG_PREFIX = require("VOI_MINT_LOG_PREFIX").encode()

RELAYER_MNEMONIC = require("RELAYER_MNEMONIC")

ALGO_ALGOD_URL = require("ALGO_ALGOD_URL")
ALGO_ALGOD_TOKEN = require("ALGO_ALGOD_TOKEN", allow_empty=True)
ALGO_INDEXER_URL = require("ALGO_INDEXER_URL")

ALGO_ESCROW_APP_ID = int(require("ALGO_ESCROW_APP_ID"))
ALGO_NUGGET_ASA_ID = int(require("ALGO_NUGGET_ASA_ID"))
ALGO_ADMIN_MNEMONIC = require("ALGO_ADMIN_MNEMONIC")

STATE_FILE = require("STATE_FILE")
INDEXER_LIMIT = int(require("INDEXER_LIMIT"))
POLL_DELAY = int(require("POLL_DELAY"))
MAX_BACKOFF = int(require("MAX_BACKOFF"))
ALGO_CONFIRM_ROUNDS = int(require("ALGO_CONFIRM_ROUNDS"))

# ============================================================
# STATE
# ============================================================

def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"processed": {}, "cursor_round": 0}

def save_state(st: Dict[str, Any]) -> None:
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=2)
    os.replace(tmp, STATE_FILE)

# ============================================================
# HELPERS
# ============================================================

def decode_log(raw: bytes) -> Optional[Dict[str, Any]]:
    if not raw.startswith(VOI_MINT_LOG_PREFIX):
        return None
    payload = raw[len(VOI_MINT_LOG_PREFIX):]
    if len(payload) < 72:
        return None

    return {
        "deposit_id": payload[0:32],
        "amount": int.from_bytes(payload[32:40], "big"),
        "receiver_bytes": payload[40:72],
        "receiver_addr": encoding.encode_address(payload[40:72]),
    }

# ============================================================
# MAIN LOOP
# ============================================================

def main():
    voi_idx = indexer.IndexerClient("", VOI_INDEXER_URL)
    algo_idx = indexer.IndexerClient("", ALGO_INDEXER_URL)

    voi_algod = algod.AlgodClient(VOI_ALGOD_TOKEN, VOI_ALGOD_ADDRESS)
    algo_algod = algod.AlgodClient(ALGO_ALGOD_TOKEN, ALGO_ALGOD_URL)

    relayer_sk = mnemonic.to_private_key(RELAYER_MNEMONIC)
    relayer_addr = account.address_from_private_key(relayer_sk)

    admin_sk = mnemonic.to_private_key(ALGO_ADMIN_MNEMONIC)
    admin_addr = account.address_from_private_key(admin_sk)

    st = load_state()
    cursor = int(st.get("cursor_round", 0))

    print(f"🚀 VOI→ALGO relayer online")
    print(f"VOI mint app : {VOI_MINT_APP_ID}")
    print(f"Relayer addr : {relayer_addr}")
    print(f"Algorand adm : {admin_addr}")
    print("-" * 60)

    backoff = 2

    while True:
        try:
            q = {"application_id": VOI_MINT_APP_ID, "limit": INDEXER_LIMIT}
            if cursor > 0:
                q["min_round"] = cursor

            resp = voi_idx.search_transactions(**q)
            txs = sorted(resp.get("transactions", []), key=lambda t: t["confirmed-round"])

            backoff = 2

            for tx in txs:
                cursor = max(cursor, tx["confirmed-round"] + 1)
                st["cursor_round"] = cursor

                for log_b64 in tx.get("logs", []):
                    decoded = decode_log(base64.b64decode(log_b64))
                    if not decoded:
                        continue

                    did = base64.b64encode(decoded["deposit_id"]).decode()
                    if did in st["processed"]:
                        continue

                    print(f"🟣 Mint log | amt={decoded['amount']} recv={decoded['receiver_addr']}")

                    # ---- Algorand withdraw
                    sp = algo_algod.suggested_params()
                    sp.flat_fee = True
                    sp.fee = 4000

                    txn = ApplicationNoOpTxn(
                        sender=admin_addr,
                        sp=sp,
                        index=ALGO_ESCROW_APP_ID,
                        app_args=[
                            b"withdraw",
                            decoded["receiver_bytes"],
                            decoded["amount"].to_bytes(8, "big"),
                        ],
                        foreign_assets=[ALGO_NUGGET_ASA_ID],
                        accounts=[decoded["receiver_addr"]],
                        note=decoded["deposit_id"],
                    )

                    txid = algo_algod.send_transaction(txn.sign(admin_sk))
                    wait_for_confirmation(algo_algod, txid, ALGO_CONFIRM_ROUNDS)

                    st["processed"][did] = {
                        "voi_txid": tx["id"],
                        "algo_txid": txid,
                        "amount": decoded["amount"],
                        "receiver": decoded["receiver_addr"],
                    }
                    save_state(st)

                    print(f"✅ Released on Algorand | {txid}")

            save_state(st)
            time.sleep(POLL_DELAY)

        except Exception as e:
            print(f"⚠️ Relayer error: {e}")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)

if __name__ == "__main__":
    main()
