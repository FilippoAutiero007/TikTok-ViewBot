import json
import hashlib
import time
import random
import string
import base64
import logging
from urllib.parse import urlencode, urlparse
import requests
from requests.adapters import HTTPAdapter
import ssl

try:
    from tiktok_signer import TikTokSigner
    SIGNER_AVAILABLE = True
except ImportError:
    SIGNER_AVAILABLE = False

from .captcha_solver import TikTokCaptchaSolver

log = logging.getLogger(__name__)

if not SIGNER_AVAILABLE:
    log.warning('TikTokSigner not installed - request signing will use fallback (may not work)')

USER_AGENT_TPL = 'com.zhiliaoapp.musically/{version_code} (Linux; U; Android {android_ver}; {locale}; {model}; Build/{build_id}; Cronet/TTNetVersion:b4d74d15 2023-02-14 QuicVersion:0144d358 2023-03-10)'

ENDPOINTS = {
    'follow': 'aweme/v1/commit/follow/user/',
    'unfollow': 'aweme/v1/commit/unfollow/user/',
    'like': 'aweme/v1/commit/item/digg/',
    'unlike': 'aweme/v1/commit/item/undigg/',
    'view': 'aweme/v1/aweme/feedback/',
    'comment': 'aweme/v1/comment/publish/',
    'share': 'aweme/v1/aweme/share/',
    'profile': 'aweme/v1/user/profile/self/',
    'search': 'aweme/v1/general/search/single/',
    'user_info': 'aweme/v1/user/',
    'feed': 'aweme/v1/tab/feed/',
    'hot': 'aweme/v1/hot/search/list/',
}

DOMAIN_GROUPS = {
    'maliva': ['api16-normal-c-alisg.tiktokv.com', 'api19-normal-c-alisg.tiktokv.com'],
    'useast1a': ['api16-normal-c-useast1a.tiktokv.com', 'api19-normal-c-useast1a.tiktokv.com'],
    'useast2a': ['api16-normal-c-useast2a.tiktokv.com', 'api19-normal-c-useast2a.tiktokv.com'],
    'us': ['api16-normal-c-useast5.us.tiktokv.com'],
}

CAPTCHA_DOMAINS = ['verify-sg.tiktokv.com', 'verification-va.byteoversea.com']

PASSPORT_DOMAINS = {
    'maliva': 'api22-normal-c-alisg.tiktokv.com',
    'useast1a': 'api22-normal-c-useast1a.tiktokv.com',
    'useast2a': 'api22-normal-c-useast2a.tiktokv.com',
    'us': 'api22-normal-c-useast5.us.tiktokv.com',
}


class TikTokAPIError(Exception):
    def __init__(self, message, code=None, response=None):
        super().__init__(message)
        self.code = code
        self.response = response


def _xor_encode(text):
    return ''.join(format(ord(c) ^ 5, '02x') for c in text)


def _random_build_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))


def _generate_query(device, extra_params=None, fixed_time=None):
    """Genera i query params UNA volta sola.

    fixed_time: opzionale (unix_sec:int, rticket_ms:int). Se passato, gli stessi
    valori vengono riusati per 'timestamp'/'ts'/'_rticket' così che URL e firma
    condividano identici timestamp (prima ogni chiamata a time() generava valori
    diversi → firma invalida → WAF risponde 200 vuoto).
    """
    if fixed_time is not None:
        unix_sec, rticket_ms = fixed_time
    else:
        unix_sec = int(time.time())
        rticket_ms = int(time.time() * 1000)
    params = {
        'aid': '1233',
        'app_language': device.get('language', 'en'),
        'app_name': 'musically_go',
        'app_type': 'normal',
        'channel': 'googleplay',
        'device_id': device['device_id'],
        'device_platform': 'android',
        'device_type': device.get('model', 'SM-G991B'),
        'dz': '0',
        'iid': device.get('install_id', ''),
        'manifest_version_code': device.get('app_info', {}).get('manifest_version_code', '2023400020'),
        'openudid': device.get('openudid', ''),
        'os_version': device.get('android_version', '13'),
        'region': device.get('region', 'US'),
        'resolution': device.get('resolution', '1080x2340'),
        'ssmix': 'a',
        'tz': device.get('timezone', 'America/New_York'),
        'version_code': device.get('app_info', {}).get('version_code', '340002'),
        '_rticket': str(rticket_ms),
        'current_region': device.get('region', 'US'),
        'os_api': device.get('sdk_version', '33'),
        'device_brand': device.get('brand', 'samsung'),
        'timezone_name': device.get('timezone', 'America/New_York'),
        'timestamp': str(unix_sec),
        'ts': str(unix_sec),
        'locale': device.get('locale', 'en_US'),
        'language': device.get('language', 'en'),
        'ac': 'wifi',
        'dpi': device.get('dpi', '420'),
    }
    if extra_params:
        params.update(extra_params)
    return params


