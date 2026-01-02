from algosdk.v2client import algod
import base64

ALGOD = algod.AlgodClient("", "https://mainnet-api.voi.nodely.dev")

def compile_template(
    treasury_pk_hex,
    asa_id,
    prefix_ascii
):
    with open("approval.template.teal") as f:
        teal = f.read()

    teal = teal.replace(
        "__TREASURY_PUBKEY_32_BYTES__",
        treasury_pk_hex.lower()
    ).replace(
        "__ASA_ID__",
        str(asa_id)
    ).replace(
        "__LOG_PREFIX_BYTES__",
        prefix_ascii.encode().hex()
    )

    res = ALGOD.compile(teal)
    with open("approval.bin", "wb") as f:
        f.write(base64.b64decode(res["result"]))

    print("Compiled approval.bin")

compile_template(
    treasury_pk_hex="04e022f96011e999858563c0b4115e5a87f787f37d97aebb105454afefb432fc",
    asa_id=48146090,
    prefix_ascii="NUGGET_V4|"
)
