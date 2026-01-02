#!/usr/bin/env python3
# ============================================================
# VOI → Algorand Relayer (V4)
#
# Watches VOI for V4 validator logs:
#   VOI_LOG_PREFIX | deposit_id(32) | algo_receiver(32) | amount(8) | voi_axfer_txid(32)
#
# Then executes Algorand escrow withdraw:
#   app_args: ["withdraw", receiver(32), amount_u64, nonce_u64]
#
# Hardened against:
# - VOI indexer 504s (multi-indexer fallback + backoff)
# - backfilling from genesis (auto-start near head unless COUNTER_START given)
# - pagination storms (strict page cap)
# - empty scans stalling (cursor advances even when nothing found)
# - missing/empty env values (fails fast)
# ============================================================

import base64
import json
import logging
import os
import random
import sys
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from algosdk import account, encoding, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import ApplicationNoOpTxn, wait_for_confirmation


# ----------------------------
# Logging (to journald/stdout)
# ----------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("voi-to-algo")


# ----------------------------
# Env helpers
# ----------------------------
def require(key: str, allow_empty: bool = False) -> str:
    v = os.getenv(key)
    if v is None:
        raise RuntimeError(f"Missing env key: {key}")
    if not allow_empty and v.strip() == "":
        raise RuntimeError(f"Empty env key: {key}")
    return v.strip()


def getenv_int(key: str, default: Optional[int] = None) -> int:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        if default is None:
            raise RuntimeError(f"Missing env key: {key}")
        return default
    return int(v.strip())


def parse_csv_urls(value: str) -> List[str]:
    items = [x.strip() for x in value.split(",") if x.strip()]
    # de-dupe while preserving order
    seen = set()
    out = []
    for u in items:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


