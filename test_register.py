#!/usr/bin/env python3
import sys
import os
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.DEBUG, format='%(levelname)s %(message)s')

from tiktok_bot.device import generate_device
from tiktok_bot.client import TikTokClient, _build_query_string, _build_headers, _generate_xgorgon, _generate_xargus, _generate_xkhronos, PASSPORT_DOMAINS
from urllib.parse import urlencode

device = generate_device()
client = TikTokClient(device)

print("=" * 60)
print("DEVICE:", json.dumps(device, indent=2)[:200], "...")
print("=" * 60)

# Test 1: get_app_region
print("\n--- TEST 1: get_app_region ---")
try:
    region = client.get_app_region()
    print("Region result:", json.dumps(region, indent=2) if region else "None")
    print("Domain:", client.domain)
    print("Passport:", client.passport_domain)
    print("Captcha:", client.captcha_domain)
except Exception as e:
    print("ERROR:", e)

# Test 2: device_register
print("\n--- TEST 2: device_register ---")
try:
    result = client.device_register()
    print("Device register result:", json.dumps(result, indent=2) if result else "None")
    print("Device ID:", client.device.get('device_id'))
except Exception as e:
    print("ERROR:", e)

# Test 3: raw request to see what TikTok returns
print("\n--- TEST 3: Raw passport request ---")
try:
    query = _build_query_string(client.device)
    url_path = '/passport/app/region/v2/'
    url = f'https://{client.passport_domain}/{url_path}?{query}'
    headers = client._build_passport_headers()
    headers['X-Gorgon'] = _generate_xgorgon(url_path, query)
    headers['X-Argus'] = _generate_xargus(client.device, url_path)
    headers['X-Khronos'] = _generate_xkhronos()
    
    print("URL:", url[:150])
    print("Headers:", json.dumps({k: v[:50] if isinstance(v, str) else v for k, v in headers.items()}, indent=2))
    
    resp = client.session.post(url, headers=headers, timeout=15)
    print("Status:", resp.status_code)
    print("Headers response:", dict(resp.headers))
    print("Body (first 500 chars):", resp.text[:500])
except Exception as e:
    print("ERROR:", e)
