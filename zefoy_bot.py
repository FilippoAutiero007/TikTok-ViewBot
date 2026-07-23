import re
import ssl
import os
import sys
import logging
import tempfile
import binascii
import csv
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from time import sleep, time
from base64 import b64decode
from random import choices, shuffle
from string import ascii_letters, digits
from urllib.parse import unquote, urlparse
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from colorama import Fore, init

try:
    import chromedriver_autoinstaller
    chromedriver_autoinstaller.install()
except ImportError:
    pass

try:
    import pyfiglet
    HAS_PYFIGLET = True
except ImportError:
    HAS_PYFIGLET = False

init()

LOG_FILE = 'logs/bot_log.txt'

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8'),
    ],
)
log = logging.getLogger(__name__)


def clear_terminal():
    os.system('cls' if os.name == 'nt' else 'clear')


def set_window_title(title):
    if os.name == 'nt':
        os.system(f'title {title}')
    else:
        sys.stdout.write(f'\033]0;{title}\007')
        sys.stdout.flush()


def format_number(n):
    return format(n, ',d').replace(',', '.')

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
    '1': {'name': 'Followers',   'selector': 't-followers-button', 'menu': 't-followers-menu'},
    '2': {'name': 'Hearts',      'selector': 't-hearts-button',    'menu': 't-hearts-menu'},
    '3': {'name': 'Comments',    'selector': 't-chearts-button',   'menu': 't-chearts-menu'},
    '4': {'name': 'Views',       'selector': 't-views-button',     'menu': 't-views-menu'},
    '5': {'name': 'Shares',      'selector': 't-shares-button',    'menu': 't-shares-menu'},
    '6': {'name': 'Favorites',   'selector': 't-favorites-button', 'menu': 't-favorites-menu'},
    '7': {'name': 'Live Stream', 'selector': 't-livestream-button','menu': 't-livestream-menu'},
    '8': {'name': 'Repost',      'selector': 't-repost-button',    'menu': 't-repost-menu'},
}

MAX_CYCLES = 200
MAX_ERRORS = 10
REQUEST_TIMEOUT = 30
MAX_RETRIES = 5
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
    if not text:
        raise ValueError('Empty text for decode')
    try:
        return b64decode(unquote(text[::-1])).decode()
    except Exception as e:
        raise ValueError(f'Decode failed: {e}')


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
                delay = min(30, 5 * (2 ** attempt))
                log.warning('Rate limited (429), waiting %ds... (attempt %d/%d)', delay, attempt + 1, max_retries + 1)
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
        if not proxy.startswith(('http://', 'https://', 'socks5://', 'socks4://')):
            proxy = f'http://{proxy}'
        s.proxies = {'http': proxy, 'https': proxy}
        log.info('Using proxy: %s', proxy)
    return s


