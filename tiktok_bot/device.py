import json
import os
import random
import string
import time
from hashlib import md5

DEVICES_DIR = os.path.join(os.path.dirname(__file__), '..', 'devices')
ACCOUNTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'accounts')

ANDROID_MODELS = [
    'SM-G991B', 'SM-G996B', 'SM-G998B', 'SM-A525F', 'SM-A526B',
    'SM-A536B', 'SM-A546B', 'SM-A736B', 'SM-M526B', 'SM-M536B',
    'Pixel 6', 'Pixel 6 Pro', 'Pixel 7', 'Pixel 7 Pro', 'Pixel 8',
    'Pixel 8 Pro', 'Pixel 8a', 'Pixel 9', 'OnePlus 10 Pro', 'OnePlus 11',
    'OnePlus 12', 'OnePlus Nord 3', 'OnePlus Nord CE 3', 'OnePlus Ace 2',
    'Xiaomi 12', 'Xiaomi 13', 'Xiaomi 13 Pro', 'Xiaomi 14', 'Redmi Note 12',
    'Redmi Note 13', 'POCO X5 Pro', 'POCO F5', 'Realme GT 3', 'Realme 11 Pro',
    'OPPO Find X5', 'OPPO Find X6', 'Vivo X90', 'Vivo X100', 'Motorola Edge 40',
]

ANDROID_VERSIONS = ['12', '13', '14', '15']
SDK_VERSIONS = ['31', '33', '34', '35']
LOCALES = [
    'en_US', 'it_IT', 'es_ES', 'fr_FR', 'de_DE', 'pt_BR',
    'ja_JP', 'ko_KR', 'zh_CN', 'ru_RU', 'ar_SA', 'tr_TR',
]
LANGUAGES = ['en', 'it', 'es', 'fr', 'de', 'pt', 'ja', 'ko', 'zh', 'ru']
REGIONS = ['US', 'IT', 'ES', 'FR', 'DE', 'BR', 'JP', 'KR', 'CN', 'RU']
TIMEZONES = [
    'America/New_York', 'America/Los_Angeles', 'America/Chicago',
    'Europe/London', 'Europe/Rome', 'Europe/Madrid', 'Europe/Paris',
    'Europe/Berlin', 'Asia/Tokyo', 'Asia/Seoul', 'Asia/Shanghai',
    'Asia/Dubai', 'America/Sao_Paulo',
]
CARRIERS = [
    'T-Mobile', 'AT&T', 'Verizon', 'Vodafone', 'Orange', 'Telefonica',
    'Telenor', 'Swisscom', ' TIM', 'MTN', 'Airtel', 'Jio',
]

APP_VERSION = '34.0.2'
VERSION_CODE = '340002'
MANIFEST_VERSION = '2023400020'


def _random_hex(length):
    return ''.join(random.choices(string.hexdigits[:16], k=length))


def _random_id():
    return str(random.randint(1000000000, 9999999999))


def _generate_device_id():
    return str(random.randint(1000000000000000, 9999999999999999))


def _generate_install_id():
    return _generate_device_id()


def _generate_openudid():
    return _random_hex(16)


def _generate_android_id():
    return _random_hex(16)


def generate_device():
    model = random.choice(ANDROID_MODELS)
    android_ver = random.choice(ANDROID_VERSIONS)
    sdk_ver = random.choice(SDK_VERSIONS)
    locale = random.choice(LOCALES)
    lang = random.choice(LANGUAGES)
    region = random.choice(REGIONS)
    tz = random.choice(TIMEZONES)
    carrier = random.choice(CARRIERS)

    device = {
        'device_id': _generate_device_id(),
        'install_id': _generate_install_id(),
        'openudid': _generate_openudid(),
        'android_id': _generate_android_id(),
        'model': model,
        'brand': model.split('-')[0] if '-' in model else model.split(' ')[0],
        'product': model,
        'device_type': model,
        'android_version': android_ver,
        'sdk_version': sdk_ver,
        'resolution': random.choice(['1080x2340', '1080x2400', '1440x3200', '1080x2280']),
        'dpi': random.choice(['420', '440', '480', '560']),
        'locale': locale,
        'language': lang,
        'region': region,
        'timezone': tz,
        'carrier': carrier,
        'app_info': {
            'aid': 1233,
            'app_version': APP_VERSION,
            'version_code': VERSION_CODE,
            'manifest_version_code': MANIFEST_VERSION,
            'update_version_code': MANIFEST_VERSION,
            'package_name': 'com.zhiliaoapp.musically',
        },
        'created_at': int(time.time()),
    }
    return device


def save_device(device):
    os.makedirs(DEVICES_DIR, exist_ok=True)
    path = os.path.join(DEVICES_DIR, f"{device['device_id']}.json")
    with open(path, 'w') as f:
        json.dump(device, f, indent=2)
    return path


def load_device(device_id):
    path = os.path.join(DEVICES_DIR, f"{device_id}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def load_all_devices():
    os.makedirs(DEVICES_DIR, exist_ok=True)
    devices = []
    for fname in os.listdir(DEVICES_DIR):
        if fname.endswith('.json'):
            with open(os.path.join(DEVICES_DIR, fname)) as f:
                devices.append(json.load(f))
    return devices


def generate_batch(count):
    devices = []
    for _ in range(count):
        d = generate_device()
        save_device(d)
        devices.append(d)
    return devices