def _sign_request_tiktoksigner(signer, params, payload=b'', version_code=340002, version_name='34.0.2', device=None, cookie=None):
    """Firma con il signer reale. NIENTE fallback fake.

    - params: DEVE essere lo stesso dict usato per costruire l'URL (stessi
      timestamp/_rticket). Non rigenerare mai una seconda query per firmare.
    - payload: DEVE essere il body reale che verrà inviato via POST (stessi byte).
    - unix: derivato da params['timestamp'] così Ladon/Gorgon/Argus condividono
      lo stesso timestamp della query (il signer li calcola tutti dallo stesso unix).
    Solleva TikTokAPIError se signer mancante o firma incompleta, invece di
    restituire header inventati che il WAF scarta con body vuoto.
    """
    if signer is None:
        raise TikTokAPIError(
            'TikTokSigner non disponibile: installa tiktok-signer, niente firma fake'
        )
    if isinstance(params, dict):
        try:
            unix = int(params.get('timestamp', int(time.time())))
        except (ValueError, TypeError):
            unix = int(time.time())
    else:
        unix = int(time.time())
    if isinstance(payload, str):
        payload_bytes = payload.encode()
    elif payload is None:
        payload_bytes = b''
    else:
        payload_bytes = payload
    try:
        headers = signer.generate_headers(
            params=params,
            data=payload_bytes,
            version_code=version_code,
            version_name=version_name,
            unix=unix,
            device=device,
            cookie=cookie,
        )
    except Exception as e:
        raise TikTokAPIError(f'Firma reale fallita: {e}')
    # Verifica che la firma sia completa: senza questi il WAF risponde 200 vuoto
    lower = {k.lower() for k in headers}
    missing = [h for h in ('x-gorgon', 'x-argus', 'x-khronos', 'x-ladon') if h not in lower]
    if missing:
        raise TikTokAPIError(f'Firma incompleta, mancano: {missing}')
    return headers


def _generate_xgorgon(url_path, query_str, body_str=''):
    # ispirazione Ilon + captcha_solver: md5(url+query+body) -> base64
    try:
        data = url_path.encode('utf-8')
        if query_str:
            data += query_str.encode('utf-8')
        if body_str:
            data += body_str.encode('utf-8')
        h = hashlib.md5(data).digest()
        result = b'\x02' + h
        return base64.b64encode(result).decode()
    except Exception:
        return base64.b64encode(b'\x02' + hashlib.md5(str(time.time()).encode()).digest()).decode()

def _generate_xargus(device, url_path=''):
    try:
        ts = int(time.time())
        device_id = device.get('device_id', '') if isinstance(device, dict) else ''
        install_id = device.get('install_id', device_id)
        raw = f'{device_id}{install_id}{ts}{url_path}'
        h = hashlib.sha256(raw.encode()).digest()
        return base64.b64encode(h).decode()
    except Exception:
        return base64.b64encode(hashlib.sha256(str(time.time()).encode()).digest()).decode()

def _generate_xladon(body_str=''):
    try:
        # X-Ladon is often base64 of body hash
        h = hashlib.md5(body_str.encode()).hexdigest()
        return base64.b64encode(h.encode()).decode()
    except Exception:
        return ''

def _generate_xkhronos():
    return str(int(time.time()))


def _build_query_string(device, extra_params=None, fixed_time=None):
    query = _generate_query(device, extra_params, fixed_time=fixed_time)
    return urlencode(sorted(query.items()))


def _device_cookie_string(session):
    """Serializza i cookie di sessione per includerli nella firma Gorgon."""
    try:
        parts = [f'{c.name}={c.value}' for c in session.cookies]
        return '; '.join(parts) if parts else None
    except Exception:
        return None