def extract_key_from_html(html):
    for pattern in [r'remove-spaces" name="([^"]*)"[^>]*placeholder',
                    r'name="([^"]*)"[^>]*value="([^"]*)"',
                    r'key=(\w+)']:
        for match in re.findall(pattern, html):
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
        re.findall(r'name="captchalogin"', html, re.IGNORECASE) or
        re.findall(r'type="search"[^>]*name="([^"]*)"', html) or
        re.findall(r'type="text"[^>]*maxlength="(?:30|50)"', html)
    )
    has_captcha_img = bool(
        re.findall(r'id="captcha-img"', html, re.IGNORECASE) or
        re.findall(r'<img[^>]*captcha', html, re.IGNORECASE)
    )
    has_hidden_field = bool(
        re.findall(r'name="captchaencoded"', html, re.IGNORECASE) or
        re.findall(r'type="hidden"[^>]*name="([^"]*)"[^>]*value="([^"]*)"', html)
    )
    if has_captcha_input or (has_captcha_img and has_hidden_field):
        return True
    if 'captcha' in html.lower() and ('img' in html.lower() or 'input' in html.lower()):
        if re.search(r'<(?:input|img)[^>]*(?:type|src)="[^"]*captcha', html, re.IGNORECASE):
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
        text_inputs = re.findall(pattern, html)
        if text_inputs:
            break

    for pattern in [
        r'<input[^>]*type="hidden"[^>]*name="([^"]*)"[^>]*value="([^"]*)"[^>]*>',
        r'<input[^>]*name="captchaencoded"[^>]*value="([^"]*)"',
        r'name="([^"]*)"[^>]*value="([^"]*)"[^>]*hidden',
    ]:
        found = re.findall(pattern, html)
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
        matches = re.findall(pattern, html, re.IGNORECASE)
        for img in matches:
            if img and img.strip():
                captcha_img = img
                break
        if captcha_img:
            break

    if not captcha_img:
        for img in re.findall(r'<img[^>]*src="([^"]*)"[^>]*>', html):
            if img and ('captcha' in img.lower() or img.endswith('.png')):
                captcha_img = img
                break

    if not captcha_img:
        for img in re.findall(r'<img[^>]*src="([^"]*)"[^>]*>', html):
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
        from selenium.webdriver.common.alert import Alert
        from selenium.common.exceptions import TimeoutException, NoSuchElementException, NoAlertPresentException
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
    chrome_options.add_argument('--disable-notifications')
    chrome_options.add_argument('--no-first-run')
    chrome_options.add_argument('--disable-popup-blocking')
    chrome_options.add_argument('--disable-infobars')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_experimental_option('prefs', {
        'profile.default_content_setting_values.notifications': 2,
    })
    if proxy:
        if not proxy.startswith(('http://', 'https://', 'socks5://', 'socks4://')):
            proxy = f'http://{proxy}'
        chrome_options.add_argument(f'--proxy-server={proxy}')

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
            Alert(driver).dismiss()
        except Exception:
            pass

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
                    session.cookies.set(
                        cookie['name'], cookie['value'],
                        domain=cookie.get('domain', ''),
                        path=cookie.get('path', '/'),
                        secure=cookie.get('secure', False),
                        expiry=cookie.get('expiry', None)
                    )
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
        alert_text = ''
        try:
            alert = Alert(driver)
            alert_text = alert.text
            alert.dismiss()
        except Exception:
            pass
        if alert_text:
            log.error('Selenium error (dismissed alert: "%s"): %s', alert_text, e)
        else:
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
        save_debug_html(html, 'cookie_verify.html')
        key = extract_key_from_html(html)
        if key:
            log.info('Session valid! Key: %s', key)
            return session, key
        if 'captcha' in html.lower():
            log.warning('Session exists but captcha not solved yet')
            log.info('Try solving the captcha in the browser and paste a new PHPSESSID')
        else:
            log.warning('Could not verify session')
        return None, None
    except requests.RequestException as e:
        log.error('Failed to verify session: %s', e)
        return None, None


# ============================================================
# Shared logic
# ============================================================

def check_service_status(html, selector):
    btn_pattern = rf'<button[^>]*class="[^"]*\b{re.escape(selector)}\b[^"]*"[^>]*>'
    btn_match = re.findall(btn_pattern, html, re.IGNORECASE)
    if not btn_match:
        btn_pattern2 = rf'<[^>]*class="[^"]*\b{re.escape(selector)}\b[^"]*"[^>]*>'
        btn_match = re.findall(btn_pattern2, html, re.IGNORECASE)

    if btn_match:
        tag = btn_match[0].lower()
        if 'disabled' in tag:
            return False
        if 'class="' in tag:
            class_part = re.search(r'class="([^"]*)"', btn_match[0], re.IGNORECASE)
            if class_part and ('off' in class_part.group(1).lower() or 'inactive' in class_part.group(1).lower()):
                return False

    menu_selector = selector.replace('-button', '-menu')
    menu_pattern = rf'<div[^>]*class="[^"]*\b{re.escape(menu_selector)}\b[^"]*"[^>]*>.*?</div>'
    menu_match = re.findall(menu_pattern, html, re.IGNORECASE | re.DOTALL)
    if menu_match:
        menu_html = menu_match[0]
        if '<form' in menu_html.lower() and 'input' in menu_html.lower():
            return True
        if 'disabled' in menu_html.lower():
            return False

    if btn_match:
        return True

    return False


