import re
import ssl
import os
import sys
import logging
import tempfile
from re import findall
from io import BytesIO
from time import sleep, time
from base64 import b64decode
from random import choices
from string import ascii_letters, digits
from urllib.parse import unquote, urlparse

import requests
from requests.adapters import HTTPAdapter
from PIL import Image
from colorama import Fore, init

init()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
ZEFOY_URL = 'https://zefoy.com'
API_URL = f'{ZEFOY_URL}/c2VuZF9mb2xsb3dlcnNfdGlrdG9L'

HEADERS = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'accept-language': 'en-US,en;q=0.9',
    'user-agent': USER_AGENT,
}

API_HEADERS = {
    'accept': '*/*',
    'accept-language': 'en-US,en;q=0.9',
    'origin': ZEFOY_URL,
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
        except requests.Timeout:
            if attempt == max_retries:
                log.error('Request timed out after %d retries', max_retries)
                raise
            sleep(2 ** attempt)
        except requests.ConnectionError:
            if attempt == max_retries:
                log.error('Connection failed after %d retries', max_retries)
                raise
            sleep(2 ** attempt)
        except requests.HTTPError as e:
            if attempt == max_retries:
                log.error('HTTP error: %s', e)
                raise
            sleep(2 ** attempt)
        except requests.RequestException as e:
            if attempt == max_retries:
                log.error('Request failed: %s', e)
                raise
            sleep(2 ** attempt)
    raise RuntimeError(f'Failed after {max_retries} retries')


def create_session(proxy=None):
    ctx = create_ssl_context()
    s = requests.Session()
    s.mount('https://', SSLAdapter(ctx))
    s.headers.update(HEADERS)
    if proxy:
        s.proxies = {'http': f'http://{proxy}', 'https': f'http://{proxy}'}
        log.info('Using proxy: %s', proxy)
    return s


def extract_key_from_html(html):
    for pattern in [r'remove-spaces" name="([^"]*)"[^>]*placeholder',
                    r'name="([^"]*)"[^>]*value="([^"]*)"',
                    r'key=(\w+)']:
        for match in findall(pattern, html):
            key = match[0] if isinstance(match, tuple) else match
            if len(key) < 100 and key != 'token':
                return key
    return None


def validate_captcha_page(html):
    if not html:
        log.error('Empty response from homepage')
        return False
    if 'Important Official Zefoy Notice' in html:
        log.warning('Safety notice page')
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
        return True
    if 'captcha' in html.lower() and ('img' in html.lower() or 'input' in html.lower()):
        return True
    log.warning('No captcha form found in page')
    save_debug_html(html, 'no_captcha_form.html')
    return False


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


# ============================================================
# OPTION 1: Selenium (DEFAULT)
# ============================================================

def solve_with_selenium(proxy=None):
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException, NoSuchElementException
    except ImportError:
        log.error('Selenium not installed. Run: pip install selenium')
        log.info('Alternatively, use option 2 (manual cookie)')
        return None, None

    log.info('Launching browser for captcha solving...')
    chrome_options = Options()
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument('--window-size=900,700')
    if proxy:
        chrome_options.add_argument(f'--proxy-server=http://{proxy}')

    try:
        driver = webdriver.Chrome(options=chrome_options)
    except Exception as e:
        log.error('Failed to launch Chrome: %s', e)
        log.info('Make sure Chrome and ChromeDriver are installed')
        return None, None

    try:
        driver.get(ZEFOY_URL)
        log.info('Browser opened. Waiting for captcha...')
        log.info('Solve the captcha in the browser window.')

        try:
            WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="text"], input[type="search"]'))
            )
        except TimeoutException:
            log.warning('Timed out waiting for captcha form, checking page state...')

        input(f'{Fore.YELLOW}Solve the captcha in the browser, then press Enter here...{Fore.RESET}')

        for attempt in range(30):
            html = driver.page_source
            key = extract_key_from_html(html)
            if key:
                log.info('Captcha solved! Key: %s', key)
                session = create_session(proxy)
                for cookie in driver.get_cookies():
                    session.cookies.set(cookie['name'], cookie['value'],
                                        domain=cookie.get('domain', ''))
                driver.quit()
                return session, key
            log.info('Waiting for page to update... (%d/30)', attempt + 1)
            sleep(2)

        log.error('Could not extract key from page after solving captcha')
        log.info('Page title: %s', driver.title)
        save_debug_html(driver.page_source, 'selenium_final.html')
        driver.quit()
        return None, None

    except Exception as e:
        log.error('Selenium error: %s', e)
        try:
            driver.quit()
        except Exception:
            pass
        return None, None


# ============================================================
# OPTION 2: Manual cookie
# ============================================================

