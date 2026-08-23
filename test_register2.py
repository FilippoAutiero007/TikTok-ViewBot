#!/usr/bin/env python3
import sys
import os
import json
import random
import string
import time
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tiktok_signer import TikTokSigner

print("=" * 60)
print("  TikTok Account Registration Test (tiktok-signer)")
print("=" * 60)

# Generate random credentials
rand_name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
email = f"{rand_name}@guerrillamail.com"
password = ''.join(random.choices(string.ascii_letters + string.digits + '!@#', k=14))

print(f"\nEmail: {email}")
print(f"Password: {password}")

# Create signer with new device
signer = TikTokSigner()
device = signer.get_device()
print(f"Device ID: {device.device_id}")
print(f"Install ID: {device.openudid}")

# Step 1: Get app region
print("\n--- Step 1: Get App Region ---")
try:
    region_params = {
        "aid": "1233",
        "device_id": device.device_id,
    }
    headers = signer.generate_headers(params=region_params, version_code=340002, version_name="34.0.2")
    headers['User-Agent'] = 'com.zhiliaoapp.musically/340002 (Linux; U; Android 13; en_US; SM-G991B; Build/TP1A.220624.014)'
    
    import requests
    url = f"https://api22-normal-c-useast1a.tiktokv.com/passport/app/region/v2/?{urlencode(sorted(region_params.items()))}"
    resp = requests.post(url, headers=headers, timeout=10)
    print(f"Status: {resp.status_code}")
    data = resp.json()
    print(f"Response: {json.dumps(data, indent=2)[:300]}")
    
    if 'data' in data:
        domain = data['data'].get('domain', '')
        captcha_domain = data['data'].get('captcha_domain', '')
        print(f"Domain: {domain}")
        print(f"Captcha domain: {captcha_domain}")
except Exception as e:
    print(f"Error: {e}")

# Step 2: Device Register
print("\n--- Step 2: Device Register ---")
try:
    device_params = {
        "aid": "1233",
        "device_id": device.device_id,
    }
    headers = signer.generate_headers(params=device_params, version_code=340002, version_name="34.0.2")
    headers['User-Agent'] = 'com.zhiliaoapp.musically/340002 (Linux; U; Android 13; en_US; SM-G991B; Build/TP1A.220624.014)'
    
    url = f"https://api22-normal-c-useast1a.tiktokv.com/passport/device/register/v2/?{urlencode(sorted(device_params.items()))}"
    resp = requests.post(url, headers=headers, timeout=10)
    print(f"Status: {resp.status_code}")
    data = resp.json()
    print(f"Response: {json.dumps(data, indent=2)[:500]}")
except Exception as e:
    print(f"Error: {e}")

# Step 3: Register Account
print("\n--- Step 3: Register Account ---")
try:
    from tiktok_bot.client import _xor_encode
    
    birthday = f"{random.randint(1990, 2005)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
    payload = (
        f"password={_xor_encode(password)}&"
        f"fixed_mix_mode=1&"
        f"rules_version=v2&"
        f"mix_mode=1&"
        f"multi_login=1&"
        f"email={_xor_encode(email)}&"
        f"account_sdk_source=app&"
        f"birthday={birthday}&"
        f"multi_signup=0"
    )
    
    reg_params = {
        "aid": "1233",
        "device_id": device.device_id,
        "passport-sdk-version": "5030190",
        "uoo": "0",
        "cronet_version": "",
        "ttnet_version": "",
        "use_store_region_cookie": "1",
    }
    
    headers = signer.generate_headers(
        params=reg_params,
        data=payload.encode(),
        version_code=340002,
        version_name="34.0.2",
    )
    headers['User-Agent'] = 'com.zhiliaoapp.musically/340002 (Linux; U; Android 13; en_US; SM-G991B; Build/TP1A.220624.014)'
    headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
    
    url = f"https://api22-normal-c-useast1a.tiktokv.com/passport/email/register/v2/?{urlencode(sorted(reg_params.items()))}"
    resp = requests.post(url, headers=headers, data=payload, timeout=15)
    print(f"Status: {resp.status_code}")
    print(f"Headers: {dict(resp.headers)}")
    data = resp.json()
    print(f"Response: {json.dumps(data, indent=2)[:1000]}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