def extract_service_form(html, menu_selector):
    menu_pattern = rf'<div[^>]*class="[^"]*\b{re.escape(menu_selector)}\b[^"]*"[^>]*>(.*?)</div>'
    menu_match = re.findall(menu_pattern, html, re.IGNORECASE | re.DOTALL)
    if not menu_match:
        return None, None

    menu_html = menu_match[0]

    action_pattern = r'action="([^"]*)"'
    action_match = re.findall(action_pattern, menu_html)
    if action_match:
        action_url = f'{ZEFOY_URL}/{action_match[0]}'
    else:
        action_url = None

    name_pattern = r'name="([^"]*)"'
    name_match = re.findall(name_pattern, menu_html)
    field_name = None
    for name in name_match:
        if name and len(name) > 5 and name != 'token':
            field_name = name
            break

    return action_url, field_name


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
        save_debug_html(html, 'services_all_off.html')
        log.info('Debug HTML saved to ./debug/services_all_off.html')
        return None, None, None
    while True:
        choice = input(f'Choose service {available}: ').strip()
        if choice in available:
            svc = SERVICES[choice]
            api_url, field_name = extract_service_form(html, svc['menu'])
            if not api_url or not field_name:
                log.warning('Could not extract form for %s, using default API URL', svc['name'])
                api_url = API_URL
                field_name = None
            else:
                log.info('Service form: url=%s field=%s', api_url, field_name)
            return choice, api_url, field_name
        log.warning('Invalid choice. Available: %s', available)


def parse_timer(html):
    match = re.findall(r'ltm=(\d+);', html)
    if match:
        return int(match[0])
    match = re.findall(r'Please wait.*?(\d+)\s*(?:min|minute).*?(\d+)\s*(?:sec|second)', html, re.IGNORECASE)
    if match:
        return int(match[0][0]) * 60 + int(match[0][1])
    match = re.findall(r'Please wait\s+(\d+)', html)
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


def send_action(session, key, aweme_id, api_url):
    body, boundary = build_multipart(key, aweme_id)
    headers = {**API_HEADERS, 'content-type': f'multipart/form-data; boundary={boundary}'}
    log.debug('send_action POST to %s field=%s value=%s', api_url, key, aweme_id)
    try:
        resp = http_request(session, 'POST', api_url, data=body.encode(), headers=headers, allow_redirects=False)
    except requests.RequestException as e:
        log.error('send_action failed: %s', e)
        return False
    log.debug('send_action response: status=%d len=%d', resp.status_code, len(resp.text))
    if resp.status_code in (301, 302, 303, 307, 308):
        log.error('send_action got redirect %d to %s', resp.status_code, resp.headers.get('Location', ''))
        return False
    try:
        resp_text = decode(resp.text)
    except (binascii.Error, UnicodeDecodeError, ValueError) as e:
        log.error('Failed to decode response: %s', e)
        save_debug_html(resp.text, 'send_action_decode_error.html')
        return False
    log.debug('send_action decoded: %s', resp_text[:200])
    if 'Session expired' in resp_text:
        raise RuntimeError('Session expired')
    success = 'views sent' in resp_text.lower()
    if not success:
        log.debug('send_action: success check failed, response: %s', resp_text[:100])
    return success


