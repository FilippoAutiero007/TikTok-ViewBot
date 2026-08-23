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

from .captcha_solver import TikTokCaptchaSolver

log = logging.getLogger(__name__)

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


def _generate_query(device, extra_params=None):
    ts = int(time.time())
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
        '_rticket': str(int(time.time() * 1000)),
        'current_region': device.get('region', 'US'),
        'os_api': device.get('sdk_version', '33'),
        'device_brand': device.get('brand', 'samsung'),
        'timezone_name': device.get('timezone', 'America/New_York'),
        'timestamp': str(ts),
        'ts': str(ts),
        'locale': device.get('locale', 'en_US'),
        'language': device.get('language', 'en'),
        'ac': 'wifi',
        'dpi': device.get('dpi', '420'),
    }
    if extra_params:
        params.update(extra_params)
    return params


def _generate_xgorgon(url_path, query_str, body_str=''):
    data = url_path.encode('utf-8')
    if query_str:
        data += query_str.encode('utf-8')
    if body_str:
        data += body_str.encode('utf-8')
    h = hashlib.md5(data).digest()
    result = b'\x02' + h
    return base64.b64encode(result).decode()


def _generate_xargus(device, url_path=''):
    ts = int(time.time())
    device_id = device.get('device_id', '')
    install_id = device.get('install_id', device_id)
    raw = f'{device_id}{install_id}{ts}{url_path}'
    h = hashlib.sha256(raw.encode()).digest()
    return base64.b64encode(h).decode()


def _generate_xkhronos():
    return str(int(time.time()))


def _build_query_string(device, extra_params=None):
    query = _generate_query(device, extra_params)
    return urlencode(sorted(query.items()))


