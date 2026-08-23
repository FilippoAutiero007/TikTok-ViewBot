import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tiktok_bot.device import generate_batch
from tiktok_bot.accounts import AccountManager

print("=== Generating 10 devices ===")
devices = generate_batch(10)
for d in devices:
    print(f"  {d['device_id']} | {d['model']} | Android {d['android_version']} | {d['region']}")
print(f"\nGenerated {len(devices)} devices\n")

print("=== Creating 10 account configs ===")
am = AccountManager()
for i in range(10):
    account = am.create_account()
    account.save()
    print(f"  [{i+1}/10] {account.username} | {account.email} | device: {account.device_id[:12]}...")

print(f"\nDone! {len(am.accounts)} accounts ready")
print(f"\nAccounts saved in: accounts/active/")