def _build_headers(device, query_params, url_path='', payload_bytes=b'', signer=None, extra_headers=None, session=None):
    """Costruisce header usando LA STESSA query dell'URL + body reale.

    query_params: dict già generato dal caller (non viene rigenerato qui).
    payload_bytes: body reale del POST (stessi byte inviati e firmati).
    Non genera mai firme fake: se il signer manca/fallisce, solleva.
    """
    if not isinstance(query_params, dict):
        raise TikTokAPIError('query_params deve essere il dict usato per l’URL')
    app_info = device.get('app_info', {})
    try:
        version_code = int(app_info.get('version_code', '340002'))
    except (ValueError, TypeError):
        version_code = 340002
    version_name = app_info.get('app_version', '34.0.2')
    headers = {
        'User-Agent': USER_AGENT_TPL.format(
            version_code=app_info.get('version_code', '340002'),
            android_ver=device.get('android_version', '13'),
            locale=device.get('locale', 'en_US'),
            model=device.get('model', 'SM-G991B'),
            build_id=_random_build_id(),
        ),
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': device.get('locale', 'en_US').replace('_', '-') + ',en;q=0.9',
        'passport-sdk-version': '19',
        'sdk-version': '2',
    }
    cookie_str = _device_cookie_string(session) if session is not None else None
    # Firma reale sugli STESSI params + STESSO body + STESSO unix della query
    sign_headers = _sign_request_tiktoksigner(
        signer, query_params, payload_bytes,
        version_code=version_code, version_name=version_name,
        device=device, cookie=cookie_str,
    )
    headers.update(sign_headers)

    if extra_headers:
        headers.update(extra_headers)
    return headers


class SSLAdapter(HTTPAdapter):
    def __init__(self, ssl_context=None, **kwargs):
        self.ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        if self.ssl_context:
            kwargs['ssl_context'] = self.ssl_context
        super().init_poolmanager(*args, **kwargs)


