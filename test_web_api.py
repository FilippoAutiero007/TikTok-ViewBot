#!/usr/bin/env python3
import sys
import os
import json
import random
import string
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("  TikTok Web API Registration Test")
print("=" * 60)

# Step 1: Get session from TikTok website
print("\n--- Step 1: Get TikTok Web Session ---")
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
})

try:
    resp = session.get('https://www.tiktok.com/', timeout=10)
    print(f"Homepage status: {resp.status_code}")
    print(f"Cookies: {dict(session.cookies)}")
    
    # Look for verification token, ttwid, etc.
    for cookie_name in session.cookies:
        print(f"  Cookie: {cookie_name} = {session.cookies[cookie_name][:50]}...")
except Exception as e:
    print(f"Error: {e}")

# Step 2: Try web signup endpoint
print("\n--- Step 2: Try Web Signup ---")
rand_name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
email = f"{rand_name}@guerrillamail.com"
password = ''.join(random.choices(string.ascii_letters + string.digits + '!@#', k=14))

print(f"Email: {email}")
print(f"Password: {password}")

# TikTok web signup endpoint
signup_url = "https://www.tiktok.com/passport/web/email/register/v2/"
signup_data = {
    "email": email,
    "password": password,
    "multi_login": "1",
}

try:
    resp = session.post(signup_url, data=signup_data, timeout=10)
    print(f"Status: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('Content-Type')}")
    if resp.text:
        print(f"Response: {resp.text[:1000]}")
    else:
        print("Empty response")
except Exception as e:
    print(f"Error: {e}")

# Step 3: Try web login endpoint
print("\n--- Step 3: Try Web Login ---")
login_url = "https://www.tiktok.com/passport/web/login/v2/"
login_data = {
    "email": email,
    "password": password,
    "multi_login": "1",
}

try:
    resp = session.post(login_url, data=login_data, timeout=10)
    print(f"Status: {resp.status_code}")
    if resp.text:
        try:
            data = resp.json()
            print(f"Response: {json.dumps(data, indent=2)[:2000]}")
        except:
            print(f"Response (raw): {resp.text[:1000]}")
    else:
        print("Empty response")
except Exception as e:
    print(f"Error: {e}")

# Step 4: Check available passport endpoints
print("\n--- Step 4: Check passport endpoints ---")
endpoints_to_try = [
    "/passport/web/account/register/",
    "/passport/web/email/register/",
    "/passport/web/email/send_code/",
    "/passport/web/user/login/",
    "/passport/web/login/",
]

for endpoint in endpoints_to_try:
    try:
        url = f"https://www.tiktok.com{endpoint}"
        resp = session.post(url, data={"test": "1"}, timeout=5)
        print(f"  {endpoint} -> {resp.status_code} ({resp.headers.get('Content-Type', 'unknown')[:30]})")
    except Exception as e:
        print(f"  {endpoint} -> ERROR: {e}")
