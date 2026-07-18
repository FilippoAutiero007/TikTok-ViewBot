import re
import ssl
import os
import logging
import tempfile
from re import findall
from io import BytesIO
from time import sleep, time
from base64 import b64decode
from random import choices, sample
from string import ascii_letters, digits
from urllib.parse import unquote, urlparse, urlencode

import requests
from requests.adapters import HTTPAdapter
from PIL import Image
from colorama import Fore, init

init()

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
ZEFOY_URL = 'https://zefoy.com'
API_URL = f'{ZEFOY_URL}/c2VuZF9mb2xsb3dlcnNfdGlrdG9L'

HEADERS = {
    'authority': 'zefoy.com',
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'accept-language': 'en-US,en;q=0.9',
    'cache-control': 'max-age=0',
    'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'sec-fetch-dest': 'document',
    'sec-fetch-mode': 'navigate',
    'sec-fetch-site': 'none',
    'sec-fetch-user': '?1',
    'upgrade-insecure-requests': '1',
    'user-agent': USER_AGENT,
}

API_HEADERS = {
    'authority': 'zefoy.com',
    'accept': '*/*',
    'accept-language': 'en-US,en;q=0.9',
    'origin': ZEFOY_URL,
    'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': USER_AGENT,
    'x-requested-with': 'XMLHttpRequest',
}

SERVICES = {
    '1': {'name': 'Followers',   'selector': 't-followers-button'},
    '2': {'name': 'Hearts',      'selector': 't-hearts-button'},
    '3': {'name': 'Comments',    'selector': 't-chearts-button'},
    '4': {'name': 'Views',       'selector': 't-views-button'},
    '5': {'name': 'Shares',      'selector': 't-shares-button'},
    '6': {'name': 'Favorites',   'selector': 't-favorites-button'},
    '7': {'name': 'Live Stream', 'selector': 't-livesteam-button'},
}

MAX_CYCLES = 200
MAX_ERRORS = 10
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
CAPTCHA_MAX_ATTEMPTS = 5
DEBUG_DIR = 'debug'


class SSLAdapter(HTTPAdapter):
    def __init__(self, ssl_context, **kwargs):
        self.ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs['ssl_context'] = self.ssl_context
        super().init_poolmanager(*args, **kwargs)


def create_ssl_context():
    ctx = ssl.create_default_context()
    ciphers = (
        'ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:'
        'ECDHE+AES256:ECDHE+AES128:DHE+AES256:DHE+AES128:'
        'RSA+AESGCM:RSA+AES:!aNULL:!eNULL:!MD5:!DSS:!RC4'
    )
    ctx.set_ciphers(ciphers)
    return ctx


def parse_cookies(cookie_str):
    cookies = {}
    if not cookie_str:
        return cookies
    for item in cookie_str.split(';'):
        parts = item.strip().split('=')
        if len(parts) == 2:
            key, value = parts[0].strip(), parts[1].strip()
            if value:
                cookies[key] = value
    return cookies


def parse_set_cookie_headers(set_cookie_headers):
    cookies = {}
    if not set_cookie_headers:
        return cookies
    for cookie_header in set_cookie_headers.split(', '):
        parts = cookie_header.split(';')
        if parts:
            kv = parts[0].split('=')
            if len(kv) == 2:
                key, value = kv[0].strip(), kv[1].strip()
                if value:
                    cookies[key] = value
    return cookies


def decode(text):
    return b64decode(unquote(text[::-1])).decode()