def search_link(session, key, tiktok_url, api_url, field_name=None, max_retries=3):
    for attempt in range(max_retries):
        form_key = field_name if field_name else key
        body, boundary = build_multipart(form_key, tiktok_url)
        headers = {**API_HEADERS, 'content-type': f'multipart/form-data; boundary={boundary}'}
        log.debug('search_link POST to %s field=%s url=%s (attempt %d/%d)', api_url, form_key, tiktok_url, attempt + 1, max_retries)
        try:
            resp = http_request(session, 'POST', api_url, data=body.encode(), headers=headers, allow_redirects=False)
        except requests.RequestException as e:
            log.error('search_link failed: %s', e)
            return None
        log.debug('search_link response: status=%d len=%d', resp.status_code, len(resp.text))
        if resp.status_code in (301, 302, 303, 307, 308):
            log.error('search_link got redirect %d to %s', resp.status_code, resp.headers.get('Location', ''))
            save_debug_html(resp.text, 'search_link_redirect.html')
            return None
        try:
            resp_text = decode(resp.text)
        except (binascii.Error, UnicodeDecodeError, ValueError) as e:
            log.error('Failed to decode response: %s', e)
            save_debug_html(resp.text, 'search_link_decode_error.html')
            return None
        log.debug('search_link decoded (first 300): %s', resp_text[:300])

        if "onsubmit=\"showHideElements('.w1r','.w2r')" in resp_text:
            matches = re.findall(r'name="([^"]*)"\s+value="([^"]*)"\s+hidden', resp_text)
            if not matches:
                log.error('Could not extract token/aweme_id')
                save_debug_html(resp_text, 'search_link_no_token.html')
                return None
            if len(matches[0]) != 2:
                log.error('Expected 2 groups for token/aweme_id, got %d', len(matches[0]))
                save_debug_html(resp_text, 'search_link_wrong_groups.html')
                return None
            token, aweme_id = matches[0]
            log.info('Sending to: %s', aweme_id)
            sleep(3)
            return send_action(session, token, aweme_id, api_url)
        else:
            timer = parse_timer(resp_text)
            if timer > 0:
                log.info('Timer: %ds — waiting then retrying...', timer)
                wait_timer(timer)
                sleep(3)
                continue
            else:
                log.debug('No timer and no form found in response')
                save_debug_html(resp_text, 'search_link_unknown.html')
                return None

    log.warning('Max retries (%d) reached for timer wait', max_retries)
    return None


CSV_FILE = 'data/stats.csv'


def init_csv():
    with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'cycle', 'success', 'total_sent', 'elapsed_sec', 'timer_sec'])


def log_cycle(cycle, success, total_sent, elapsed, timer=0):
    with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().strftime('%H:%M:%S'), cycle, int(success), total_sent, f'{elapsed:.1f}', timer])


def generate_chart(service_name, tiktok_url):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except (ImportError, ValueError) as e:
        log.warning('matplotlib not available or backend error: %s, skipping chart', e)
        return

    rows = []
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    if not rows:
        log.warning('No data to chart')
        return

    times = []
    totals = []
    successes = []
    timers = []
    for r in rows:
        h, m, s = r['timestamp'].split(':')
        t = datetime.now().replace(hour=int(h), minute=int(m), second=int(s), microsecond=0)
        times.append(t)
        totals.append(int(r['total_sent']))
        successes.append(int(r['success']))
        timers.append(int(r['timer_sec']))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), gridspec_kw={'height_ratios': [3, 1]})
    fig.suptitle(f'Zefoy Bot - {service_name}\n{tiktok_url}', fontsize=13, fontweight='bold')

    ax1.plot(times, totals, 'o-', color='#2196F3', linewidth=2, markersize=4, label='Total views sent')
    ax1.fill_between(times, totals, alpha=0.15, color='#2196F3')
    ax1.set_ylabel('Total Views', fontsize=11)
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='upper left')

    success_count = sum(successes)
    fail_count = len(successes) - success_count
    elapsed = 0
    if len(times) > 1:
        elapsed = (times[-1] - times[0]).total_seconds()
    rate = success_count / (elapsed / 60) if elapsed > 0 else 0

    info_text = f'Sent: {success_count} | Failed: {fail_count} | Rate: {rate:.1f}/min'
    ax1.text(0.5, 0.02, info_text, transform=ax1.transAxes, ha='center', fontsize=10,
             bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.7))

    ax2.bar(times, timers, width=0.001, color='#FF5722', alpha=0.7, label='Timer (sec)')
    ax2.set_ylabel('Timer (sec)', fontsize=11)
    ax2.set_xlabel('Time', fontsize=11)
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='upper left')

    for ax in [ax1, ax2]:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

    plt.tight_layout()
    chart_path = 'stats_chart.png'
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    plt.close()
    log.info('Chart saved: %s', chart_path)
    print(f'{Fore.GREEN}  Grafico salvato: {os.path.abspath(chart_path)}{Fore.RESET}')