def solve_with_cookie(proxy=None):
    print(f"""
{Fore.CYAN}Manual Cookie Method{Fore.RESET}
{Fore.WHITE}1. Open {ZEFOY_URL} in your browser
2. Solve the captcha
3. Open Developer Tools (F12) -> Application -> Cookies
4. Copy the PHPSESSID value{Fore.RESET}
""")
    phpsessid = input('Paste PHPSESSID: ').strip()
    if not phpsessid:
        log.error('No PHPSESSID provided')
        return None, None

    session = create_session(proxy)
    session.cookies.set('PHPSESSID', phpsessid, domain='zefoy.com')

    log.info('Verifying session...')
    try:
        resp = http_request(session, 'GET', ZEFOY_URL)
        html = resp.text
        key = extract_key_from_html(html)
        if key:
            log.info('Session valid! Key: %s', key)
            return session, key
        if 'captcha' in html.lower():
            log.warning('Session exists but captcha not solved yet')
            log.info('Try solving the captcha in the browser and paste a new PHPSESSID')
        else:
            log.warning('Could not verify session')
        save_debug_html(html, 'cookie_verify.html')
        return None, None
    except requests.RequestException as e:
        log.error('Failed to verify session: %s', e)
        return None, None


# ============================================================
# Shared logic
# ============================================================

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
    headers = {**API_HEADERS, 'content-type': f'multipart/form-data; boundary={boundary}'}
    try:
        resp = http_request(session, 'POST', API_URL, data=body.encode(), headers=headers)
    except requests.RequestException as e:
        log.error('send_action failed: %s', e)
        return False
    try:
        resp_text = decode(resp.text)
    except (binascii.Error, UnicodeDecodeError) as e:
        log.error('Failed to decode response: %s', e)
        return False
    if 'Session expired' in resp_text:
        raise RuntimeError('Session expired')
    return 'views sent' in resp_text.lower()


def search_link(session, key, tiktok_url):
    body, boundary = build_multipart(key, tiktok_url)
    headers = {**API_HEADERS, 'content-type': f'multipart/form-data; boundary={boundary}'}
    try:
        resp = http_request(session, 'POST', API_URL, data=body.encode(), headers=headers)
    except requests.RequestException as e:
        log.error('search_link failed: %s', e)
        return None
    try:
        resp_text = decode(resp.text)
    except (binascii.Error, UnicodeDecodeError) as e:
        log.error('Failed to decode response: %s', e)
        return None

    if "onsubmit=\"showHideElements('.w1r','.w2r')" in resp_text:
        matches = findall(r'name="([^"]*)"\s+value="([^"]*)"\s+hidden', resp_text)
        if not matches:
            log.error('Could not extract token/aweme_id')
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


# ============================================================
# Main
# ============================================================

def main():
    print(f'{Fore.CYAN}╔══════════════════════════════════════╗')
    print(f'{Fore.CYAN}║        Zefoy ViewBot v4              ║')
    print(f'{Fore.CYAN}║  Selenium (default) + Cookie mode    ║')
    print(f'{Fore.CYAN}╚══════════════════════════════════════╝')
    print()

    tiktok_url = input('TikTok URL: ').strip()
    if not tiktok_url:
        log.error('No URL provided')
        return
    if not validate_tiktok_url(tiktok_url):
        log.error('Invalid TikTok URL (must be from vm.tiktok.com, tiktok.com, or vt.tiktok.com)')
        return

    print(f"""
{Fore.WHITE}Captcha solving method:
  {Fore.CYAN}[1]{Fore.WHITE} Selenium (default) - opens Chrome, solve captcha there
  {Fore.CYAN}[2]{Fore.WHITE} Manual cookie      - paste PHPSESSID from browser{Fore.RESET}
""")
    method = input(f'Choose method [1]: ').strip() or '1'
    proxy = input('Proxy (optional, format: ip:port or press Enter): ').strip() or None

    log.info('Starting Zefoy bot...')

    if method == '2':
        session, key = solve_with_cookie(proxy)
    else:
        session, key = solve_with_selenium(proxy)

    if not key:
        log.error('Failed to get session key')
        log.info('Check ./debug/ folder for saved HTML responses')
        return

    log.info('Fetching service list...')
    try:
        resp = http_request(session, 'GET', ZEFOY_URL)
        html = resp.text
    except requests.RequestException as e:
        log.error('Failed to fetch services: %s', e)
        return

    service = choose_service(html)
    if not service:
        return

    log.info('Selected: %s', SERVICES[service]['name'])
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
                log.debug('Waiting... (cycle %d/%d)', cycle, MAX_CYCLES)
        except RuntimeError as e:
            if 'Session expired' in str(e):
                log.warning('Session expired, re-solving captcha...')
                if method == '2':
                    session, key = solve_with_cookie(proxy)
                else:
                    session, key = solve_with_selenium(proxy)
                if not key:
                    log.error('Reconnect failed')
                    break
                errors = 0
                continue
            log.error('Fatal error: %s', e)
            break
        except Exception as e:
            errors += 1
            log.error('Error at cycle %d: %s', cycle, e)
            if errors >= MAX_ERRORS:
                log.error('Too many errors, re-solving captcha...')
                if method == '2':
                    session, key = solve_with_cookie(proxy)
                else:
                    session, key = solve_with_selenium(proxy)
                if not key:
                    break
                errors = 0
                continue
        sleep(5)

    log.info('Done. Total sent: %d', count)


if __name__ == '__main__':
    main()
