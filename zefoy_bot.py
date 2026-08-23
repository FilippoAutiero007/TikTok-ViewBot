import re
import ssl
import os
import sys
import json
import select
import platform

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
import logging
import binascii
import csv
import threading
import subprocess
import argparse
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
    import pyfiglet
    HAS_PYFIGLET = True
except ImportError:
    HAS_PYFIGLET = False

try:
    from plyer import notification as plyer_notification
    HAS_PLYER = True
except ImportError:
    HAS_PLYER = False

try:
    import sqlite3
    HAS_SQLITE = True
except ImportError:
    HAS_SQLITE = False

init()

CONFIG_FILE = 'config.json'
LOG_FILE = 'logs/bot_log.txt'
os.makedirs('logs', exist_ok=True)

DEFAULT_CONFIG = {
    'max_cycles': 200,
    'max_errors': 10,
    'request_timeout': 30,
    'max_retries': 5,
    'target_views': 100000,
    'default_threads': 1,
    'default_time_limit_min': 30,
    'max_threads': 50,
    'max_time_limit_hours': 48,
    'json_logging': False,
}


def load_config():
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
            config.update({k: v for k, v in user_config.items() if k in DEFAULT_CONFIG})
            log.debug('Loaded config from %s', CONFIG_FILE)
        except (json.JSONDecodeError, OSError) as e:
            log.warning('Failed to load config: %s, using defaults', e)
    return config


def save_config(config):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        log.debug('Config saved to %s', CONFIG_FILE)
    except OSError as e:
        log.warning('Failed to save config: %s', e)


def input_with_timeout(prompt, timeout_sec=300):
    if platform.system() == 'Windows':
        import msvcrt
        print(prompt, end='', flush=True)
        result = ''
        start = time()
        while time() - start < timeout_sec:
            if msvcrt.kbhit():
                ch = msvcrt.getwche()
                if ch in ('\r', '\n'):
                    print()
                    return result.strip()
                elif ch == '\b':
                    if result:
                        result = result[:-1]
                        print('\b \b', end='', flush=True)
                else:
                    result += ch
                    print(ch, end='', flush=True)
            else:
                sleep(0.05)
        print(f'\n{Fore.YELLOW}Input timed out after {timeout_sec}s{Fore.RESET}')
        return result.strip()
    else:
        print(prompt, end='', flush=True)
        rlist, _, _ = select.select([sys.stdin], [], [], timeout_sec)
        if rlist:
            return sys.stdin.readline().strip()
        print(f'\n{Fore.YELLOW}Input timed out after {timeout_sec}s{Fore.RESET}')
        return ''


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

CONFIG = load_config()

try:
    import chromedriver_autoinstaller
    chromedriver_autoinstaller.install()
except ImportError:
    pass
except Exception as e:
    log.warning('chromedriver_autoinstaller failed: %s', e)


def clear_terminal():
    if os.name == 'nt':
        os.system('cls')
    else:
        os.system('clear')


def supports_ansi():
    if os.name == 'nt':
        return os.environ.get('ANSICON') or 'ANSI' in os.environ.get('TERM', '') or hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()
    return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()


ANSI_SUPPORTED = supports_ansi()


def clear_screen():
    if ANSI_SUPPORTED:
        sys.stdout.write('\033[2J\033[H')
        sys.stdout.flush()
    else:
        clear_terminal()


def set_window_title(title):
    safe_title = re.sub(r'[&|;<>`\\]', '', title)
    if os.name == 'nt':
        subprocess.run(['cmd', '/c', 'title', safe_title], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        sys.stdout.write(f'\033]0;{safe_title}\007')
        sys.stdout.flush()


def format_number(n):
    return format(n, ',d').replace(',', '.')


# ============================================================
# M6: Structured JSON Logging
# ============================================================

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            'time': self.formatTime(record),
            'level': record.levelname,
            'message': record.getMessage(),
        }
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False)


def setup_json_logging():
    json_handler = logging.FileHandler('logs/bot_log.json', mode='a', encoding='utf-8')
    json_handler.setFormatter(JsonFormatter())
    log.addHandler(json_handler)


if CONFIG.get('json_logging'):
    setup_json_logging()


# ============================================================
# M7: Proxy Health Check
# ============================================================