PROXY_FILE = 'data/proxies.txt'
STATS_LOCK = threading.Lock()


class GlobalStats:
    def __init__(self, target=100000, time_limit=1800):
        self.total_sent = 0
        self.total_errors = 0
        self.active_workers = 0
        self.start_time = time()
        self.target = target
        self.time_limit = time_limit
        self.worker_counts = {}

    def add_sent(self, worker_id):
        with STATS_LOCK:
            self.total_sent += 1
            self.worker_counts[worker_id] = self.worker_counts.get(worker_id, 0) + 1

    def add_error(self):
        with STATS_LOCK:
            self.total_errors += 1

    def set_active(self, n):
        with STATS_LOCK:
            self.active_workers = n

    def print_dashboard(self):
        with STATS_LOCK:
            elapsed = time() - self.start_time
            mins, secs = divmod(int(elapsed), 60)
            rate = self.total_sent / (elapsed / 60) if elapsed > 0 else 0
            remaining = max(0, self.target - self.total_sent)
            eta_min = remaining / rate if rate > 0 else 0
            progress = min(100, (self.total_sent / self.target) * 100) if self.target > 0 else 0
            bar_len = 30
            filled = int(bar_len * progress / 100)
            bar = '█' * filled + '░' * (bar_len - filled)
            pct = f'{progress:.1f}%'

            lines = [
                f'\n{Fore.CYAN}{"═" * 55}',
                f'  ⏱  Tempo: {mins}m {secs}s   |   Workers attivi: {self.active_workers}',
                f'  📊  Progresso: [{bar}] {pct}',
                f'  ✅  Inviate: {self.total_sent:,} / {self.target:,}   |   Rate: {rate:.0f}/min',
                f'  ⏳  Rimanenti: {remaining:,}   |   ETA: {eta_min:.0f} min',
                f'  ❌  Errori: {self.total_errors}',
                f'{"═" * 55}{Fore.RESET}',
            ]
            print('\033[2J\033[H', end='')
            print('\n'.join(lines))

            for wid, cnt in sorted(self.worker_counts.items()):
                print(f'    Worker {wid:02d}: {cnt} views')
            print()


def load_proxies():
    if not os.path.exists(PROXY_FILE):
        return []
    with open(PROXY_FILE, 'r', encoding='utf-8') as f:
        proxies = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    shuffle(proxies)
    return proxies


PROXY_APIS = [
    'https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text&timeout=5000',
    'https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt',
    'https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/https.txt',
    'https://raw.githubusercontent.com/mmpx12/proxy-list/master/https.txt',
    'https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt',
]


def fetch_free_proxies(max_proxies=50):
    log.info('Fetching free proxies from APIs...')
    raw_proxies = set()

    for api_url in PROXY_APIS:
        try:
            resp = requests.get(api_url, timeout=10, headers={'User-Agent': USER_AGENT})
            if resp.status_code == 200:
                lines = resp.text.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if line and ':' in line and not line.startswith('#'):
                        if not line.startswith('http'):
                            line = f'http://{line}'
                        raw_proxies.add(line)
                log.debug('Got %d proxies from %s', len(lines), api_url.split('/')[2])
        except Exception as e:
            log.debug('Failed to fetch from %s: %s', api_url.split('/')[2], e)
        if len(raw_proxies) >= max_proxies * 2:
            break

    log.info('Fetched %d raw proxies, validating...', len(raw_proxies))
    proxy_list = list(raw_proxies)
    shuffle(proxy_list)
    proxy_list = proxy_list[:max_proxies * 2]

    valid = []
    for proxy in proxy_list:
        if len(valid) >= max_proxies:
            break
        if validate_proxy(proxy):
            valid.append(proxy)

    log.info('Valid proxies: %d/%d', len(valid), len(proxy_list))

    if valid:
        with open(PROXY_FILE, 'w', encoding='utf-8') as f:
            f.write(f'# Auto-fetched {len(valid)} proxies\n')
            for p in valid:
                f.write(f'{p}\n')

    return valid