def _build_headers(device, url_path='', extra_headers=None):
    query = _generate_query(device)
    query_str = urlencode(sorted(query.items()))
    headers = {
        'User-Agent': USER_AGENT_TPL.format(
            version_code=device.get('app_info', {}).get('version_code', '340002'),
            android_ver=device.get('android_version', '13'),
            locale=device.get('locale', 'en_US'),
            model=device.get('model', 'SM-G991B'),
            build_id=_random_build_id(),
        ),
        'Accept-Encoding': 'gzip',
        'Connection': 'keep-alive',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Tt-Token': '',
        'X-SS-Stub': '',
        'Accept': 'application/json',
        'X-Gorgon': _generate_xgorgon(url_path, query_str),
        'X-Argus': _generate_xargus(device, url_path),
        'X-Khronos': _generate_xkhronos(),
        'passport-sdk-version': '19',
    }
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
        self._setup_session()

    def _setup_session(self):
        ctx = ssl.create_default_context()
        ciphers = (
            'ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:'
            'ECDHE+AES256:ECDHE+AES128:DHE+AES256:DHE+AES128:'
            'RSA+AESGCM:RSA+AES:!aNULL:!eNULL:!MD5:!DSS:!RC4'
        )
        ctx.set_ciphers(ciphers)
        adapter = SSLAdapter(ssl_context=ctx)
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)
        if self.proxy:
            self.session.proxies = {'https': self.proxy, 'http': self.proxy}

    def _update_cookies_from_response(self, resp):
        if not hasattr(resp, 'headers'):
            return
        tt_token = resp.headers.get('x-tt-token', '')
        if tt_token:
            self.x_token = tt_token
        set_cookie = resp.headers.get('set-cookie', '')
        if set_cookie:
            for part in set_cookie.split(','):
                if '=' in part:
                    k, v = part.split('=', 1)
                    k = k.strip().split(';')[0]
                    v = v.strip().split(';')[0]
                    if k and v:
                        self.session.cookies.set(k, v, domain='.tiktokv.com')

    def _build_url(self, endpoint, extra_params=None):
        query = _generate_query(self.device, extra_params)
        query_str = urlencode(sorted(query.items()))
        return f'https://{self.domain}/{endpoint}?{query_str}'

    def _request(self, method, endpoint, data=None, extra_headers=None, extra_params=None):
        url = self._build_url(endpoint, extra_params)
        url_path = f'/{endpoint}'
        headers = _build_headers(self.device, url_path, extra_headers)
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
        query = _build_query_string(self.device, extra_query)
        url_path = f'/{endpoint}'
        url = f'https://{self.passport_domain}/{endpoint}?{query}'
        headers = self._build_passport_headers()
        headers['X-Gorgon'] = _generate_xgorgon(url_path, query)
        headers['X-Argus'] = _generate_xargus(self.device, url_path)
        headers['X-Khronos'] = _generate_xkhronos()
        resp = self.session.post(url, headers=headers, data=payload, timeout=15)
        self._update_cookies_from_response(resp)
        return resp

    def get_app_region(self):
        try:
            resp = self._passport_request('passport/app/region/v2/')
            data = resp.json()
            if 'data' in data:
                domain_info = data['data']
                new_domain = domain_info.get('domain', '')
                if new_domain:
                    self.domain = new_domain
                captcha = domain_info.get('captcha_domain', '')
                if captcha:
                    self.captcha_domain = captcha
                return domain_info
            return None
        except Exception as e:
            log.debug('get_app_region failed: %s', e)
            return None

    def device_register(self):
        try:
            payload = json.dumps(self.device)
            resp = self._passport_request('passport/device/register/v2/', payload=payload)
            result = resp.json()
            if result.get('device_id_str'):
                self.device['device_id'] = result['device_id_str']
            if result.get('install_id_str'):
                self.device['install_id'] = result['install_id_str']
            return result
        except Exception as e:
            log.debug('device_register failed: %s', e)
            return None

    def register_account(self, email, password):
        self.get_app_region()
        self.device_register()

        birthday = f'{random.randint(1990, 2005)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}'
        payload = (
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
            resp = self._passport_request('passport/email/register/v2/', payload=payload, extra_query=extra_query)
            data = resp.json()
            result = self._handle_login_response(resp, data)

            if result and result.get('status') == 'captcha_required':
                log.info('Captcha required during registration, solving...')
                solver = TikTokCaptchaSolver(self.device, proxy=self.proxy)
                captcha_result = solver.solve()
                if captcha_result:
                    log.info('Captcha solved! Retrying registration...')
                    resp = self._passport_request('passport/email/register/v2/', payload=payload, extra_query=extra_query)
                    data = resp.json()
                    result = self._handle_login_response(resp, data)

            return result
        except Exception as e:
            log.error('Registration failed: %s', e)
            return None

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
            resp = self._passport_request('passport/user/login/v2/', payload=payload, extra_query=extra_query)
            data = resp.json()
            result = self._handle_login_response(resp, data)

            if result and result.get('status') == 'captcha_required':
                log.info('Captcha required during login, solving...')
                solver = TikTokCaptchaSolver(self.device, proxy=self.proxy)
                captcha_result = solver.solve()
                if captcha_result:
                    log.info('Captcha solved! Retrying login...')
                    resp = self._passport_request('passport/user/login/v2/', payload=payload, extra_query=extra_query)
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

    def follow(self, target_sec_uid):
        data = {'to_user_id': target_sec_uid, 'type': '1', 'source': '6'}
        return self._request('POST', ENDPOINTS['follow'], data=urlencode(data))

    def unfollow(self, target_sec_uid):
        data = {'to_user_id': target_sec_uid, 'type': '0', 'source': '6'}
        return self._request('POST', ENDPOINTS['unfollow'], data=urlencode(data))

    def like(self, aweme_id):
        data = {'aweme_id': aweme_id, 'type': '1', 'source': '6'}
        return self._request('POST', ENDPOINTS['like'], data=urlencode(data))

    def unlike(self, aweme_id):
        data = {'aweme_id': aweme_id, 'type': '0', 'source': '6'}
        return self._request('POST', ENDPOINTS['unlike'], data=urlencode(data))

    def view(self, aweme_id):
        data = {'aweme_id': aweme_id, 'action': '0'}
        return self._request('POST', ENDPOINTS['view'], data=urlencode(data))

    def get_user_info(self, sec_uid):
        params = {'sec_user_id': sec_uid}
        return self._request('GET', ENDPOINTS['user_info'], params=params)

    def get_user_videos(self, sec_uid, count=20):
        params = {'sec_user_id': sec_uid, 'count': str(count), 'max_cursor': '0'}
        return self._request('GET', ENDPOINTS['feed'], params=params)

    def search_user(self, keyword):
        params = {'keyword': keyword, 'count': '10', 'cursor': '0', 'search_source': 'discover', 'type': '1'}
        return self._request('GET', ENDPOINTS['search'], params=params)

    def get_hot_videos(self):
        return self._request('GET', ENDPOINTS['hot'])
