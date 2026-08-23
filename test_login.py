#!/usr/bin/env python3
import sys
import os
import json
import random
import string
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tiktok_signer import TikTokSigner
from tiktok_bot.client import _xor_encode
import requests

# Use same credentials from last test
email = "eskvt7iybw3l@guerrillamail.com"
password = "2d2hFnBQ!LYE5#"

print("=" * 60)
print("  TikTok Login Test")
print("=" * 60)
print(f"Email: {email}")
print(f"Password: {password}")

signer = TikTokSigner()
device = signer.get_device()
print(f"Device ID: {device.device_id}")

# Step 1: Login
print("\n--- Login ---")
try:
    login_params = {
        "aid": "1233",
        "device_id": device.device_id,
        "passport-sdk-version": "19",
        "uoo": "0",
    }
    
    payload = (
        f"password={_xor_encode(password)}&"
        f"account_sdk_source=app&"
        f"multi_login=1&"
        f"mix_mode=1&"
        f"email={_xor_encode(email)}"
    )
    
    headers = signer.generate_headers(
        params=login_params,
        data=payload.encode(),
        version_code=340002,
        version_name="34.0.2",
    )
    headers['User-Agent'] = 'com.zhiliaoapp.musically/340002 (Linux; U; Android 13; en_US; SM-G991B; Build/TP1A.220624.014)'
    headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
    
    url = f"https://api22-normal-c-useast1a.tiktokv.com/passport/user/login/v2/?{urlencode(sorted(login_params.items()))}"
    print(f"URL: {url[:120]}")
    
    resp = requests.post(url, headers=headers, data=payload, timeout=15)
    print(f"Status: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('Content-Type')}")
    
    if resp.text:
        try:
            data = resp.json()
            print(f"Response: {json.dumps(data, indent=2)[:2000]}")
            
            error_code = data.get('error_code', 0)
            if error_code == 0:
                user_data = data.get('data', {})
                user = user_data.get('user', {})
                print(f"\nLOGIN SUCCESS!")
                print(f"  User ID: {user.get('uid')}")
                print(f"  Username: {user.get('unique_id')}")
                print(f"  Nickname: {user.get('nickname')}")
                print(f"  sec_uid: {user.get('sec_uid')}")
                
                x_token = resp.headers.get('x-tt-token', '')
                print(f"  X-Tt-Token: {x_token[:80]}...")
            else:
                print(f"\nLOGIN FAILED: error_code={error_code}")
                print(f"  Message: {data.get('description', '')}")
        except json.JSONDecodeError:
            print(f"Response (raw, first 500): {resp.text[:500]}")
    else:
        print("Response body is empty")
        print(f"All headers: {dict(resp.headers)}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

# Step 2: Also try a different registration - this time register a NEW account
print("\n\n--- Register NEW Account ---")
rand_name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
new_email = f"{rand_name}@guerrillamail.com"
new_password = ''.join(random.choices(string.ascii_letters + string.digits + '!@#', k=14))
print(f"New Email: {new_email}")
print(f"New Password: {new_password}")

try:
    birthday = f"{random.randint(1990, 2005)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
    payload = (
        f"password={_xor_encode(new_password)}&"
        f"fixed_mix_mode=1&"
        f"rules_version=v2&"
        f"mix_mode=1&"
        f"multi_login=1&"
        f"email={_xor_encode(new_email)}&"
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
    print(f"Content-Type: {resp.headers.get('Content-Type')}")
    print(f"Content-Length: {resp.headers.get('Content-Length')}")
    
    if resp.text:
        print(f"Response: {resp.text[:2000]}")
    else:
        print("Response body is empty (might be success!)")
        
    x_token = resp.headers.get('x-tt-token', '')
    if x_token:
        print(f"X-Tt-Token received: {x_token[:80]}...")
        
    # Try to login right after
    print(f"\n--- Login with NEW credentials ---")
    login_params2 = {
        "aid": "1233",
        "device_id": device.device_id,
        "passport-sdk-version": "19",
        "uoo": "0",
    }
    
    payload2 = (
        f"password={_xor_encode(new_password)}&"
        f"account_sdk_source=app&"
        f"multi_login=1&"
        f"mix_mode=1&"
        f"email={_xor_encode(new_email)}"
    )
    
    headers2 = signer.generate_headers(
        params=login_params2,
        data=payload2.encode(),
        version_code=340002,
        version_name="34.0.2",
    )
    headers2['User-Agent'] = 'com.zhiliaoapp.musically/340002 (Linux; U; Android 13; en_US; SM-G991B; Build/TP1A.220624.014)'
    headers2['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
    
    url2 = f"https://api22-normal-c-useast1a.tiktokv.com/passport/user/login/v2/?{urlencode(sorted(login_params2.items()))}"
    resp2 = requests.post(url2, headers=headers2, data=payload2, timeout=15)
    print(f"Status: {resp2.status_code}")
    
    if resp2.text:
        data2 = resp2.json()
        error_code = data2.get('error_code', 0)
        if error_code == 0:
            user = data2.get('data', {}).get('user', {})
            print(f"LOGIN SUCCESS!")
            print(f"  User ID: {user.get('uid')}")
            print(f"  Username: {user.get('unique_id')}")
        else:
            print(f"Login error: {data2.get('description', '')}")
    else:
        print("Empty response")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