def validate_proxy(proxy, timeout=5):
    try:
        session = create_session(proxy)
        resp = session.get(
            'https://zefoy.com',
            timeout=timeout,
            headers={'User-Agent': USER_AGENT},
            allow_redirects=False,
        )
        return resp.status_code in (200, 301, 302)
    except Exception:
        return False


class WorkerThread:
    def __init__(self, worker_id, proxy, tiktok_url, api_url, field_name, cookies, service_name, global_stats, phpsessid_pool=None):
        self.worker_id = worker_id
        self.proxy = proxy
        self.tiktok_url = tiktok_url
        self.api_url = api_url
        self.field_name = field_name
        self.cookies = cookies
        self.service_name = service_name
        self.global_stats = global_stats
        self.phpsessid_pool = phpsessid_pool or []
        self.session = None
        self.key = None
        self.count = 0
        self.errors = 0
        self.running = True
        self.reconnects = 0

    def setup_session(self):
        self.session = create_session(self.proxy)
        for name, value in self.cookies.items():
            if name != 'field_name':
                self.session.cookies.set(name, value, domain='zefoy.com')
        self.key = self.field_name

    def try_reconnect(self):
        self.reconnects += 1
        if self.reconnects > 5:
            self.log('warning', 'Max reconnects reached, stopping')
            return False

        if self.phpsessid_pool:
            phpsessid = self.phpsessid_pool[self.reconnects % len(self.phpsessid_pool)]
            self.session = create_session(self.proxy)
            self.session.cookies.set('PHPSESSID', phpsessid, domain='zefoy.com')
            self.log('info', 'Reconnected with PHPSESSID (attempt %d)', self.reconnects)
            try:
                resp = http_request(self.session, 'GET', ZEFOY_URL)
                html = resp.text
                key = extract_key_from_html(html)
                if key:
                    self.key = key
                    self.log('info', 'Session restored')
                    return True
            except Exception as e:
                self.log('error', 'Reconnect failed: %s', e)
        else:
            self.log('warning', 'No PHPSESSID pool, worker stopping')
        return False

    def log(self, level, msg, *args):
        prefix = f'[W{self.worker_id:02d}]'
        if self.proxy:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(self.proxy if '://' in self.proxy else f'http://{self.proxy}')
                short_proxy = parsed.hostname or self.proxy.split(':')[0]
            except Exception:
                short_proxy = self.proxy.split(':')[0] if ':' in self.proxy else self.proxy
            prefix += f'[{short_proxy}]'
        getattr(log, level)(f'{prefix} {msg}', *args)

    def run(self):
        self.setup_session()
        self.log('info', 'Worker started')

        for cycle in range(1, MAX_CYCLES + 1):
            if not self.running:
                break

            elapsed = time() - self.global_stats.start_time
            if elapsed >= self.global_stats.time_limit:
                self.log('info', 'Time limit reached, stopping')
                break

            try:
                result = search_link(self.session, self.key, self.tiktok_url,
                                     self.api_url, self.field_name)
                if result:
                    self.count += 1
                    self.global_stats.add_sent(self.worker_id)
                    self.errors = 0
                    set_window_title(
                        f'Zefoy Bot | Views Generated: {format_number(self.global_stats.total_sent)} | '
                        f'Active Workers: {self.global_stats.active_workers} | '
                        f'Rate: {self.global_stats.total_sent / ((time() - self.global_stats.start_time) / 60):.0f}/min'
                    )
                else:
                    pass
            except RuntimeError as e:
                if 'Session expired' in str(e):
                    self.log('warning', 'Session expired, reconnecting...')
                    if self.try_reconnect():
                        continue
                    else:
                        self.running = False
                        break
                self.log('error', 'Fatal: %s', e)
                break
            except Exception as e:
                self.errors += 1
                self.global_stats.add_error()
                self.log('error', 'Error cycle %d: %s', cycle, e)
                if self.errors >= MAX_ERRORS:
                    self.log('warning', 'Too many errors, trying reconnect...')
                    if self.try_reconnect():
                        self.errors = 0
                        continue
                    else:
                        break
            sleep(5)

        self.log('info', 'Worker stopped. Sent: %d', self.count)
        return self.count