# ----------------------------
# Indexer REST wrapper (no SDK quirks)
# ----------------------------
class IndexerREST:
    def __init__(self, base_url: str, token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = token or ""

    def get_json(self, path: str, params: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{self.base_url}{path}?{qs}" if qs else f"{self.base_url}{path}"

        req = urllib.request.Request(url, method="GET")
        if self.token:
            # Some indexers accept this header name; harmless if unused.
            req.add_header("X-Indexer-API-Token", self.token)

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            # indexers return json
            return json.loads(raw.decode("utf-8"))


def voi_indexer_query_with_fallback(
    indexers: List[IndexerREST],
    path: str,
    params: Dict[str, Any],
    timeout: int = 15,
) -> Dict[str, Any]:
    last_err: Optional[Exception] = None
    for idx in indexers:
        try:
            return idx.get_json(path, params=params, timeout=timeout)
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"All VOI indexers failed. Last error: {last_err}")


# ----------------------------
# State
# ----------------------------
def load_state(state_file: str) -> Dict[str, Any]:
    try:
        if os.path.exists(state_file):
            with open(state_file, "r", encoding="utf-8") as f:
                st = json.load(f)
                if not isinstance(st, dict):
                    raise ValueError("state not a dict")
                st.setdefault("processed", {})
                st.setdefault("cursor_round", 0)
                return st
    except Exception:
        log.warning("⚠️ Could not read state file, reinitializing")
    return {"processed": {}, "cursor_round": 0}


def save_state(state_file: str, st: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    tmp = state_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2, sort_keys=True)
    os.replace(tmp, state_file)


# ----------------------------
# Decode VOI V4 log line
#   prefix | deposit_id(32) | receiver(32) | amount(8) | voi_txid(32)
# ----------------------------
def decode_v4_log(prefix: bytes, raw_log_bytes: bytes) -> Optional[Dict[str, Any]]:
    if not raw_log_bytes.startswith(prefix):
        return None

    payload = raw_log_bytes[len(prefix) :]
    if len(payload) < (32 + 32 + 8 + 32):
        return None

    deposit_id = payload[0:32]
    receiver_bytes = payload[32:64]
    amount_bytes = payload[64:72]
    voi_axfer_txid = payload[72:104]

    amount = int.from_bytes(amount_bytes, "big")

    # receiver_bytes are raw public key bytes; encode as Algorand address
    receiver_addr = encoding.encode_address(receiver_bytes)

    return {
        "deposit_id": deposit_id,
        "receiver_bytes": receiver_bytes,
        "receiver_addr": receiver_addr,
        "amount": amount,
        "voi_axfer_txid": voi_axfer_txid,
    }


# ----------------------------
# Algorand escrow nonce fetch (global state key "nonce")
# ----------------------------
def fetch_escrow_nonce(algo_algod: algod.AlgodClient, app_id: int) -> int:
    info = algo_algod.application_info(app_id)
    gs = info.get("params", {}).get("global-state", []) or []
    for kv in gs:
        k_b64 = kv.get("key")
        if not k_b64:
            continue
        k = base64.b64decode(k_b64).decode("utf-8", errors="ignore")
        if k == "nonce":
            v = kv.get("value", {})
            # nonce stored as uint
            return int(v.get("uint", 0))
    return 0


def account_opted_in_asset(algo_algod: algod.AlgodClient, addr: str, asset_id: int) -> bool:
    try:
        info = algo_algod.account_info(addr)
        for a in info.get("assets", []) or []:
            if int(a.get("asset-id", 0)) == int(asset_id):
                return True
        return False
    except Exception:
        # If the lookup fails, be conservative and treat as not opted in
        return False


# ----------------------------
# Main
# ----------------------------
def main() -> None:
    log.info("🔁 Relayer starting…")

    # ---- VOI (source)
    VOI_ALGOD_ADDRESS = require("VOI_ALGOD_ADDRESS")
    VOI_ALGOD_TOKEN = require("VOI_ALGOD_TOKEN", allow_empty=True)

    # Prefer multi-url key, fall back to single
    if os.getenv("VOI_INDEXER_URLS", "").strip():
        voi_indexer_urls = parse_csv_urls(require("VOI_INDEXER_URLS"))
    else:
        voi_indexer_urls = [require("VOI_INDEXER_URL")]

    VOI_LOG_APP_ID = int(require("VOI_LOG_APP_ID"))
    VOI_LOG_PREFIX = require("VOI_LOG_PREFIX").encode("utf-8")
    VOI_NUGGET_ASA_ID = int(require("VOI_NUGGET_ASA_ID"))
    VOI_TREASURY_ADDRESS = os.getenv("VOI_TREASURY_ADDRESS", "").strip()  # optional

    # ---- Algorand (destination)
    ALGO_ALGOD_ADDRESS = require("ALGO_ALGOD_ADDRESS")
    ALGO_ALGOD_TOKEN = require("ALGO_ALGOD_TOKEN", allow_empty=True)
    ALGO_ESCROW_APP_ID = int(require("ALGO_ESCROW_APP_ID"))
    ALGO_NUGGET_ASA_ID = int(require("ALGO_NUGGET_ASA_ID"))
    ALGO_ADMIN_MNEMONIC = require("ALGO_ADMIN_MNEMONIC")

    # ---- Relayer controls
    STATE_FILE = require("STATE_FILE")
    INDEXER_LIMIT = getenv_int("INDEXER_LIMIT", 20)
    POLL_DELAY = getenv_int("POLL_DELAY", 20)
    MAX_BACKOFF = getenv_int("MAX_BACKOFF", 180)
    ALGO_CONFIRM_ROUNDS = getenv_int("ALGO_CONFIRM_ROUNDS", 12)

    # If VOI indexer is flaky, avoid genesis by default:
    # - If COUNTER_START provided (>0) use it
    # - Else auto-start near head (last-round - AUTO_START_LOOKBACK)
    COUNTER_START = getenv_int("COUNTER_START", 0)
    AUTO_START_LOOKBACK = getenv_int("AUTO_START_LOOKBACK", 4000)

    # strict caps
    MAX_PAGES_PER_SCAN = getenv_int("MAX_PAGES_PER_SCAN", 5)
    EMPTY_ADVANCE_LAG = getenv_int("EMPTY_ADVANCE_LAG", 50)  # move cursor up to head-lag on empty scans

    # ---- clients
    voi_algod = algod.AlgodClient(VOI_ALGOD_TOKEN, VOI_ALGOD_ADDRESS)
    algo_algod = algod.AlgodClient(ALGO_ALGOD_TOKEN, ALGO_ALGOD_ADDRESS)

    voi_indexers = [IndexerREST(u, token="") for u in voi_indexer_urls]

    admin_sk = mnemonic.to_private_key(ALGO_ADMIN_MNEMONIC)
    admin_addr = account.address_from_private_key(admin_sk)

    log.info("ENV CHECK: %s %s %s", VOI_LOG_APP_ID, voi_indexer_urls[0], ALGO_ESCROW_APP_ID)
    log.info("Algorand admin: %s", admin_addr)
    if VOI_TREASURY_ADDRESS:
        log.info("VOI treasury (optional): %s", VOI_TREASURY_ADDRESS)

    st = load_state(STATE_FILE)
    cursor = int(st.get("cursor_round", 0))

    # Initialize cursor smartly if empty / 0
    if cursor <= 0:
        try:
            head = int(voi_algod.status().get("last-round", 0))
        except Exception:
            head = 0

        if COUNTER_START and COUNTER_START > 0:
            cursor = COUNTER_START
            log.info("🔧 Using COUNTER_START=%d", cursor)
        else:
            cursor = max(0, head - AUTO_START_LOOKBACK)
            log.info("🔧 Auto-start near head: head=%d -> cursor=%d", head, cursor)

        st["cursor_round"] = cursor
        save_state(STATE_FILE, st)

    log.info("🔍 Scanning VOI txns from round %d", cursor)

    backoff = 2

    while True:
        try:
            # Always know head so we can advance cursor on empty scans
            try:
                voi_head = int(voi_algod.status().get("last-round", 0))
            except Exception:
                voi_head = 0

            found_any = False
            pages = 0
            next_token: Optional[str] = None
            scan_cursor = cursor

            while pages < MAX_PAGES_PER_SCAN:
                params: Dict[str, Any] = {
                    "application-id": VOI_LOG_APP_ID,
                    "min-round": scan_cursor,
                    "limit": INDEXER_LIMIT,
                    "tx-type": "appl",
                }
                if next_token:
                    params["next"] = next_token

                resp = voi_indexer_query_with_fallback(
                    voi_indexers,
                    path="/v2/transactions",
                    params=params,
                    timeout=15,
                )

                txs = resp.get("transactions", []) or []
                next_token = resp.get("next-token")  # may be absent
                pages += 1

                if not txs:
                    break

                # process in confirmed-round order
                txs = sorted(txs, key=lambda t: int(t.get("confirmed-round", 0)))

                for tx in txs:
                    cr = int(tx.get("confirmed-round", 0))
                    if cr <= 0:
                        continue

                    # IMPORTANT: advance cursor based on chain progress
                    cursor = max(cursor, cr + 1)
                    st["cursor_round"] = cursor

                    logs_b64 = tx.get("logs", []) or []
                    if not logs_b64:
                        continue

                    for lb64 in logs_b64:
                        try:
                            raw = base64.b64decode(lb64)
                        except Exception:
                            continue

                        decoded = decode_v4_log(VOI_LOG_PREFIX, raw)
                        if not decoded:
                            continue

                        found_any = True

                        did_b64 = base64.b64encode(decoded["deposit_id"]).decode("utf-8")
                        if did_b64 in st["processed"]:
                            continue

                        # sanity checks
                        if decoded["amount"] <= 0:
                            continue

                        # If receiver isn't opted-in on Algorand, escrow transfer will fail.
                        # (Relayer should log it clearly instead of crashing.)
                        if not account_opted_in_asset(algo_algod, decoded["receiver_addr"], ALGO_NUGGET_ASA_ID):
                            log.warning(
                                "❌ Receiver not opted-in on Algorand: %s (asset %d). Skipping deposit_id=%s",
                                decoded["receiver_addr"],
                                ALGO_NUGGET_ASA_ID,
                                did_b64,
                            )
                            st["processed"][did_b64] = {
                                "status": "receiver_not_opted_in",
                                "voi_round": cr,
                                "voi_txid": tx.get("id"),
                                "amount": decoded["amount"],
                                "receiver": decoded["receiver_addr"],
                            }
                            save_state(STATE_FILE, st)
                            continue

                        log.info(
                            "🟣 VOI deposit log: amount=%d receiver=%s deposit_id=%s",
                            decoded["amount"],
                            decoded["receiver_addr"],
                            did_b64,
                        )

                        # ----- Algorand withdraw
                        current_nonce = fetch_escrow_nonce(algo_algod, ALGO_ESCROW_APP_ID)
                        next_nonce = current_nonce + 1

                        sp = algo_algod.suggested_params()
                        sp.flat_fee = True
                        sp.fee = 4000  # enough for app call

                        app_args = [
                            b"withdraw",
                            decoded["receiver_bytes"],                     # 32 bytes
                            int(decoded["amount"]).to_bytes(8, "big"),     # amount u64
                            int(next_nonce).to_bytes(8, "big"),            # nonce u64
                        ]

                        withdraw_txn = ApplicationNoOpTxn(
                            sender=admin_addr,
                            sp=sp,
                            index=ALGO_ESCROW_APP_ID,
                            app_args=app_args,
                            foreign_assets=[ALGO_NUGGET_ASA_ID],
                            # some approval programs want receiver in accounts[]
                            accounts=[decoded["receiver_addr"]],
                            # put deposit id in note so you can correlate
                            note=decoded["deposit_id"],
                        )

                        algo_txid = algo_algod.send_transaction(withdraw_txn.sign(admin_sk))
                        wait_for_confirmation(algo_algod, algo_txid, ALGO_CONFIRM_ROUNDS)

                        st["processed"][did_b64] = {
                            "status": "released",
                            "voi_round": cr,
                            "voi_txid": tx.get("id"),
                            "algo_txid": algo_txid,
                            "amount": decoded["amount"],
                            "receiver": decoded["receiver_addr"],
                            "nonce": next_nonce,
                        }
                        save_state(STATE_FILE, st)

                        log.info("✅ Released on Algorand: %s (nonce=%d)", algo_txid, next_nonce)

                # If there is no next token, stop paging
                if not next_token:
                    break

                # keep scan_cursor aligned to global cursor so we don't loop same range
                scan_cursor = cursor

            # If no deposits were found, advance cursor close to head (prevents genesis backfill)
            if not found_any and voi_head > 0:
                cursor = max(cursor, max(0, voi_head - EMPTY_ADVANCE_LAG))
                st["cursor_round"] = cursor
                save_state(STATE_FILE, st)
                log.info("…no new deposits. last_round=%d (cursor=%d)", voi_head, cursor)
            else:
                save_state(STATE_FILE, st)

            backoff = 2
            time.sleep(POLL_DELAY)

        except Exception as e:
            log.warning("⚠️ Relayer error: %s", e)

            # jittered exponential backoff
            sleep_for = min(MAX_BACKOFF, backoff) + random.uniform(0, 1.0)
            time.sleep(sleep_for)
            backoff = min(MAX_BACKOFF, backoff * 2)


if __name__ == "__main__":
    main()