class ProxyHealthChecker:
    def __init__(self):
        self.proxy_stats = {}
        self.lock = threading.Lock()

    def record(self, proxy, success):
        with self.lock:
            if proxy not in self.proxy_stats:
                self.proxy_stats[proxy] = {'success': 0, 'fail': 0, 'last_check': time()}
            stats = self.proxy_stats[proxy]
            if success:
                stats['success'] += 1
            else:
                stats['fail'] += 1
            stats['last_check'] = time()

    def is_healthy(self, proxy, min_success_rate=0.3):
        with self.lock:
            if proxy not in self.proxy_stats:
                return True
            stats = self.proxy_stats[proxy]
            total = stats['success'] + stats['fail']
            if total < 3:
                return True
            rate = stats['success'] / total
            return rate >= min_success_rate

    def get_best_proxy(self, proxy_list):
        healthy = [p for p in proxy_list if self.is_healthy(p)]
        return healthy[0] if healthy else (proxy_list[0] if proxy_list else None)


PROXY_HEALTH = ProxyHealthChecker()


def notify_desktop(title, message):
    if not HAS_PLYER:
        return
    try:
        plyer_notification.notify(
            title=title,
            message=message,
            app_name='Zefoy Bot',
            timeout=5,
        )
    except Exception:
        pass


# ============================================================
# M8: Adaptive Rate Limiter
# ============================================================

class AdaptiveRateLimiter:
    def __init__(self, base_delay=5, min_delay=1, max_delay=30):
        self.base_delay = base_delay
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.current_delay = base_delay
        self.recent_codes = []
        self.lock = threading.Lock()

    def record_status(self, status_code):
        with self.lock:
            self.recent_codes.append((time(), status_code))
            cutoff = time() - 60
            self.recent_codes = [(t, c) for t, c in self.recent_codes if t > cutoff]
            rate_limit_count = sum(1 for _, c in self.recent_codes if c == 429)
            error_count = sum(1 for _, c in self.recent_codes if c >= 500)
            if rate_limit_count > 0:
                self.current_delay = min(self.max_delay, self.current_delay * (1 + rate_limit_count * 0.5))
                log.debug('Rate limiter: increased delay to %.1fs (429 count: %d)', self.current_delay, rate_limit_count)
            elif error_count > 2:
                self.current_delay = min(self.max_delay, self.current_delay * 1.3)
            elif len(self.recent_codes) > 5:
                success_count = sum(1 for _, c in self.recent_codes if 200 <= c < 400)
                if success_count / len(self.recent_codes) > 0.9:
                    self.current_delay = max(self.min_delay, self.current_delay * 0.9)

    def get_delay(self):
        with self.lock:
            return self.current_delay


RATE_LIMITER = AdaptiveRateLimiter()


# ============================================================
# M11: SQLite Stats
# ============================================================

class SqliteStats:
    def __init__(self, db_path='data/stats.db'):
        self.db_path = db_path
        self.lock = threading.Lock()
        if HAS_SQLITE:
            self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute('''CREATE TABLE IF NOT EXISTS cycles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                cycle INTEGER,
                success INTEGER,
                total_sent INTEGER,
                elapsed_sec REAL,
                timer_sec INTEGER,
                worker_id INTEGER,
                service TEXT
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                service TEXT,
                total_sent INTEGER,
                duration_sec REAL
            )''')
            conn.commit()
            conn.close()

    def log_cycle(self, cycle, success, total_sent, elapsed, timer=0, worker_id=0, service=''):
        if not HAS_SQLITE:
            return
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute(
                    'INSERT INTO cycles (timestamp, cycle, success, total_sent, elapsed_sec, timer_sec, worker_id, service) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), cycle, int(success), total_sent, f'{elapsed:.1f}', timer, worker_id, service)
                )
                conn.commit()
                conn.close()
            except Exception as e:
                log.debug('SQLite log_cycle failed: %s', e)

    def log_session_end(self, service, total_sent, duration_sec):
        if not HAS_SQLITE:
            return
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute(
                    'INSERT INTO sessions (timestamp, service, total_sent, duration_sec) VALUES (?, ?, ?, ?)',
                    (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), service, total_sent, duration_sec)
                )
                conn.commit()
                conn.close()
            except Exception as e:
                log.debug('SQLite log_session_end failed: %s', e)

    def get_stats(self, service=None, last_n=None):
        if not HAS_SQLITE:
            return []
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                query = 'SELECT * FROM cycles'
                params = []
                if service:
                    query += ' WHERE service = ?'
                    params.append(service)
                query += ' ORDER BY id DESC'
                if last_n:
                    query += ' LIMIT ?'
                    params.append(last_n)
                rows = conn.execute(query, params).fetchall()
                conn.close()
                return rows
            except Exception:
                return []


