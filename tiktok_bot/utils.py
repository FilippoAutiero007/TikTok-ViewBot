import re
import json
import time
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


def resolve_sec_uid(username, proxy=None, timeout=12):
    """
    Ottimizzato ispirazione apivault-labs/tiktok-profile-scraper-python:
    - estrae da __UNIVERSAL_DATA_FOR_REHYDRATION__ (priorità) poi SIGI_STATE
    - retry con proxy rotation + residential headers
    - 3 tentativi con backoff
    """
    username = username.lstrip('@').strip()
    url = f'https://www.tiktok.com/@{username}'
    headers_list = [
        {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://www.tiktok.com/',
            'Sec-Fetch-Mode': 'navigate',
        },
        {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
    ]
    for attempt in range(3):
        try:
            headers = headers_list[attempt % len(headers_list)]
            proxies = {'http': proxy, 'https': proxy} if proxy else None
            resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True, proxies=proxies)
            if resp.status_code != 200:
                log.debug('resolve_sec_uid attempt %d status %d', attempt+1, resp.status_code)
                time.sleep(1 + attempt)
                continue
            text = resp.text
            low = text.lower()
            # Wall login/captcha: prima ritentava 3x identiche e poi follow(None).
            # Rileva subito e abortisce con log chiaro.
            if '<title' in low and ('log in | tiktok' in low or 'login' in low[:5000]):
                if 'secuid' not in low and '__universal_data_for_rehydration__' not in low:
                    log.warning(
                        'resolve_sec_uid @%s: TikTok ha risposto con wall login (len=%d), '
                        'niente secUid. Serve proxy/cookie o uid numerico manuale.',
                        username, len(text),
                    )
                    return None
            if any(k in low for k in ('captcha', 'verify', 'challenge')) and 'secuid' not in low:
                log.warning('resolve_sec_uid @%s: pagina captcha/challenge, abort', username)
                return None

            # 1. __UNIVERSAL_DATA_FOR_REHYDRATION__ (metodo apivault - più stabile)
            m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', text, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1))
                    # ricerca ricorsiva secUid
                    def find_secUid(obj):
                        if isinstance(obj, dict):
                            if 'secUid' in obj and isinstance(obj['secUid'], str) and obj['secUid'].startswith('MS4w'):
                                return obj['secUid']
                            for v in obj.values():
                                r = find_secUid(v)
                                if r: return r
                        elif isinstance(obj, list):
                            for v in obj:
                                r = find_secUid(v)
                                if r: return r
                        return None
                    found = find_secUid(data)
                    if found:
                        log.info('Resolved secUid via UNIVERSAL_DATA (%d chars)', len(found))
                        return found
                except Exception as e:
                    log.debug('UNIVERSAL_DATA parse failed: %s', e)

            # 2. SIGI_STATE fallback
            m = re.search(r'<script id="SIGI_STATE"[^>]*>(.*?)</script>', text, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1))
                    # struttura: UserModule users[username] secUid
                    users = data.get('UserModule', {}).get('users', {})
                    if username in users and users[username].get('secUid'):
                        return users[username]['secUid']
                    # fallback search
                    txt = m.group(1)
                    mm = re.search(r'"secUid"\s*:\s*"([^"]+)"', txt)
                    if mm: return mm.group(1)
                except Exception:
                    pass

            # 3. regex diretto (legacy)
            for pat in [r'"secUid"\s*:\s*"([^"]+)"', r'sec_uid=([^&"]+)', r'"secUid":"([^"]+)"', r'secUid:\s*"([^"]+)"']:
                mm = re.search(pat, text)
                if mm:
                    sec = mm.group(1)
                    if sec.startswith('MS4w') or len(sec) > 30:
                        return sec

            log.debug('resolve_sec_uid attempt %d no match, len %d', attempt+1, len(text))
            time.sleep(1 + attempt)
        except Exception as e:
            log.debug('resolve_sec_uid attempt %d error: %s', attempt+1, e)
            time.sleep(1 + attempt)

    log.warning('Could not resolve sec_uid for @%s after 3 attempts', username)
    return None


# Apivault-inspired: scrape profilo completo (stats, verifica) senza API key, free fallback
def scrape_profile(username, proxy=None):
    """
    Leggero scraper profilo ispirato a tiktok-profile-scraper-python ma senza Apify (requests + UNIVERSAL_DATA).
    Ritorna dict con stats.followers/likes/videos etc per verifica boost.
    """
    sec = resolve_sec_uid(username, proxy=proxy)
    # per ora ritorna solo secUid, ma estendibile per stats
    return {'username': username, 'secUid': sec}


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
