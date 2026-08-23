#!/usr/bin/env python3
import sys
import os
import json
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tiktok_signer import TikTokSigner, DeviceProfile

print("=== Testing tiktok-signer ===")

signer = TikTokSigner()
device = signer.get_device()
print("Device:", json.dumps(device.to_dict(), indent=2))

print()
print("=== Generating signatures ===")

params = {"aid": "1233", "device_id": device.device_id, "count": "20"}
params_str = urlencode(sorted(params.items()))
print(f"Params: {params_str}")

try:
    headers = signer.generate_headers(
        params=params,
        data=None,
        version_code=340002,
        version_name="34.0.2",
    )
    print("Generated headers:")
    for k, v in headers.items():
        val = str(v)
        print(f"  {k}: {val[:120]}...")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

print()
print("=== Test with TikTok API ===")

import requests

try:
    headers = signer.generate_headers(
        params=params,
        data=None,
        version_code=340002,
        version_name="34.0.2",
    )
    
    headers['User-Agent'] = 'com.zhiliaoapp.musically/340002 (Linux; U; Android 13; en_US; SM-G991B; Build/TP1A.220624.014; Cronet/TTNetVersion:b4d74d15 2023-02-14)'
    headers['Accept'] = 'application/json'
    
    url = f"https://api16-normal-c-useast1a.tiktokv.com/aweme/v1/tab/feed/?{params_str}"
    print(f"Request: GET {url[:120]}")
    
    resp = requests.get(url, headers=headers, timeout=10)
    print(f"Status: {resp.status_code}")
    print(f"Response (first 500): {resp.text[:500]}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