SQLITE_STATS = SqliteStats()


USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
ZEFOY_URL = 'https://zefoy.com'

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

MAX_CYCLES = CONFIG['max_cycles']
MAX_ERRORS = CONFIG['max_errors']
REQUEST_TIMEOUT = CONFIG['request_timeout']
MAX_RETRIES = CONFIG['max_retries']
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
            RATE_LIMITER.record_status(resp.status_code)
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
        if not proxy.startswith(('http://', 'https://', 'socks5://', 'socks5h://', 'socks4://', 'socks4a://')):
            proxy = f'http://{proxy}'
        s.proxies = {'http': proxy, 'https': proxy}
        if proxy.startswith(('socks5://', 'socks5h://', 'socks4://', 'socks4a://')):
            try:
                import urllib3.contrib.socks
                s.mount('socks5://', urllib3.contrib.socks.SOCKSProxyManager)
                s.mount('socks5h://', urllib3.contrib.socks.SOCKSProxyManager)
                s.mount('socks4://', urllib3.contrib.socks.SOCKSProxyManager)
                s.mount('socks4a://', urllib3.contrib.socks.SOCKSProxyManager)
            except ImportError:
                log.warning('PySocks/urllib3[socks] not installed. SOCKS proxy may fail. Install: pip install urllib3[socks]')
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

        result = input_with_timeout(f'{Fore.YELLOW}Solve the captcha in the browser, then press Enter here...{Fore.RESET}', timeout_sec=600)
        log.debug('Captcha input returned: %s', repr(result))

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
    phpsessid = input_with_timeout('Paste PHPSESSID: ', timeout_sec=60).strip()
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


def is_valid_base64_action(action):
    import string as _string
    valid_chars = set(_string.ascii_letters + _string.digits + '+/=')
    return bool(action) and len(action) > 10 and all(c in valid_chars for c in action)


def extract_service_form(html, menu_selector):
    menu_pattern = rf'<div[^>]*class="[^"]*\b{re.escape(menu_selector)}\b[^"]*"[^>]*>(.*?)</div>\s*</div>'
    menu_match = re.findall(menu_pattern, html, re.IGNORECASE | re.DOTALL)
    if not menu_match:
        menu_pattern = rf'<div[^>]*class="[^"]*\b{re.escape(menu_selector)}\b[^"]*"[^>]*>(.*?)</div>'
        menu_match = re.findall(menu_pattern, html, re.IGNORECASE | re.DOTALL)
    if not menu_match:
        return None, None

    menu_html = menu_match[0]

    action_pattern = r'action="([^"]*)"'
    action_match = re.findall(action_pattern, menu_html)
    if action_match:
        raw_action = action_match[0]
        if is_valid_base64_action(raw_action):
            action_url = f'{ZEFOY_URL}/{raw_action}'
        else:
            log.warning('Extracted action "%s" is not valid base64, trying to find correct form', raw_action)
            action_url = None
    else:
        action_url = None

    name_pattern = r'name="([^"]*)"'
    name_match = re.findall(name_pattern, menu_html)
    field_name = None
    for name in name_match:
        if name and len(name) > 5 and name != 'token':
            field_name = name
            break

    if not action_url or not field_name:
        all_forms = re.findall(
            rf'<div[^>]*class="[^"]*\b{re.escape(menu_selector)}\b[^"]*"[^>]*>.*?</form>',
            html, re.IGNORECASE | re.DOTALL
        )
        for form_html in all_forms:
            am = re.findall(r'action="([^"]*)"', form_html)
            if am and is_valid_base64_action(am[0]):
                action_url = f'{ZEFOY_URL}/{am[0]}'
                nm = re.findall(r'name="([^"]*)"', form_html)
                for n in nm:
                    if n and len(n) > 5 and n != 'token':
                        field_name = n
                        break
                if action_url and field_name:
                    break

    return action_url, field_name