def run_multi_thread(tiktok_url, num_threads, proxy_list, service_choice, api_url, field_name, cookies, phpsessid_pool=None, time_limit=1800):
    stats = GlobalStats(target=100000, time_limit=time_limit)

    workers = []
    for i in range(num_threads):
        proxy = proxy_list[i % len(proxy_list)] if proxy_list else None
        w = WorkerThread(i + 1, proxy, tiktok_url, api_url, field_name, cookies.copy(),
                         SERVICES[service_choice]['name'], stats, phpsessid_pool)
        workers.append(w)

    stats.set_active(num_threads)
    start_time = time()
    init_csv()

    dash_thread = threading.Thread(target=dashboard_loop, args=(stats,), daemon=True)
    dash_thread.start()

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = {executor.submit(w.run): w for w in workers}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                log.error('Worker exception: %s', e)

    stats.set_active(0)
    stats.print_dashboard()

    elapsed_total = time() - start_time
    mins, secs = divmod(int(elapsed_total), 60)
    rate = stats.total_sent / (elapsed_total / 60) if elapsed_total > 0 else 0

    print(f'{Fore.CYAN}{"═" * 55}')
    print(f'  RIEPILOGO FINALE')
    print(f'{"═" * 55}')
    print(f'  Workers:    {num_threads}')
    print(f'  Proxy:      {len(proxy_list)} caricati')
    print(f'  Totale:     {stats.total_sent:,} views')
    print(f'  Tempo:      {mins}m {secs}s')
    print(f'  Rate:       {rate:.1f} views/min')
    if rate > 0:
        print(f'  Target 100k: ~{100000 / rate:.0f} minuti')
    print(f'{"═" * 55}{Fore.RESET}\n')

    log.info('Multi-thread done: %d total in %dm %ds (%.1f/min)', stats.total_sent, mins, secs, rate)
    generate_chart(SERVICES[service_choice]['name'], tiktok_url)
    return stats.total_sent


def dashboard_loop(stats):
    while True:
        with STATS_LOCK:
            if stats.active_workers <= 0:
                break
        stats.print_dashboard()
        sleep(3)
    stats.print_dashboard()


# ============================================================
# Main
# ============================================================