def save_debug_html(html, filename='response.html'):
    os.makedirs(DEBUG_DIR, exist_ok=True)
    path = os.path.join(DEBUG_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    log.debug('Saved HTML to %s (%d chars)', path, len(html))


def validate_tiktok_url(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        if parsed.hostname not in ('vm.tiktok.com', 'tiktok.com', 'www.tiktok.com', 'vt.tiktok.com'):
            return False
        return bool(parsed.path or parsed.query)
    except (ValueError, AttributeError):
        return False


def http_request(session, method, url, max_retries=MAX_RETRIES, **kwargs):
    kwargs.setdefault('timeout', REQUEST_TIMEOUT)
    for attempt in range(max_retries + 1):
        try:
            resp = session.request(method, url, **kwargs)
            if resp.status_code == 429:
                delay = 2 ** attempt
                log.warning('Rate limited, waiting %ds...', delay)
                sleep(delay)
                continue
            if resp.status_code >= 500:
                delay = 2 ** attempt
                log.warning('Server error %d, waiting %ds...', resp.status_code, delay)
                sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except requests.Timeout as e:
            if attempt == max_retries:
                log.error('Request timed out after %d retries', max_retries)
                raise
            delay = 2 ** attempt
            log.warning('Timeout on attempt %d, retrying in %ds...', attempt + 1, delay)
            sleep(delay)
        except requests.ConnectionError as e:
            if attempt == max_retries:
                log.error('Connection failed after %d retries', max_retries)
                raise
            delay = 2 ** attempt
            log.warning('Connection error on attempt %d, retrying in %ds...', attempt + 1, delay)
            sleep(delay)
        except requests.HTTPError as e:
            if attempt == max_retries:
                log.error('HTTP error after %d retries: %s', max_retries, e)
                raise
            delay = 2 ** attempt
            log.warning('HTTP error on attempt %d: %s, retrying in %ds...', attempt + 1, e, delay)
            sleep(delay)
        except requests.RequestException as e:
            if attempt == max_retries:
                log.error('Request failed after %d retries: %s', max_retries, e)
                raise
            delay = 2 ** attempt
            log.warning('Request error on attempt %d: %s, retrying in %ds...', attempt + 1, e, delay)
            sleep(delay)
    raise RuntimeError(f'Failed after {max_retries} retries')


def create_session(proxy=None):
    ctx = create_ssl_context()
    s = requests.Session()
    s.mount('https://', SSLAdapter(ctx))
    s.headers.update(HEADERS)
    if proxy:
        s.proxies = {
            'http': f'http://{proxy}',
            'https': f'http://{proxy}',
        }
        log.info('Using proxy: %s', proxy)
    return s


def is_safety_notice_page(html):
    return 'Important Official Zefoy Notice' in html or 'Official Zefoy Safety Information' in html


def is_cloudflare_challenge(html):
    return 'Cloudflare' in html and ('challenge' in html.lower() or 'Checking' in html)


def is_blocked_page(html):
    if '502 Bad Gateway' in html:
        return True, '502 Bad Gateway - site may be blocked in your region'
    if '403 Forbidden' in html:
        return True, '403 Forbidden - access denied'
    if is_cloudflare_challenge(html):
        return True, 'Cloudflare challenge detected'
    if is_safety_notice_page(html):
        return True, 'Safety notice page - click required'
    return False, None


def handle_safety_notice(session, html):
    log.info('Detected safety notice page, looking for continue button...')

    btn_patterns = [
        r'<button[^>]*>.*?continue.*?</button>',
        r'<a[^>]*>.*?continue.*?</a>',
        r'<button[^>]*>.*?proceed.*?</button>',
        r'<button[^>]*>.*?enter.*?</button>',
        r'<input[^>]*type="submit"[^>]*>',
        r'<button[^>]*type="submit"[^>]*>',
    ]

    for pattern in btn_patterns:
        matches = findall(pattern, html, re.IGNORECASE | re.DOTALL)
        if matches:
            log.info('Found button: %s', matches[0][:100])

    redirect_match = findall(r'window\.location\.href\s*=\s*["\']([^"\']+)["\']', html)
    if redirect_match:
        log.info('Found redirect URL: %s', redirect_match[0])
        try:
            resp = http_request(session, 'GET', redirect_match[0])
            return resp.text
        except requests.RequestException:
            pass

    meta_refresh = findall(r'<meta[^>]*http-equiv="refresh"[^>]*content="[^"]*url=([^"]*)"', html, re.IGNORECASE)
    if meta_refresh:
        log.info('Found meta refresh URL: %s', meta_refresh[0])
        try:
            resp = http_request(session, 'GET', meta_refresh[0])
            return resp.text
        except requests.RequestException:
            pass

    log.warning('No continue button found. Try clicking manually in browser or use Selenium.')
    log.info('Saving HTML for manual inspection...')
    save_debug_html(html, 'safety_notice.html')
    return html


def fetch_homepage(session):
    for attempt in range(CAPTCHA_MAX_ATTEMPTS):
        log.info('Fetching Zefoy homepage (attempt %d/%d)...', attempt + 1, CAPTCHA_MAX_ATTEMPTS)
        try:
            resp = http_request(session, 'GET', ZEFOY_URL)
            html = resp.text.replace('&amp;', '&')
            save_debug_html(html, f'homepage_{attempt}.html')

            blocked, reason = is_blocked_page(html)
            if blocked:
                if is_safety_notice_page(html):
                    log.info('Safety notice detected, attempting to bypass...')
                    html = handle_safety_notice(session, html)
                    if not is_safety_notice_page(html):
                        return html
                    log.warning('Could not bypass safety notice')
                elif is_cloudflare_challenge(html):
                    log.warning('%s, waiting 5s and retrying...', reason)
                    sleep(5)
                else:
                    log.warning('%s, retrying...', reason)
                    sleep(10)
                continue

            if len(html) < 100:
                log.warning('Response too short (%d chars), retrying...', len(html))
                sleep(3)
                continue

            return html
        except requests.RequestException as e:
            log.warning('Failed to fetch homepage: %s, retrying...', e)
            sleep(5)

    return None


def parse_captcha_fields(html):
    text_inputs = []
    hidden_fields = []
    captcha_img = None

    for pattern in [
        r'<input[^>]*type="search"[^>]*name="([^"]*)"[^>]*>',
        r'<input[^>]*name="([^"]*)"[^>]*type="search"[^>]*>',
        r'<input[^>]*type="text"[^>]*name="([^"]*)"[^>]*value="([^"]*)"[^>]*>',
        r'type="text"[^>]*name="([^"]*)"[^>]*value="([^"]*)"',
        r'type="text" maxlength="(?:30|50)" name="([^"]*)"',
        r'name="([^"]*)"[^>]*placeholder="([^"]*)"',
    ]:
        text_inputs = findall(pattern, html)
        if text_inputs:
            break

    for pattern in [
        r'<input[^>]*type="hidden"[^>]*name="([^"]*)"[^>]*value="([^"]*)"[^>]*>',
        r'<input[^>]*name="captchaencoded"[^>]*value="([^"]*)"',
        r'name="([^"]*)"[^>]*value="([^"]*)"[^>]*hidden',
    ]:
        found = findall(pattern, html)
        if found:
            hidden_fields = found
            break

    img_patterns = [
        r'<img[^>]*id="captcha-img"[^>]*src="([^"]*)"',
        r'id="captcha-img"[^>]*src="([^"]*)"',
        r'<img[^>]*src="([^"]*)"[^>]*id="captcha-img"',
        r'<img[^>]*src="([^"]*)"[^>]*captcha',
        r'<img[^>]*captcha[^>]*src="([^"]*)"',
    ]
    for pattern in img_patterns:
        matches = findall(pattern, html, re.IGNORECASE)
        for img in matches:
            if img and img.strip():
                captcha_img = img
                break
        if captcha_img:
            break

    if not captcha_img:
        for img in findall(r'<img[^>]*src="([^"]*)"[^>]*>', html):
            if img and ('captcha' in img.lower() or img.endswith('.png')):
                captcha_img = img
                break

    if not captcha_img:
        for img in findall(r'<img[^>]*src="([^"]*)"[^>]*>', html):
            if img and img.strip():
                captcha_img = img
                break

    return text_inputs, hidden_fields, captcha_img


def validate_captcha_page(html):
    if not html:
        log.error('Empty response from homepage')
        return False
    if is_safety_notice_page(html):
        log.warning('Still on safety notice page')
        return False
    has_captcha_input = bool(
        findall(r'name="captchalogin"', html, re.IGNORECASE) or
        findall(r'type="search"[^>]*name="([^"]*)"', html) or
        findall(r'type="text"[^>]*maxlength="(?:30|50)"', html)
    )
    has_captcha_img = bool(
        findall(r'id="captcha-img"', html, re.IGNORECASE) or
        findall(r'<img[^>]*captcha', html, re.IGNORECASE)
    )
    has_hidden_field = bool(
        findall(r'name="captchaencoded"', html, re.IGNORECASE) or
        findall(r'type="hidden"[^>]*name="([^"]*)"[^>]*value="([^"]*)"', html)
    )
    if has_captcha_input or (has_captcha_img and has_hidden_field):
        log.info('Captcha page detected (input=%s, img=%s, hidden=%s)',
                 has_captcha_input, has_captcha_img, has_hidden_field)
        return True
    if 'captcha' in html.lower() and ('img' in html.lower() or 'input' in html.lower()):
        log.info('Found captcha elements (fallback check), proceeding')
        return True
    log.warning('No captcha form found in page')
    save_debug_html(html, 'no_captcha_form.html')
    return False


def solve_captcha(proxy=None):
    session = create_session(proxy)
    html = fetch_homepage(session)
    if not html:
        log.error('Failed to fetch homepage after %d attempts', CAPTCHA_MAX_ATTEMPTS)
        return None, None

    if not validate_captcha_page(html):
        return None, None

    text_inputs, hidden_fields, captcha_img = parse_captcha_fields(html)
    if not text_inputs:
        log.error('No captcha input field found')
        save_debug_html(html, 'no_captcha_input.html')
        return None, None
    if not captcha_img or not captcha_img.strip():
        log.warning('Captcha image has empty src - likely JavaScript-loaded')
        log.info('Trying to find image URL from JavaScript...')
        js_patterns = [
            r'captcha-img["\']?\s*\.src\s*=\s*["\']([^"\']+)["\']',
            r'src\s*[:=]\s*["\']([^"\']*captcha[^"\']*)["\']',
            r'captcha.*?url\s*[:=]\s*["\']([^"\']+)["\']',
        ]
        for pattern in js_patterns:
            matches = findall(pattern, html, re.IGNORECASE)
            if matches:
                captcha_img = matches[0]
                log.info('Found captcha URL in JS: %s', captcha_img)
                break
        if not captcha_img or not captcha_img.strip():
            log.error('Cannot find captcha image URL (JavaScript-loaded, need Selenium)')
            log.info('Tip: The captcha image is loaded by JavaScript.')
            log.info('Try opening zefoy.com in a browser first, then paste the session cookie.')
            save_debug_html(html, 'js_captcha.html')
            return None, None

    field = 'captchalogin'
    for inp in text_inputs:
        name = inp[0] if isinstance(inp, tuple) else inp
        if name:
            field = name
            break
    log.info('Captcha field: %s', field)

    if captcha_img.startswith('http'):
        captcha_url = captcha_img
    else:
        captcha_url = f'{ZEFOY_URL}/{captcha_img.lstrip("/")}'

    log.info('Downloading captcha image...')
    try:
        img_resp = http_request(session, 'GET', captcha_url)
        try:
            image = Image.open(BytesIO(img_resp.content))
            image.verify()
        except (IOError, SyntaxError) as e:
            log.error('Invalid captcha image: %s', e)
            return None, None

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False, dir='.') as tmp:
            tmp.write(img_resp.content)
            captcha_path = tmp.name

        log.info('Saved captcha to %s', captcha_path)
        try:
            Image.open(captcha_path).show()
        except Exception:
            log.warning('Open %s manually to view', captcha_path)
    except requests.RequestException as e:
        log.error('Failed to download captcha: %s', e)
        return None, None
    except (binascii.Error, UnicodeDecodeError) as e:
        log.error('Failed to decode captcha data: %s', e)
        return None, None

    log.info('Solve the captcha and enter the answer:')
    answer = input('> ').strip()
    if not answer:
        log.error('No answer provided')
        return None, None

    log.info('Submitting captcha...')
    data = {field: answer}
    for item in hidden_fields:
        if isinstance(item, tuple):
            if len(item) == 2:
                name, value = item
                if name and value:
                    data[name] = value
            elif len(item) == 1:
                data['captchaencoded'] = item[0]
        elif isinstance(item, str):
            data['captchaencoded'] = item
    data['token'] = ''

    session.headers.update({
        'Content-Type': 'application/x-www-form-urlencoded',
        'origin': ZEFOY_URL,
        'referer': ZEFOY_URL,
    })
    resp = http_request(session, 'POST', ZEFOY_URL, data=data)
    save_debug_html(resp.text, 'captcha_response.html')

    if 'captcha' in resp.text.lower() and 'Enter the word' in resp.text:
        log.warning('Captcha submission failed - incorrect answer')
        return None, None

    for pattern in [r'remove-spaces" name="([^"]*)"[^>]*placeholder',
                    r'name="([^"]*)"[^>]*value="([^"]*)"',
                    r'key=(\w+)']:
        for match in findall(pattern, resp.text):
            key = match[0] if isinstance(match, tuple) else match
            if len(key) < 100 and key != 'token':
                log.info('Captcha solved! Key: %s', key)
                return session, key

    log.error('Could not extract key from response')
    return None, None


def check_service_status(html, selector):
    pattern = rf'class="[^"]*\b{re.escape(selector)}\b[^"]*"'
    match = findall(pattern, html)
    if not match:
        return False
    return 'disabled' not in match[0].lower()


def show_services(html):
    log.info('Available services:')
    available = []
    for num, svc in SERVICES.items():
        status = check_service_status(html, svc['selector'])
        icon = f'{Fore.GREEN}ON{Fore.RESET}' if status else f'{Fore.RED}OFF{Fore.RESET}'
        print(f'  [{num}] {svc["name"]:<12} {icon}')
        if status:
            available.append(num)
    return available


def choose_service(html):
    available = show_services(html)
    if not available:
        log.error('No services available right now')
        return None

    while True:
        choice = input(f'Choose service {available}: ').strip()
        if choice in available:
            return choice
        log.warning('Invalid choice. Available: %s', available)


def parse_timer(html):
    match = findall(r'ltm=(\d+);', html)
    if match:
        return int(match[0])

    match = findall(r'Please wait.*?(\d+)\s*(?:min|minute).*?(\d+)\s*(?:sec|second)', html, re.IGNORECASE)
    if match:
        return int(match[0][0]) * 60 + int(match[0][1])

    match = findall(r'Please wait\s+(\d+)', html)
    if match:
        return int(match[0])

    return 0


def wait_timer(seconds):
    if seconds <= 0:
        return
    end_time = time() + seconds
    while time() < end_time:
        remaining = round(end_time - time())
        mins, secs = divmod(remaining, 60)
        label = f'{mins}m {secs:02d}s' if mins else f'{secs}s'
        print(f'\r  Waiting {label}...  ', end='', flush=True)
        sleep(1)
    print('\r' + ' ' * 40, end='', flush=True)


def build_multipart(key, value):
    token = ''.join(choices(ascii_letters + digits, k=16))
    boundary = f'----WebKitFormBoundary{token}'
    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
        f'{value}\r\n'
        f'--{boundary}--\r\n'
    )
    return body, boundary