def show_services(html):
    log.info('Available services:')
    available = []
    disabled = []
    for num, svc in SERVICES.items():
        status = check_service_status(html, svc['selector'])
        if status:
            icon = f'{Fore.GREEN}ON{Fore.RESET}'
            available.append(num)
        else:
            icon = f'{Fore.RED}OFF{Fore.RESET}'
            disabled.append(num)
        print(f'  [{num}] {svc["name"]:<12} {icon}')
    if disabled:
        print(f'\n  {Fore.RED}OFF services are disabled by zefoy.com (not a bot bug){Fore.RESET}')
    return available



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
    safe_value = value.replace('\r', '').replace('\n', '').replace('\x00', '')
    token = ''.join(choices(ascii_letters + digits, k=16))
    boundary = f'----WebKitFormBoundary{token}'
    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
        f'{safe_value}\r\n'
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
        location = resp.headers.get('Location', '')
        log.error('send_action got redirect %d to %s', resp.status_code, location)
        return False
    if resp.url and resp.url.rstrip('/') != api_url.rstrip('/'):
        log.warning('send_action redirected to %s', resp.url)
        return False
    if resp.status_code == 200 and len(resp.text) > 10000 and '<html' in resp.text.lower():
        log.error('send_action got full HTML page instead of API response')
        return False
    raw = resp.text
    timer_raw = parse_timer(raw)
    if timer_raw > 0:
        log.info('send_action timer: %ds', timer_raw)
        return False
    try:
        resp_text = decode(raw)
    except (binascii.Error, UnicodeDecodeError, ValueError) as e:
        log.error('Failed to decode send_action response: %s', e)
        save_debug_html(raw, 'send_action_decode_error.html')
        return False
    log.debug('send_action decoded: %s', resp_text[:200])
    if 'Session expired' in resp_text:
        raise RuntimeError('Session expired')
    lower = resp_text.lower()
    text_success = any(phrase in lower for phrase in [
        'views sent', 'hearts sent', 'followers sent', 'comments',
        'shares sent', 'favorites sent', 'repost sent', 'sent successfully',
        'success', 'completed'
    ])
    form_success = "onsubmit=\"fcde(" in resp_text or "onsubmit=\"showHideElements(" in resp_text
    success = text_success or form_success
    if not success:
        log.debug('send_action: success check failed, response: %s', resp_text[:100])
    else:
        log.debug('send_action: success (text=%s, form=%s)', text_success, form_success)
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
            location = resp.headers.get('Location', '')
            log.error('search_link got redirect %d to %s', resp.status_code, location)
            if location and ('/' == location or location.rstrip('/').endswith('zefoy.com') or location == '/'):
                log.error('Redirected to homepage — API URL is invalid or session expired')
                save_debug_html(resp.text, 'search_link_redirect.html')
                raise RuntimeError('Session expired')
            save_debug_html(resp.text, 'search_link_redirect.html')
            sleep(5)
            continue
        if resp.url and resp.url.rstrip('/') != api_url.rstrip('/'):
            log.warning('Response URL %s differs from request URL %s — session may be expired', resp.url, api_url)
            save_debug_html(resp.text, 'search_link_redirect.html')
            raise RuntimeError('Session expired')
        if resp.status_code == 200 and len(resp.text) > 10000 and '<html' in resp.text.lower():
            log.error('Got full HTML page (%d chars) instead of API response — API URL may be invalid', len(resp.text))
            save_debug_html(resp.text, 'search_link_wrong_response.html')
            raise RuntimeError('Session expired')

        raw = resp.text
        timer_raw = parse_timer(raw)
        if timer_raw > 0:
            log.info('Timer: %ds — waiting then retrying...', timer_raw)
            wait_timer(timer_raw)
            sleep(3)
            continue

        try:
            resp_text = decode(raw)
        except (binascii.Error, UnicodeDecodeError, ValueError) as e:
            log.error('Failed to decode response: %s', e)
            save_debug_html(raw, 'search_link_decode_error.html')
            sleep(5)
            continue
        log.debug('search_link decoded (first 300): %s', resp_text[:300])

        if "onsubmit=\"showHideElements('.w1r','.w2r')" in resp_text or "onsubmit=\"fcde(" in resp_text:
            matches = re.findall(r'name="([^"]*)"\s+value="([^"]*)"\s*(?:hidden|/\s*>)', resp_text)
            if not matches:
                matches = re.findall(r'type="hidden"\s+name="([^"]*)"\s+value="([^"]*)"', resp_text)
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
                sleep(5)
                continue

    log.warning('Max retries (%d) reached for timer wait', max_retries)
    return None


CSV_FILE = 'data/stats.csv'
CSV_LOCK = threading.Lock()


def init_csv():
    os.makedirs('data', exist_ok=True)
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'cycle', 'success', 'total_sent', 'elapsed_sec', 'timer_sec'])


