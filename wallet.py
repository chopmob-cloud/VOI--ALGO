#!/usr/bin/env python3
# Create a new VOI/Algorand-style account (same key format)

from algosdk import account, mnemonic

def main():
    sk, addr = account.generate_account()
    m = mnemonic.from_private_key(sk)

    print("========================================")
    print("✅ NEW VOI WALLET CREATED")
    print("========================================")
    print("Address  :", addr)
    print("Mnemonic :", m)
    print("----------------------------------------")
    print("⚠️ SAVE THIS MNEMONIC OFFLINE. DO NOT PASTE IT INTO CHAT.")
    print("========================================")

if __name__ == "__main__":
    main()