def send_action(session, key, aweme_id):
    body, boundary = build_multipart(key, aweme_id)
    headers = {
        **API_HEADERS,
        'content-type': f'multipart/form-data; boundary={boundary}',
    }
    try:
        resp = http_request(session, 'POST', API_URL, data=body.encode(),
                            headers=headers)
    except requests.RequestException as e:
        log.error('send_action request failed: %s', e)
        return False

    try:
        resp_text = decode(resp.text)
    except (binascii.Error, UnicodeDecodeError) as e:
        log.error('Failed to decode send_action response: %s', e)
        return False

    log.debug('send_action response: %s', resp_text[:200])

    if 'Session expired' in resp_text:
        raise RuntimeError('Session expired')
    if 'views sent' in resp_text.lower():
        return True
    return False


def search_link(session, key, tiktok_url):
    body, boundary = build_multipart(key, tiktok_url)
    headers = {
        **API_HEADERS,
        'content-type': f'multipart/form-data; boundary={boundary}',
    }
    try:
        resp = http_request(session, 'POST', API_URL, data=body.encode(),
                            headers=headers)
    except requests.RequestException as e:
        log.error('search_link request failed: %s', e)
        return None

    try:
        resp_text = decode(resp.text)
    except (binascii.Error, UnicodeDecodeError) as e:
        log.error('Failed to decode search_link response: %s', e)
        return None

    log.debug('search_link response: %s', resp_text[:200])

    if "onsubmit=\"showHideElements('.w1r','.w2r')" in resp_text:
        matches = findall(r'name="([^"]*)"\s+value="([^"]*)"\s+hidden', resp_text)
        if not matches:
            log.error('Could not extract token/aweme_id from response')
            return None
        token, aweme_id = matches[0]
        log.info('Sending to: %s', aweme_id)
        sleep(3)
        return send_action(session, token, aweme_id)
    else:
        timer = parse_timer(resp_text)
        if timer > 0:
            wait_timer(timer)
        return None