def log_cycle(cycle, success, total_sent, elapsed, timer=0):
    with CSV_LOCK:
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
    with CSV_LOCK:
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
    prev_seconds = -1
    day_offset = 0
    for r in rows:
        h, m, s = r['timestamp'].split(':')
        current_seconds = int(h) * 3600 + int(m) * 60 + int(s)
        if prev_seconds >= 0 and current_seconds < prev_seconds:
            day_offset += 1
        prev_seconds = current_seconds
        t = datetime.now().replace(hour=int(h), minute=int(m), second=int(s), microsecond=0)
        t = t.replace(day=t.day + day_offset) if day_offset else t
        times.append(t)
        totals.append(int(float(r['total_sent'])))
        successes.append(int(float(r['success'])))
        timers.append(float(r['timer_sec']))

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

    if len(times) > 1:
        diffs = [(times[i] - times[i-1]).total_seconds() for i in range(1, len(times))]
        avg_interval = sum(diffs) / len(diffs) if diffs else 60
        bar_width = max(0.0003, avg_interval / 86400 * 0.8)
    else:
        bar_width = 0.001
    ax2.bar(times, timers, width=bar_width, color='#FF5722', alpha=0.7, label='Timer (sec)')
    ax2.set_ylabel('Timer (sec)', fontsize=11)
    ax2.set_xlabel('Time', fontsize=11)
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='upper left')

    for ax in [ax1, ax2]:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

    plt.tight_layout()
    os.makedirs('data', exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    chart_path = os.path.join('data', f'stats_chart_{timestamp}.png')
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    plt.close()
    log.info('Chart saved: %s', chart_path)
    print(f'{Fore.GREEN}  Chart saved: {os.path.abspath(chart_path)}{Fore.RESET}')


PROXY_FILE = 'data/proxies.txt'
STATS_LOCK = threading.Lock()


class GlobalStats:
    def __init__(self, target=None, time_limit=1800):
        self.total_sent = 0
        self.total_errors = 0
        self.active_workers = 0
        self.start_time = time()
        self.target = target or CONFIG['target_views']
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
                f'  Time: {mins}m {secs}s   |   Active workers: {self.active_workers}',
                f'  Progress: [{bar}] {pct}',
                f'  Sent: {self.total_sent:,} / {self.target:,}   |   Rate: {rate:.0f}/min',
                f'  Remaining: {remaining:,}   |   ETA: {eta_min:.0f} min',
                f'  Errors: {self.total_errors}',
                f'{"═" * 55}{Fore.RESET}',
            ]
            clear_screen()
            print('\n'.join(lines))

            for wid, cnt in sorted(self.worker_counts.items()):
                print(f'    Worker {wid:02d}: {cnt} views')
            print()


