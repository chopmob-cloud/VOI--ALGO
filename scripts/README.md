Scripts Overview — VOI ↔ Algorand Bridge

This directory contains scripts used to deploy, test, and operate the VOI → Algorand bridge.

⚠️ Important
Not all scripts are required for all setups.
If you are using the official treasury-managed escrow, you do NOT need to deploy your own escrow application.

✅ Required for Production Use

These scripts are required to run or interact with the bridge.

deploy_log_validator_v4.py

Required

Deploys the VOI Log Validator Application (V4).

This application:

Validates grouped ASA deposits

Enforces TEAL-level constraints (asset ID, treasury receiver, group structure)

Emits a canonical log consumed by the relayer

This must be deployed for the bridge to function.

<hr>

test_voi_deposit_v4.py

Required for testing

Creates a valid VOI deposit transaction group:

ASA transfer → treasury

App call → validator

Emits a V4 log

Use this to:

Test the validator app

Test relayer ingestion

Verify end-to-end bridge flow

<hr>

app_optin.py

Required (one-time per account)

Opts an Algorand account into the Nugget ASA.

The Algorand receiver must be opted-in before funds can be released by the escrow.

<hr>

⚠️ Optional / Advanced (For Custom Bridge Operators)

These scripts are NOT required if you are using the official treasury escrow.

deploy_voi_escrow.py

Optional — advanced users only

Deploys a custom Algorand escrow application.

Use this only if:

You want to run your own bridge

You are not using the official treasury escrow

You want full control over withdrawal logic and nonce tracking

If you are using the treasury-managed escrow:

❌ Do NOT run this script