def reconnect_session(old_session, proxy=None):
    log.warning('Attempting to reconnect...')
    sleep(5)
    new_session, key = solve_captcha(proxy)
    return new_session, key


def main():
    print(f'{Fore.CYAN}╔══════════════════════════════════╗')
    print(f'{Fore.CYAN}║       Zefoy ViewBot v3           ║')
    print(f'{Fore.CYAN}║  debug HTML saved to ./debug/    ║')
    print(f'{Fore.CYAN}║  with SSL + proxy support        ║')
    print(f'{Fore.CYAN}╚══════════════════════════════════╝')
    print()

    tiktok_url = input('TikTok URL: ').strip()
    if not tiktok_url:
        log.error('No URL provided')
        return

    if not validate_tiktok_url(tiktok_url):
        log.error('Invalid TikTok URL (must be from vm.tiktok.com, tiktok.com, or vt.tiktok.com)')
        return

    proxy_input = input(f'Proxy (optional, format: ip:port:user:pass or press Enter): ').strip()
    proxy = proxy_input if proxy_input else None

    log.info('Starting Zefoy bot...')
    session, key = solve_captcha(proxy)

    if not key:
        log.error('Failed to solve captcha')
        log.info('Check ./debug/ folder for saved HTML responses')
        return

    log.info('Captcha solved! Fetching service list...')
    try:
        resp = http_request(session, 'GET', ZEFOY_URL)
        html = resp.text
    except requests.RequestException as e:
        log.error('Failed to fetch services page: %s', e)
        return

    service = choose_service(html)
    if not service:
        return

    svc_name = SERVICES[service]['name']
    log.info('Selected: %s', svc_name)

    log.info('Starting send loop...')
    count = 0
    errors = 0
    for cycle in range(1, MAX_CYCLES + 1):
        try:
            result = search_link(session, key, tiktok_url)
            if result:
                count += 1
                log.info('Sent #%d (cycle %d/%d)', count, cycle, MAX_CYCLES)
                errors = 0
            else:
                log.debug('Waiting for next cycle... (cycle %d/%d)', cycle, MAX_CYCLES)
        except RuntimeError as e:
            if 'Session expired' in str(e):
                log.warning('Session expired, reconnecting...')
                session, key = reconnect_session(session, proxy)
                if not key:
                    log.error('Reconnect failed, stopping')
                    break
                log.info('Reconnected! Key: %s', key)
                errors = 0
                continue
            log.error('Fatal error at cycle %d: %s', cycle, e)
            break
        except Exception as e:
            errors += 1
            log.error('Error at cycle %d/%d: %s', cycle, MAX_CYCLES, e)
            if errors >= MAX_ERRORS:
                log.error('Too many consecutive errors (%d), attempting reconnect...', errors)
                session, key = reconnect_session(session, proxy)
                if not key:
                    log.error('Reconnect failed, stopping')
                    break
                errors = 0
                continue
        sleep(5)

    log.info('Done. Total sent: %d', count)


if __name__ == '__main__':
    main()