def load_proxies():
    if not os.path.exists(PROXY_FILE):
        return []
    with CSV_LOCK:
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
    session = create_session()

    for api_url in PROXY_APIS:
        try:
            resp = http_request(session, 'GET', api_url, max_retries=1, timeout=10)
            if resp.status_code == 200:
                lines = resp.text.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if line and ':' in line and not line.startswith('#'):
                        if not line.startswith('http'):
                            line = f'http://{line}'
                        raw_proxies.add(line)
                log.debug('Got %d proxies from %s', len(lines), api_url.split('/')[2] if len(api_url.split('/')) > 2 else api_url)
        except Exception as e:
            log.debug('Failed to fetch from %s: %s', api_url.split('/')[2] if len(api_url.split('/')) > 2 else api_url, e)
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
        try:
            resp = http_request(self.session, 'GET', ZEFOY_URL, max_retries=2)
            html = resp.text
            extracted_key = extract_key_from_html(html)
            if extracted_key:
                self.key = extracted_key
                self.log('info', 'Session validated, key: %s', self.key)
            else:
                self.log('warning', 'Session set but could not extract key')
        except Exception as e:
            self.log('warning', 'Session validation failed: %s', e)

    def try_reconnect(self):
        self.reconnects += 1
        if self.reconnects > 5:
            self.log('warning', 'Max reconnects reached, stopping')
            return False

        if self.phpsessid_pool:
            attempts = 0
            while attempts < len(self.phpsessid_pool):
                phpsessid = self.phpsessid_pool[self.reconnects % len(self.phpsessid_pool)]
                self.reconnects += 1
                attempts += 1
                self.session = create_session(self.proxy)
                self.session.cookies.set('PHPSESSID', phpsessid, domain='zefoy.com')
                self.log('info', 'Trying PHPSESSID (attempt %d/%d)', attempts, len(self.phpsessid_pool))
                try:
                    resp = http_request(self.session, 'GET', ZEFOY_URL, max_retries=1)
                    html = resp.text
                    key = extract_key_from_html(html)
                    if key:
                        self.key = key
                        self.log('info', 'Session restored with PHPSESSID')
                        return True
                    else:
                        self.log('debug', 'PHPSESSID %s did not yield key, trying next', phpsessid[:8])
                except Exception as e:
                    self.log('debug', 'PHPSESSID %s failed: %s', phpsessid[:8], e)
            self.log('warning', 'All PHPSESSIDs in pool are stale')
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

            cycle_start = time()
            try:
                result = search_link(self.session, self.key, self.tiktok_url,
                                     self.api_url, self.field_name)
                if result:
                    self.count += 1
                    self.global_stats.add_sent(self.worker_id)
                    self.errors = 0
                    PROXY_HEALTH.record(self.proxy, True)
                    SQLITE_STATS.log_cycle(cycle, True, self.global_stats.total_sent,
                                           time() - self.global_stats.start_time,
                                           0, self.worker_id, self.service_name)
                    set_window_title(
                        f'Zefoy Bot | Views Generated: {format_number(self.global_stats.total_sent)} | '
                        f'Active Workers: {self.global_stats.active_workers} | '
                        f'Rate: {self.global_stats.total_sent / ((time() - self.global_stats.start_time) / 60):.0f}/min'
                    )
                else:
                    PROXY_HEALTH.record(self.proxy, False)
            except RuntimeError as e:
                if 'Session expired' in str(e):
                    self.log('warning', 'Session expired, reconnecting...')
                    if self.try_reconnect():
                        continue
                    else:
                        self.running = False
                        notify_desktop('Zefoy Bot', f'Worker {self.worker_id}: Session expired, stopping')
                        break
                self.log('error', 'Fatal: %s', e)
                break
            except Exception as e:
                self.errors += 1
                self.global_stats.add_error()
                PROXY_HEALTH.record(self.proxy, False)
                self.log('error', 'Error cycle %d: %s', cycle, e)
                if self.errors >= MAX_ERRORS:
                    self.log('warning', 'Too many errors, trying reconnect...')
                    if self.try_reconnect():
                        self.errors = 0
                        continue
                    else:
                        notify_desktop('Zefoy Bot', f'Worker {self.worker_id}: Too many errors, stopping')
                        break
            sleep_delay = max(1, RATE_LIMITER.get_delay() - (time() - cycle_start))
            sleep(sleep_delay)

        self.log('info', 'Worker stopped. Sent: %d', self.count)
        return self.count


def run_multi_thread(tiktok_url, num_threads, proxy_list, service_choice, api_url, field_name, cookies, phpsessid_pool=None, time_limit=1800):
    stats = GlobalStats(time_limit=time_limit)

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
    print(f'  FINAL SUMMARY')
    print(f'{"═" * 55}')
    print(f'  Workers:    {num_threads}')
    print(f'  Proxies:    {len(proxy_list)} loaded')
    print(f'  Total:      {stats.total_sent:,} views')
    print(f'  Time:       {mins}m {secs}s')
    print(f'  Rate:       {rate:.1f} views/min')
    target = stats.target
    if rate > 0:
        print(f'  Target {format_number(target)}: ~{target / rate:.0f} min')
    print(f'{"═" * 55}{Fore.RESET}\n')

    SQLITE_STATS.log_session_end(SERVICES[service_choice]['name'], stats.total_sent, elapsed_total)
    notify_desktop('Zefoy Bot', f'Done: {stats.total_sent:,} {SERVICES[service_choice]["name"].lower()} in {mins}m {secs}s')
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