def main():
    clear_terminal()
    
    if HAS_PYFIGLET:
        print(f'{Fore.CYAN}{pyfiglet.figlet_format("Zefoy Bot", font="slant")}{Fore.RESET}')
    else:
        print(f'{Fore.CYAN}╔══════════════════════════════════════╗')
        print(f'{Fore.CYAN}║        Zefoy ViewBot v4              ║')
        print(f'{Fore.CYAN}║  Selenium + Cookie + Multi-Thread    ║')
        print(f'{Fore.CYAN}╚══════════════════════════════════════╝{Fore.RESET}')
    
    print(f'{Fore.WHITE}{"=" * 50}')
    print(f'{Fore.WHITE}Welcome to Zefoy TikTok Bot!')
    print(f'{Fore.WHITE}{"=" * 50}')
    print(f'''
{Fore.WHITE}Available services:
  {Fore.CYAN}[1]{Fore.WHITE} Increase Video Views
  {Fore.CYAN}[2]{Fore.WHITE} Increase Video Likes  
  {Fore.CYAN}[3]{Fore.WHITE} Increase Followers
  {Fore.CYAN}[4]{Fore.WHITE} Increase Comments
  {Fore.CYAN}[5]{Fore.WHITE} Increase Shares
  {Fore.CYAN}[6]{Fore.WHITE} Increase Favorites
  {Fore.CYAN}[7]{Fore.WHITE} Increase Live Stream
  {Fore.CYAN}[8]{Fore.WHITE} Increase Repost
{Fore.RESET}''')

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
    if method not in ('1', '2'):
        log.warning('Invalid method "%s", defaulting to Selenium (1)', method)
        method = '1'

    threads_input = input('Threads (default 1, multi-thread mode): ').strip()
    num_threads = int(threads_input) if threads_input.isdigit() and threads_input.isascii() and int(threads_input) > 0 else 1

    proxy = None
    proxy_list = []
    if num_threads > 1:
        proxy_list = load_proxies()
        if not proxy_list:
            print(f'{Fore.YELLOW}No proxies in proxies.txt{Fore.RESET}')
            auto_fetch = input('Auto-fetch free proxies? (Y/n): ').strip().lower()
            if auto_fetch != 'n':
                max_p = input('Max proxies to fetch (default 30): ').strip()
                max_p = int(max_p) if max_p.isdigit() and 1 <= int(max_p) <= 500 else 30
                proxy_list = fetch_free_proxies(max_p)
                if proxy_list:
                    log.info('Loaded %d working proxies', len(proxy_list))
                else:
                    log.warning('No working proxies found — all threads will use same IP')
            else:
                log.info('Create proxies.txt with format: ip:port (one per line)')
        else:
            log.info('Loaded %d proxies from proxies.txt', len(proxy_list))
        proxy = proxy_list[0] if proxy_list else None
    else:
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
        save_debug_html(html, 'service_list.html')
    except requests.RequestException as e:
        log.error('Failed to fetch services: %s', e)
        return

    available = show_services(html)
    if not available:
        log.error('No services available right now')
        return
    while True:
        choice = input(f'Choose service {available}: ').strip()
        if choice in available:
            break
        log.warning('Invalid choice. Available: %s', available)

    svc = SERVICES[choice]
    api_url, field_name = extract_service_form(html, svc['menu'])
    if not api_url or not field_name:
        log.warning('Could not extract form for %s, using default API URL', svc['name'])
        api_url = API_URL
        field_name = None
    else:
        log.info('Service form: url=%s field=%s', api_url, field_name)

    log.info('Selected: %s', SERVICES[choice]['name'])

    if num_threads > 1:
        time_input = input('Time limit in minutes (default 30): ').strip()
        time_limit = int(time_input) * 60 if time_input.isdigit() and int(time_input) > 0 else 1800

        phpsessid_pool = []
        if method == '2':
            phpsessid = session.cookies.get('PHPSESSID', '')
            if phpsessid:
                phpsessid_pool.append(phpsessid)
            print(f'\n{Fore.YELLOW}Multi-session mode: paste altri PHPSESSID (uno per riga, vuoto per terminare):{Fore.RESET}')
            while True:
                extra = input('  PHPSESSID extra (o INVIO per terminare): ').strip()
                if not extra:
                    break
                phpsessid_pool.append(extra)
            log.info('PHPSESSID pool: %d sessions', len(phpsessid_pool))

        cookies = {}
        for c in session.cookies:
            cookies[c.name] = c.value
        if field_name:
            cookies['field_name'] = field_name

        run_multi_thread(tiktok_url, num_threads, proxy_list, choice, api_url, field_name, cookies, phpsessid_pool, time_limit)
    else:
        log.info('API URL: %s', api_url)
        log.info('Starting send loop...')

        init_csv()
        start_time = time()
        count = 0
        errors = 0
        result = False
        for cycle in range(1, MAX_CYCLES + 1):
            cycle_timer = 0
            cycle_start = time()
            try:
                result = search_link(session, key, tiktok_url, api_url, field_name)
                if result:
                    count += 1
                    log.info('Sent #%d (cycle %d/%d)', count, cycle, MAX_CYCLES)
                    errors = 0
                else:
                    log.debug('Cycle %d/%d - no result', cycle, MAX_CYCLES)
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
            cycle_timer = time() - cycle_start
            elapsed = time() - start_time
            log_cycle(cycle, result is True, count, elapsed, cycle_timer)
            sleep(5)

        elapsed_total = time() - start_time
        mins, secs = divmod(int(elapsed_total), 60)
        log.info('Done. Total sent: %d in %dm %ds', count, mins, secs)
        print(f'\n{Fore.CYAN}  Riepilogo: {count} views in {mins}m {secs}s{Fore.RESET}')
        generate_chart(SERVICES[choice]['name'], tiktok_url)


if __name__ == '__main__':
    main()