class TikTokClient:
    def __init__(self, device, proxy=None):
        self.device = device
        self.proxy = proxy
        self.session = requests.Session()
        self.domain = random.choice(DOMAIN_GROUPS['useast1a'])
        self.passport_domain = PASSPORT_DOMAINS['useast1a']
        self.captcha_domain = random.choice(CAPTCHA_DOMAINS)
        self.region = device.get('region', 'US')
        self.locale = device.get('locale', 'en_US')
        self.language = device.get('language', 'en')
        self.x_token = ''
        self.cookie_str = ''
        self.user_data = {}
        self.signer = None
        if not SIGNER_AVAILABLE:
            raise TikTokAPIError(
                'tiktok-signer non installato: pip install tiktok-signer (niente fallback)'
            )
        try:
            # TikTokSigner usa metodi di classe + profilo globale: lo impostiamo
            # una volta per device. La firma vera viene poi richiesta per-call
            # con gli STESSI params/body/unix (vedi _sign_request_tiktoksigner).
            TikTokSigner.set_device(device)
            self.signer = TikTokSigner
        except Exception as e:
            raise TikTokAPIError(f'TikTokSigner init fallita: {e}')
        self._setup_session()

    def _setup_session(self):
        ctx = ssl.create_default_context()
        ciphers = (
            'ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:'
            'ECDHE+AES256:ECDHE+AES128:DHE+AES256:DHE+AES128:'
            'RSA+AESGCM:RSA+AES:!aNULL:!eNULL:!MD5:!DSS:!RC4'
        )
        ctx.set_ciphers(ciphers)
        # Ottimizzato per parallelo: pool grande + retry + keep-alive (ispirazione zefoy_client)
        adapter = SSLAdapter(ssl_context=ctx, pool_connections=20, pool_maxsize=50, max_retries=2)
        self.session.mount('https://', adapter)
        self.session.mount('http://', HTTPAdapter(pool_connections=20, pool_maxsize=50, max_retries=2))
        # Headers comuni per WAF bypass
        self.session.headers.update({
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        })
        if self.proxy:
            proxy = self.proxy.strip()
            if '://' not in proxy:
                proxy = f'http://{proxy}'
            scheme = proxy.split('://', 1)[0].lower()
            if scheme not in ('http', 'https', 'socks5', 'socks5h', 'socks4', 'socks4a'):
                raise TikTokAPIError(f'Proxy non supportato: {self.proxy!r}')
            if scheme.startswith('socks'):
                try:
                    import urllib3.contrib.socks  # noqa: F401
                except ImportError:
                    raise TikTokAPIError(
                        'Proxy SOCKS richiede urllib3[socks]/PySocks: pip install pysocks'
                    )
            self.session.proxies = {'https': proxy, 'http': proxy}
            self.proxy = proxy
        # Nota: requests.Session non ha attributo timeout → il timeout va passato
        # a ogni get/post (già timeout=15). Niente self.session.timeout.
        self.default_timeout = 15

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def _update_cookies_from_response(self, resp):
        if not hasattr(resp, 'headers'):
            return
        tt_token = resp.headers.get('x-tt-token', '')
        if tt_token:
            self.x_token = tt_token
        # Usa il cookie-jar di requests (gestisce Expires=Wed, ... con virgole,
        # domain/path/secure). Il vecchio split(',') corrompeva i cookie e
        # perdeva tt-target-idc. Resta un fallback manuale solo se jar vuoto.
        try:
            jar_cookies = getattr(resp, 'cookies', None)
            if jar_cookies:
                self.session.cookies.update(jar_cookies)
        except Exception:
            pass
        set_cookie = resp.headers.get('set-cookie', '')
        if set_cookie and len(self.session.cookies) == 0:
            for part in set_cookie.split(';'):
                part = part.strip()
                if not part or '=' not in part or ',' in part.split('=')[0]:
                    continue
                k, v = part.split('=', 1)
                k = k.strip()
                v = v.strip().split(';')[0]
                if k and v and k.lower() not in ('expires', 'path', 'domain', 'max-age'):
                    try:
                        self.session.cookies.set(k, v)
                    except Exception:
                        pass

    def _build_url(self, endpoint, query_params):
        """Costruisce l'URL dalla query GIÀ generata (non ne crea una nuova)."""
        query_str = urlencode(sorted(query_params.items()))
        return f'https://{self.domain}/{endpoint}?{query_str}'

    def _request(self, method, endpoint, data=None, extra_headers=None, extra_params=None):
        # UNICA query per URL + firma: stessi timestamp/_rticket, niente mismatch
        query = _generate_query(self.device, extra_params)
        url = self._build_url(endpoint, query)
        url_path = f'/{endpoint}'
        if method == 'GET':
            payload_bytes = b''
        elif isinstance(data, str):
            payload_bytes = data.encode()
        elif data is None:
            payload_bytes = b''
        else:
            payload_bytes = data
        headers = _build_headers(
            self.device, query, url_path, payload_bytes,
            signer=self.signer, extra_headers=extra_headers, session=self.session,
        )
        if self.x_token:
            headers['X-Tt-Token'] = self.x_token
        try:
            if method == 'GET':
                resp = self.session.get(url, headers=headers, timeout=15)
            else:
                resp = self.session.post(url, headers=headers, data=data, timeout=15)
            self._update_cookies_from_response(resp)
            return self._handle_response(resp)
        except requests.RequestException as e:
            raise TikTokAPIError(f'Request failed: {e}')

    def _handle_response(self, resp):
        if resp.status_code in (301, 302, 303):
            return {'status_code': 0}
        try:
            data = resp.json()
        except ValueError:
            raise TikTokAPIError(f'Invalid JSON: {resp.text[:200]}')
        status_code = data.get('status_code', data.get('error_code', 0))
        if status_code != 0:
            msg = data.get('status_msg', data.get('description', 'Unknown error'))
            raise TikTokAPIError(f'API error: {msg}', code=status_code, response=data)
        return data

    def _build_passport_headers(self, extra_headers=None):
        headers = {
            'User-Agent': USER_AGENT_TPL.format(
                version_code=self.device.get('app_info', {}).get('version_code', '340002'),
                android_ver=self.device.get('android_version', '13'),
                locale=self.device.get('locale', 'en_US'),
                model=self.device.get('model', 'SM-G991B'),
                build_id=_random_build_id(),
            ),
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Accept': 'application/json',
            'passport-sdk-version': '19',
        }
        if self.x_token:
            headers['X-Tt-Token'] = self.x_token
        if self.cookie_str:
            headers['Cookie'] = self.cookie_str
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _passport_request(self, endpoint, payload=None, extra_query=None):
        # UNICA query per URL + firma (prima erano due _generate_query diverse
        # con timestamp/_rticket diversi → firma invalida → 200 vuoto dal WAF)
        query_params = _generate_query(self.device, extra_query)
        query_str = urlencode(sorted(query_params.items()))
        url = f'https://{self.passport_domain}/{endpoint}?{query_str}'
        headers = self._build_passport_headers()

        app_info = self.device.get('app_info', {})
        try:
            version_code = int(app_info.get('version_code', '340002'))
        except (ValueError, TypeError):
            version_code = 340002
        version_name = app_info.get('app_version', '34.0.2')
        cookie_str = _device_cookie_string(self.session)
        # Stesso dict query + stesso body reale + stesso unix per la firma
        sign_headers = _sign_request_tiktoksigner(
            self.signer, query_params, payload or '',
            version_code=version_code, version_name=version_name,
            device=self.device, cookie=cookie_str,
        )
        headers.update(sign_headers)

        resp = self.session.post(url, headers=headers, data=payload, timeout=15)
        # Rileva subito WAF/blocco: prima era resp.json() → 'Expecting value char 0' senza contesto
        body = getattr(resp, 'text', '') or ''
        if resp.status_code != 200:
            raise TikTokAPIError(
                f'Passport {endpoint} HTTP {resp.status_code} (body {len(body)} chars: {body[:200]!r})'
            )
        if len(body.strip()) == 0:
            raise TikTokAPIError(
                f'Passport {endpoint} risposta vuota (WAF/firma scartata, body 0 bytes). '
                f'Verifica firma X-Gorgon/X-Argus e query condivisa.'
            )
        ctype = resp.headers.get('Content-Type', '')
        if 'json' not in ctype.lower():
            # TikTok a volte ritorna json senza content-type: prova comunque il parse,
            # ma con errore esplicito se fallisce invece di 'Expecting value' generico
            try:
                resp.json()
            except ValueError:
                raise TikTokAPIError(
                    f'Passport {endpoint} non-JSON (Content-Type={ctype!r}, body {len(body)}: {body[:200]!r})'
                )
        self._update_cookies_from_response(resp)
        return resp

    def get_app_region(self):
        try:
            resp = self._passport_request('passport/app/region/')
        except TikTokAPIError as e:
            log.warning('get_app_region fallita (continuo con dominio di default): %s', e)
            return None
        try:
            data = resp.json()
        except ValueError:
            log.warning(
                'get_app_region body non-JSON (status=%d len=%d: %r), uso default',
                resp.status_code, len(getattr(resp, 'text', '') or ''),
                (getattr(resp, 'text', '') or '')[:200],
            )
            return None
        if 'data' in data:
            domain_info = data['data']
            new_domain = domain_info.get('domain', '')
            if new_domain:
                self.domain = new_domain
            captcha = domain_info.get('captcha_domain', '')
            if captcha:
                self.captcha_domain = captcha
            return domain_info
        log.warning('get_app_region: chiave data assente in %r', str(data)[:200])
        return None

    def device_register(self):
        # Il passport si aspetta form-urlencoded, non JSON (prima: json.dumps → 400/empty)
        try:
            payload = urlencode({
                'device_id': self.device.get('device_id', ''),
                'install_id': self.device.get('install_id', ''),
                'openudid': self.device.get('openudid', ''),
                'device_type': self.device.get('model', 'SM-G991B'),
                'os_version': self.device.get('android_version', '13'),
            })
            resp = self._passport_request('passport/device/register/', payload=payload)
        except TikTokAPIError as e:
            log.warning('device_register fallita (continuo con device locale): %s', e)
            return None
        try:
            result = resp.json()
        except ValueError:
            log.warning(
                'device_register body non-JSON (status=%d len=%d)',
                resp.status_code, len(getattr(resp, 'text', '') or ''),
            )
            return None
        if result.get('device_id_str'):
            self.device['device_id'] = result['device_id_str']
        if result.get('install_id_str'):
            self.device['install_id'] = result['install_id_str']
        return result

    def register_account(self, email, password):
        self.get_app_region()
        self.device_register()

        birthday = f'{random.randint(1990, 2005)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}'
        self._register_payload = (
            f'password={_xor_encode(password)}&'
            f'fixed_mix_mode=1&'
            f'rules_version=v2&'
            f'mix_mode=1&'
            f'multi_login=1&'
            f'email={_xor_encode(email)}&'
            f'account_sdk_source=app&'
            f'birthday={birthday}&'
            f'multi_signup=0'
        )

        extra_query = {
            'passport-sdk-version': '5030190',
            'uoo': '0',
            'cronet_version': '',
            'ttnet_version': '',
            'use_store_region_cookie': '1',
        }

        try:
            resp = self._passport_request('passport/email/register/v2/', payload=self._register_payload, extra_query=extra_query)
            data = resp.json()
            result = self._handle_login_response(resp, data)

            if result and result.get('status') == 'captcha_required':
                log.info('Captcha required during registration, solving...')
                solver = TikTokCaptchaSolver(self.device, proxy=self.proxy)
                captcha_result = solver.solve()
                if captcha_result:
                    log.info('Captcha solved! Retrying registration...')
                    resp = self._passport_request('passport/email/register/v2/', payload=self._register_payload, extra_query=extra_query)
                    data = resp.json()
                    result = self._handle_login_response(resp, data)

            return result
        except Exception as e:
            log.error('Registration failed: %s', e)
            return None

    def send_verification_code(self, email):
        payload = (
            f'email={_xor_encode(email)}&'
            f'type=1&'
            f'account_sdk_source=app&'
            f'mix_mode=1&'
            f'multi_login=1'
        )

        extra_query = {
            'passport-sdk-version': '5030190',
            'uoo': '0',
        }

        try:
            resp = self._passport_request('passport/email/send_code/', payload=payload, extra_query=extra_query)
            data = resp.json()
            error_code = data.get('error_code', 0)
            if error_code == 0:
                log.info('Verification code sent to %s', email)
                return {'status': 'success', 'data': data}
            else:
                msg = data.get('description', 'Unknown error')
                log.error('Send code failed: %s (error_code=%d)', msg, error_code)
                return {'status': 'error', 'error_code': error_code, 'message': msg, 'data': data}
        except Exception as e:
            log.error('Send verification code failed: %s', e)
            return {'status': 'error', 'message': str(e)}

    def submit_verification_code(self, email, code):
        payload = (
            f'email={_xor_encode(email)}&'
            f'code={code}&'
            f'account_sdk_source=app&'
            f'mix_mode=1&'
            f'multi_login=1'
        )

        extra_query = {
            'passport-sdk-version': '5030190',
            'uoo': '0',
        }

        try:
            resp = self._passport_request('passport/email/verify/', payload=payload, extra_query=extra_query)
            data = resp.json()
            error_code = data.get('error_code', 0)

            if error_code in (1107, 1105, 1108):
                log.info('Captcha required during verification, solving...')
                solver = TikTokCaptchaSolver(self.device, proxy=self.proxy)
                captcha_result = solver.solve()
                if captcha_result:
                    log.info('Captcha solved! Retrying verification...')
                    resp = self._passport_request('passport/email/verify/', payload=payload, extra_query=extra_query)
                    data = resp.json()
                    error_code = data.get('error_code', 0)

            if error_code != 0 and error_code != 2000:
                msg = data.get('description', 'Unknown error')
                log.error('Verify code failed: %s (error_code=%d)', msg, error_code)
                return {'status': 'error', 'error_code': error_code, 'message': msg, 'data': data}

            user_data = data.get('data', {})
            if user_data and user_data.get('user', {}).get('uid'):
                self.user_data = user_data
                self.x_token = resp.headers.get('x-tt-token', self.x_token)

                tt_target_idc = ''
                for cookie_str in resp.headers.get('set-cookie', '').split(','):
                    if 'tt-target-idc' in cookie_str:
                        try:
                            tt_target_idc = cookie_str.split('tt-target-idc=')[1].split(';')[0].strip()
                        except (IndexError, ValueError):
                            pass
                        break

                if tt_target_idc and tt_target_idc in DOMAIN_GROUPS:
                    self.domain = random.choice(DOMAIN_GROUPS[tt_target_idc])
                    self.passport_domain = PASSPORT_DOMAINS.get(tt_target_idc, self.passport_domain)

                account_info = {
                    'status': 'active',
                    'user_id': str(user_data.get('user', {}).get('uid', '')),
                    'sec_uid': user_data.get('user', {}).get('sec_uid', ''),
                    'username': user_data.get('user', {}).get('unique_id', ''),
                    'nickname': user_data.get('user', {}).get('nickname', ''),
                    'x_tt_token': self.x_token,
                    'cookies': dict(self.session.cookies),
                    'domain': self.domain,
                    'passport_domain': self.passport_domain,
                    'tt_target_idc': tt_target_idc,
                    'device': self.device,
                }
                log.info('Email verified, account created: %s', account_info.get('username', ''))
                return {'status': 'success', 'account': account_info, 'data': user_data}

            log.warning('Verification succeeded but no user data returned')
            return {'status': 'partial', 'data': data}

        except Exception as e:
            log.error('Submit verification code failed: %s', e)
            return {'status': 'error', 'message': str(e)}

    def register_with_email_verification(self, email, password, code_getter=None, timeout=120):
        result = self.register_account(email, password)

        if not result:
            return None

        status = result.get('status', 'error')

        if status == 'success':
            return result

        if status == 'captcha_required':
            log.warning('Captcha required, already handled in register_account')
            return result

        if status == 'verification_required':
            log.info('Registration requires email verification for: %s', email)
        elif status == 'error':
            error_code = result.get('error_code', 0)
            if error_code == 1005:
                log.info('Email verification required (error_code=1005) for: %s', email)
            else:
                log.info('Registration returned error (code=%d), attempting verification anyway for: %s', error_code, email)
        else:
            log.info('Registration status=%s, attempting verification for: %s', status, email)

        send_result = self.send_verification_code(email)
        if not send_result or send_result.get('status') != 'success':
            log.error('Failed to send verification code')
            return None

        if code_getter:
            log.info('Waiting for verification code via callback...')
            code = code_getter(email, timeout=timeout)
        else:
            log.warning('No code_getter provided, cannot auto-verify')
            return {'status': 'verification_required', 'email': email, 'data': result.get('data')}

        if not code:
            log.error('No verification code received within timeout')
            return None

        log.info('Got verification code: %s, submitting...', code)
        verify_result = self.submit_verification_code(email, code)
        return verify_result

    def login(self, username, password, is_email=True):
        self.get_app_region()

        if is_email:
            payload = (
                f'password={_xor_encode(password)}&'
                f'account_sdk_source=app&'
                f'multi_login=1&'
                f'mix_mode=1&'
                f'email={_xor_encode(username)}'
            )
        else:
            payload = (
                f'password={_xor_encode(password)}&'
                f'account_sdk_source=app&'
                f'multi_login=1&'
                f'mix_mode=1&'
                f'username={_xor_encode(username)}'
            )

        extra_query = {'passport-sdk-version': '19', 'uoo': '0'}

        try:
            resp = self._passport_request('passport/user/login/', payload=payload, extra_query=extra_query)
            data = resp.json()
            result = self._handle_login_response(resp, data)

            if result and result.get('status') == 'captcha_required':
                log.info('Captcha required during login, solving...')
                solver = TikTokCaptchaSolver(self.device, proxy=self.proxy)
                captcha_result = solver.solve()
                if captcha_result:
                    log.info('Captcha solved! Retrying login...')
                    resp = self._passport_request('passport/user/login/', payload=payload, extra_query=extra_query)
                    data = resp.json()
                    result = self._handle_login_response(resp, data)

            return result
        except Exception as e:
            log.error('Login failed: %s', e)
            return None

    def _handle_login_response(self, resp, data):
        error_code = data.get('error_code', 0)
        if error_code in (1107, 1105, 1108):
            log.info('Captcha required (error_code=%d), attempting auto-solve...', error_code)
            return {'status': 'captcha_required', 'error_code': error_code, 'data': data}

        if error_code == 1005:
            log.info('Email verification required (error_code=1005)')
            return {'status': 'verification_required', 'error_code': error_code, 'data': data}

        if error_code != 0 and error_code != 2000:
            return {'status': 'error', 'error_code': error_code, 'message': data.get('description', ''), 'data': data}

        user_data = data.get('data', {})
        if not user_data or not user_data.get('user', {}).get('uid'):
            return {'status': 'error', 'message': 'No user data in response', 'data': data}

        self.user_data = user_data
        self.x_token = resp.headers.get('x-tt-token', self.x_token)

        tt_target_idc = ''
        for cookie_str in resp.headers.get('set-cookie', '').split(','):
            if 'tt-target-idc' in cookie_str:
                try:
                    tt_target_idc = cookie_str.split('tt-target-idc=')[1].split(';')[0].strip()
                except (IndexError, ValueError):
                    pass
                break

        if tt_target_idc and tt_target_idc in DOMAIN_GROUPS:
            self.domain = random.choice(DOMAIN_GROUPS[tt_target_idc])
            self.passport_domain = PASSPORT_DOMAINS.get(tt_target_idc, self.passport_domain)

        account_info = {
            'status': 'active',
            'user_id': str(user_data.get('user', {}).get('uid', '')),
            'sec_uid': user_data.get('user', {}).get('sec_uid', ''),
            'username': user_data.get('user', {}).get('unique_id', ''),
            'nickname': user_data.get('user', {}).get('nickname', ''),
            'x_tt_token': self.x_token,
            'cookies': dict(self.session.cookies),
            'domain': self.domain,
            'passport_domain': self.passport_domain,
            'tt_target_idc': tt_target_idc,
            'device': self.device,
        }
        return {'status': 'success', 'account': account_info, 'data': user_data}

    def _solve_captcha_and_retry(self, original_fn, *args, max_attempts=3, **kwargs):
        solver = TikTokCaptchaSolver(self.device, proxy=self.proxy)
        for attempt in range(max_attempts):
            log.info('Captcha solve attempt %d/%d', attempt + 1, max_attempts)
            result = solver.solve()
            if result:
                log.info('Captcha solved! Retrying operation...')
                return original_fn(*args, **kwargs)
            if attempt < max_attempts - 1:
                time.sleep(random.uniform(2, 5))
        log.error('All captcha solve attempts failed')
        return None

    def _require_login(self):
        """Blocca follow/like/view anonimi: senza login TikTok risponde errore/sessione."""
        if self.user_data and self.user_data.get('user', {}).get('uid'):
            return
        has_cookies = len(self.session.cookies) > 0
        if not (self.x_token and has_cookies):
            raise TikTokAPIError(
                'Login richiesto: nessun x_tt_token/cookie di sessione. '
                'Fai login/register prima di follow/like/view.'
            )

    def follow(self, target_user_id):
        # L'endpoint vuole l'uid NUMERICO, non il secUid 'MS4w...'.
        # Passare un secUid garantiva errore server → rifiuto esplicito.
        if not target_user_id:
            raise TikTokAPIError('follow: target_user_id mancante (None/vuoto)')
        if isinstance(target_user_id, str) and target_user_id.startswith('MS4w'):
            raise TikTokAPIError(
                'follow: serve uid numerico, non secUid (MS4w...). '
                'Risolvi uid numerico del profilo prima di chiamare follow.'
            )
        self._require_login()
        data = {'to_user_id': target_user_id, 'type': '1', 'source': '6'}
        return self._request('POST', ENDPOINTS['follow'], data=urlencode(data))

    def unfollow(self, target_user_id):
        if not target_user_id:
            raise TikTokAPIError('unfollow: target_user_id mancante')
        if isinstance(target_user_id, str) and target_user_id.startswith('MS4w'):
            raise TikTokAPIError('unfollow: serve uid numerico, non secUid (MS4w...)')
        self._require_login()
        data = {'to_user_id': target_user_id, 'type': '0', 'source': '6'}
        return self._request('POST', ENDPOINTS['unfollow'], data=urlencode(data))

    def like(self, aweme_id):
        if not aweme_id:
            raise TikTokAPIError('like: aweme_id mancante')
        self._require_login()
        data = {'aweme_id': aweme_id, 'type': '1', 'source': '6'}
        return self._request('POST', ENDPOINTS['like'], data=urlencode(data))

    def unlike(self, aweme_id):
        if not aweme_id:
            raise TikTokAPIError('unlike: aweme_id mancante')
        self._require_login()
        data = {'aweme_id': aweme_id, 'type': '0', 'source': '6'}
        return self._request('POST', ENDPOINTS['unlike'], data=urlencode(data))

    def view(self, aweme_id):
        if not aweme_id:
            raise TikTokAPIError('view: aweme_id mancante')
        self._require_login()
        data = {'aweme_id': aweme_id, 'action': '0'}
        return self._request('POST', ENDPOINTS['view'], data=urlencode(data))

    def get_user_info(self, sec_uid):
        extra_params = {'sec_user_id': sec_uid}
        return self._request('GET', ENDPOINTS['user_info'], extra_params=extra_params)

    def get_user_videos(self, sec_uid, count=20):
        extra_params = {'sec_user_id': sec_uid, 'count': str(count), 'max_cursor': '0'}
        return self._request('GET', ENDPOINTS['feed'], extra_params=extra_params)

    def search_user(self, keyword):
        extra_params = {'keyword': keyword, 'count': '10', 'cursor': '0', 'search_source': 'discover', 'type': '1'}
        return self._request('GET', ENDPOINTS['search'], extra_params=extra_params)

    def get_hot_videos(self):
        return self._request('GET', ENDPOINTS['hot'])