def parse_args():
    parser = argparse.ArgumentParser(description='Zefoy TikTok ViewBot v4', formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Examples:\n  python zefoy_bot.py --url https://vm.tiktok.com/XXX --method 2 --threads 5\n  python zefoy_bot.py --url https://vm.tiktok.com/XXX --service 6 --time 60\n  python zefoy_bot.py --url https://vm.tiktok.com/XXX --method 2 --phpsessid abc123')
    parser.add_argument('--url', '-u', help='TikTok video URL')
    parser.add_argument('--method', '-m', choices=['1', '2'], default=None, help='Captcha method: 1=Selenium, 2=Cookie (default: interactive)')
    parser.add_argument('--service', '-s', choices=['1','2','3','4','5','6','7','8'], default=None, help='Service number (auto-select if available)')
    parser.add_argument('--threads', '-t', type=int, default=None, help='Number of threads (default: 1)')
    parser.add_argument('--time', type=int, default=None, help='Time limit in minutes (default: 30)')
    parser.add_argument('--proxy', '-p', default=None, help='Proxy (ip:port or url)')
    parser.add_argument('--phpsessid', default=None, help='PHPSESSID for cookie method')
    parser.add_argument('--config', default=None, help='Path to config JSON file')
    parser.add_argument('--target', type=int, default=None, help='Target views count (default: from config)')
    parser.add_argument('--max-cycles', type=int, default=None, help='Max cycles (default: from config)')
    parser.add_argument('--json-log', action='store_true', default=None, help='Enable JSON logging')
    parser.add_argument('--list-services', action='store_true', help='List available services and exit')
    return parser.parse_args()


def main():
    global CONFIG, MAX_CYCLES, MAX_ERRORS
    args = parse_args()
    clear_terminal()

    if args.config:
        if os.path.exists(args.config):
            try:
                with open(args.config, 'r', encoding='utf-8') as f:
                    CONFIG.update(json.load(f))
                log.info('Loaded config from %s', args.config)
            except Exception as e:
                log.error('Failed to load config %s: %s', args.config, e)
                return
        else:
            log.error('Config file not found: %s', args.config)
            return

    if args.target:
        CONFIG['target_views'] = args.target
    if args.max_cycles:
        CONFIG['max_cycles'] = args.max_cycles
    if args.json_log:
        CONFIG['json_logging'] = True
        setup_json_logging()
    MAX_CYCLES = CONFIG['max_cycles']
    MAX_ERRORS = CONFIG['max_errors']
    
    if args.list_services:
        print(f'\n{Fore.CYAN}Available Zefoy Services:{Fore.RESET}')
        for num, svc in SERVICES.items():
            print(f'  [{num}] {svc["name"]}')
        print(f'\n{Fore.WHITE}Use --service <number> to auto-select{Fore.RESET}')
        return

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

    tiktok_url = args.url or input('TikTok URL: ').strip()
    if not tiktok_url:
        log.error('No URL provided')
        return
    if not validate_tiktok_url(tiktok_url):
        log.error('Invalid TikTok URL (must be from vm.tiktok.com, tiktok.com, or vt.tiktok.com)')
        return

    if args.method:
        method = args.method
    else:
        print(f"""
{Fore.WHITE}Captcha solving method:
  {Fore.CYAN}[1]{Fore.WHITE} Selenium (default) - opens Chrome, solve captcha there
  {Fore.CYAN}[2]{Fore.WHITE} Manual cookie      - paste PHPSESSID from browser{Fore.RESET}
""")
        method = input(f'Choose method [1]: ').strip() or '1'
        if method not in ('1', '2'):
            log.warning('Invalid method "%s", defaulting to Selenium (1)', method)
            method = '1'

    if args.threads is not None:
        num_threads = max(1, min(args.threads, CONFIG['max_threads']))
    else:
        threads_input = input('Threads (default 1, multi-thread mode): ').strip()
        num_threads = int(threads_input) if threads_input.isdigit() and threads_input.isascii() and int(threads_input) > 0 else 1
        num_threads = min(num_threads, CONFIG['max_threads'])

    proxy = args.proxy
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
        if not proxy:
            proxy = proxy_list[0] if proxy_list else None
    elif not proxy:
        if args.url and args.service and args.method and args.threads is not None:
            log.info('No proxy provided, running without proxy')
        elif sys.stdin.isatty():
            proxy = input('Proxy (optional, format: ip:port or press Enter): ').strip() or None

    log.info('Starting Zefoy bot...')

    if method == '2' and args.phpsessid:
        session = create_session(proxy)
        session.cookies.set('PHPSESSID', args.phpsessid, domain='zefoy.com')
        log.info('Verifying session...')
        try:
            resp = http_request(session, 'GET', ZEFOY_URL)
            html = resp.text
            key = extract_key_from_html(html)
            if not key:
                log.error('PHPSESSID from CLI is invalid')
                return
            log.info('Session valid! Key: %s', key)
        except Exception as e:
            log.error('Session verification failed: %s', e)
            return
    elif method == '2':
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
        log.error('No services available right now — zefoy.com may be down')
        return
    if args.service:
        if args.service in available:
            choice = args.service
            log.info('Auto-selected service: %s', SERVICES[choice]['name'])
        else:
            svc_info = SERVICES.get(args.service, {})
            svc_name = svc_info.get('name', f'Service #{args.service}')
            log.error('Service %s (%s) is currently DISABLED on zefoy.com', args.service, svc_name)
            log.info('Available services: %s', ', '.join(f'{n}={SERVICES[n]["name"]}' for n in available))
            log.info('Try: --service %s (Comments) or --service %s (Favorites)', available[0], available[-1])
            return
    else:
        while True:
            choice = input(f'Choose service {available}: ').strip()
            if choice in available:
                break
            log.warning('Invalid choice. Available: %s', available)

    svc = SERVICES[choice]
    api_url, field_name = extract_service_form(html, svc['menu'])
    if not api_url or not field_name:
        log.error('Could not extract form for %s — cannot proceed', svc['name'])
        log.info('Try refreshing session or choose another service')
        return
    else:
        log.info('Service form: url=%s field=%s', api_url, field_name)

    log.info('Selected: %s', SERVICES[choice]['name'])

    if num_threads > 1:
        if args.time is not None:
            time_limit = max(60, min(args.time * 60, CONFIG['max_time_limit_hours'] * 3600))
        else:
            time_input = input('Time limit in minutes (default 30): ').strip()
            time_limit = int(time_input) * 60 if time_input.isdigit() and int(time_input) > 0 else 1800
            time_limit = min(time_limit, CONFIG['max_time_limit_hours'] * 3600)

        phpsessid_pool = []
        if method == '2':
            phpsessid = session.cookies.get('PHPSESSID', '')
            if phpsessid:
                phpsessid_pool.append(phpsessid)
            print(f'\n{Fore.YELLOW}Multi-session mode: paste additional PHPSESSID (one per line, empty to finish):{Fore.RESET}')
            while True:
                extra = input('  PHPSESSID extra (or ENTER to finish): ').strip()
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
                    PROXY_HEALTH.record(proxy, True)
                    errors = 0
                else:
                    PROXY_HEALTH.record(proxy, False)
                    log.debug('Cycle %d/%d - no result', cycle, MAX_CYCLES)
            except RuntimeError as e:
                if 'Session expired' in str(e):
                    log.warning('Session expired, re-solving captcha...')
                    notify_desktop('Zefoy Bot', 'Session expired, re-solving captcha...')
                    if method == '2':
                        session, key = solve_with_cookie(proxy)
                    else:
                        session, key = solve_with_selenium(proxy)
                    if not key:
                        log.error('Reconnect failed')
                        break
                    try:
                        resp = http_request(session, 'GET', ZEFOY_URL)
                        html = resp.text
                        new_api_url, new_field = extract_service_form(html, SERVICES[choice]['menu'])
                        if new_api_url and new_field:
                            api_url = new_api_url
                            field_name = new_field
                            log.info('Service form refreshed: url=%s field=%s', api_url, field_name)
                    except Exception:
                        pass
                    errors = 0
                    continue
                log.error('Fatal error: %s', e)
                break
            except Exception as e:
                errors += 1
                PROXY_HEALTH.record(proxy, False)
                log.error('Error at cycle %d: %s', cycle, e)
                if errors >= MAX_ERRORS:
                    log.error('Too many errors, re-solving captcha...')
                    notify_desktop('Zefoy Bot', 'Too many errors, re-solving captcha...')
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
            SQLITE_STATS.log_cycle(cycle, result is True, count, elapsed, cycle_timer, 0, SERVICES[choice]['name'])
            sleep_delay = max(1, RATE_LIMITER.get_delay() - cycle_timer)
            sleep(sleep_delay)

        elapsed_total = time() - start_time
        mins, secs = divmod(int(elapsed_total), 60)
        log.info('Done. Total sent: %d in %dm %ds', count, mins, secs)
        print(f'\n{Fore.CYAN}  Summary: {count} views in {mins}m {secs}s{Fore.RESET}')
        SQLITE_STATS.log_session_end(SERVICES[choice]['name'], count, elapsed_total)
        notify_desktop('Zefoy Bot', f'Done: {count} views in {mins}m {secs}s')
        generate_chart(SERVICES[choice]['name'], tiktok_url)


if __name__ == '__main__':
    main()
