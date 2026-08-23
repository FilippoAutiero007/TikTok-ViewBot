import re
import json
import logging
import requests
from urllib.parse import urlparse

log = logging.getLogger(__name__)

TIKTOK_PATTERNS = {
    'username': re.compile(r'@([\w.]+)'),
    'video_id': re.compile(r'/video/(\d+)'),
    'sec_uid': re.compile(r'sec_uid=([^&]+)'),
}


def parse_tiktok_url(url):
    result = {
        'url': url,
        'username': None,
        'video_id': None,
        'sec_uid': None,
        'type': 'unknown',
    }

    m = TIKTOK_PATTERNS['username'].search(url)
    if m:
        result['username'] = m.group(1)

    m = TIKTOK_PATTERNS['video_id'].search(url)
    if m:
        result['video_id'] = m.group(1)
        result['type'] = 'video'

    m = TIKTOK_PATTERNS['sec_uid'].search(url)
    if m:
        result['sec_uid'] = m.group(1)

    if result['username'] and not result['video_id']:
        result['type'] = 'profile'

    return result


def resolve_sec_uid(username):
    try:
        url = f'https://www.tiktok.com/@{username}'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        text = resp.text

        m = re.search(r'"secUid"\s*:\s*"([^"]+)"', text)
        if m:
            return m.group(1)

        m = re.search(r'sec_uid=([^&"]+)', text)
        if m:
            return m.group(1)

        m = re.search(r'"user"\s*:\s*\{[^}]*"secUid"\s*:\s*"([^"]+)"', text)
        if m:
            return m.group(1)

        log.warning('Could not resolve sec_uid for @%s', username)
        return None

    except Exception as e:
        log.error('Failed to resolve sec_uid: %s', e)
        return None


def resolve_video_id(url):
    parsed = parse_tiktok_url(url)
    if parsed['video_id']:
        return parsed['video_id']

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)',
        }
        resp = requests.head(url, headers=headers, allow_redirects=True, timeout=10)
        final_url = resp.url
        m = TIKTOK_PATTERNS['video_id'].search(final_url)
        if m:
            return m.group(1)
    except Exception as e:
        log.error('Failed to resolve video_id: %s', e)
    return None


def validate_tiktok_url(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        valid_hosts = [
            'tiktok.com', 'www.tiktok.com', 'vm.tiktok.com',
            'vt.tiktok.com', 'm.tiktok.com',
        ]
        return parsed.hostname in valid_hosts
    except (ValueError, AttributeError):
        return False


def get_temp_email():
    import random
    import string
    domains = [
        'guerrillamail.com', 'mailinator.com', 'yopmail.com',
        'throwaway.email', 'tempmail.com', '10minutemail.com',
        'sharklasers.com', 'guerrillamailblock.com',
    ]
    name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
    domain = random.choice(domains)
    return f'{name}@{domain}'
