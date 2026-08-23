import base64
import hashlib
import json
import logging
import random
import time
from hashlib import md5
from urllib.parse import urlencode

import cv2
import numpy as np
import requests

log = logging.getLogger(__name__)

try:
    from TikSign import Argus
    from TikSign.ladon import Ladon
    from TikSign.gorgon import xgorgon
    TIKSIGN_AVAILABLE = True
except ImportError:
    TIKSIGN_AVAILABLE = False
    log.warning('TikSign not installed - captcha solver will use fallback signing')


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


class ChaCha20:
    def __init__(self, key, nonce, counter=0):
        if len(key) != 32 or len(nonce) != 12:
            raise ValueError('Invalid key or nonce length')
        self.k = key
        self.n = nonce
        self.c = counter

    @staticmethod
    def _r(v, n):
        return ((v << n) & 0xFFFFFFFF) | (v >> (32 - n))

    @staticmethod
    def _qr(s, a, b, c, d):
        s[a] = (s[a] + s[b]) & 0xFFFFFFFF
        s[d] ^= s[a]
        s[d] = ChaCha20._r(s[d], 16)
        s[c] = (s[c] + s[d]) & 0xFFFFFFFF
        s[b] ^= s[c]
        s[b] = ChaCha20._r(s[b], 12)
        s[a] = (s[a] + s[b]) & 0xFFFFFFFF
        s[d] ^= s[a]
        s[d] = ChaCha20._r(s[d], 8)
        s[c] = (s[c] + s[d]) & 0xFFFFFFFF
        s[b] ^= s[c]
        s[b] = ChaCha20._r(s[b], 7)

    def _block(self, ctr):
        s = [0x61707865, 0x3320646e, 0x79622d32, 0x6b206574]
        s += [int.from_bytes(self.k[i * 4:(i + 1) * 4], 'little') for i in range(8)]
        s.append(ctr & 0xFFFFFFFF)
        s += [int.from_bytes(self.n[i * 4:(i + 1) * 4], 'little') for i in range(3)]
        w = s[:]
        for _ in range(10):
            self._qr(w, 0, 4, 8, 12)
            self._qr(w, 1, 5, 9, 13)
            self._qr(w, 2, 6, 10, 14)
            self._qr(w, 3, 7, 11, 15)
            self._qr(w, 0, 5, 10, 15)
            self._qr(w, 1, 6, 11, 12)
            self._qr(w, 2, 7, 8, 13)
            self._qr(w, 3, 4, 9, 14)
        return b''.join(((w[i] + s[i]) & 0xFFFFFFFF).to_bytes(4, 'little') for i in range(16))

    def _ks(self):
        ctr = self.c
        while True:
            block = self._block(ctr)
            ctr = (ctr + 1) & 0xFFFFFFFF
            for b in block:
                yield b

    def encrypt(self, data):
        ks = self._ks()
        return bytes([b ^ next(ks) for b in data])


def edata_encrypt(txt):
    import secrets
    d = txt.encode('utf-8')
    k = secrets.token_bytes(32)
    n = secrets.token_bytes(12)
    c = ChaCha20(k, n, 0)
    ct = c.encrypt(d)
    raw = b'\x01' + k + n + ct
    return base64.b64encode(raw).decode()


def edata_decrypt(txt):
    raw = base64.b64decode(txt)
    if len(raw) < 1 + 32 + 12:
        raise ValueError('Invalid edata')
    k = raw[1:33]
    n = raw[33:45]
    ct = raw[45:]
    c = ChaCha20(k, n, 0)
    plain = c.encrypt(ct)
    return plain.decode('utf-8', errors='replace')


def _sign_params_tiksign(params_str, payload='', device=None):
    if TIKSIGN_AVAILABLE:
        result = {}
        gorgon_result = xgorgon(params_str, data=payload)
        result.update(gorgon_result)
        result['x-ladon'] = Ladon.encrypt(int(time.time()), 1611921764, 1233)
        try:
            argus_result = Argus.encrypt(
                params=params_str,
                data=payload,
                unix=int(time.time()),
                aid=1233,
                lc_id=1611921764,
            )
            if isinstance(argus_result, dict):
                result['x-argus'] = argus_result.get('X-Argus', argus_result.get('x-argus', ''))
        except Exception:
            result['x-argus'] = _generate_xargus(device or {}, params_str)
        if payload:
            result['x-ss-stub'] = md5(payload.encode('utf-8')).hexdigest().upper()
        result['content-length'] = str(len(payload))
        return result
    else:
        url_path = '/captcha/get' if not payload else '/captcha/verify'
        return {
            'x-gorgon': _generate_xgorgon(url_path, params_str, payload),
            'x-argus': _generate_xargus(device or {}, url_path),
            'x-khronos': _generate_xkhronos(),
            'content-length': str(len(payload)),
        }


def _get_captcha_base_params(device):
    ts = int(time.time() * 1000)
    return {
        'lang': 'en',
        'app_name': 'musical_ly',
        'h5_sdk_version': '2.33.17',
        'h5_sdk_use_type': 'goofy',
        'sdk_version': '2.3.8.i18n',
        'iid': device.get('install_id', ''),
        'did': device.get('device_id', ''),
        'device_id': device.get('device_id', ''),
        'ch': 'googleplay',
        'aid': '1233',
        'os_type': '0',
        'mode': 'slide',
        'tmp': str(ts),
        'platform': 'app',
        'webdriver': 'false',
        'enable_image': '1',
        'verify_host': 'https://rc-verification-sg.tiktokv.com/',
        'locale': 'en',
        'channel': 'googleplay',
        'app_key': '',
        'vc': '37.0.4',
        'app_version': '37.0.4',
        'session_id': '',
        'region': 'us',
        'userMode': '257',
        'use_native_report': '1',
        'use_jsb_request': '1',
        'orientation': '2',
        'resolution': device.get('resolution', '1080x2220').replace('x', '*'),
        'os_version': device.get('android_version', '30'),
        'device_brand': device.get('brand', 'samsung'),
        'device_model': device.get('model', 'SM-G991B'),
        'os_name': 'Android',
        'version_code': '3704',
        'device_type': device.get('model', 'SM-G991B'),
        'device_platform': 'Android',
        'type': 'verify',
        'detail': '',
        'server_sdk_env': '{"idc":"my","region":"ALISG","server_type":"business"}',
        'imagex_domain': '',
        'subtype': 'slide',
        'challenge_code': '99999',
        'triggered_region': 'us',
        'cookie_enabled': 'true',
        'screen_width': '393',
        'screen_height': '851',
        'browser_language': 'en',
        'browser_platform': 'Linux aarch64',
        'browser_name': 'Mozilla',
        'browser_version': (
            '5.0 (Linux; Android {android_ver}; {model} Build/{build}; wv) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 '
            'Chrome/143.0.7499.34 Mobile Safari/537.36 '
            'BytedanceWebview/d8a21c6'
        ).format(
            android_ver=device.get('android_version', '13'),
            model=device.get('model', 'SM-G991B'),
            build='RP1A.200720.011'
        ),
    }


def _get_user_agent():
    return (
        'com.zhiliaoapp.musically/340002 (Linux; U; Android 13; en_US; '
        'SM-G991B; Build/TP1A.220624.014; Cronet/TTNetVersion:b4d74d15 '
        '2023-02-14 QuicVersion:0144d358 2023-03-10)'
    )


class PuzzleSolver:
    def __init__(self, base64_puzzle, base64_piece):
        self.puzzle = base64_puzzle
        self.piece = base64_piece

    def get_position(self):
        try:
            p = self._sobel(self._img(self.piece))
            t = self._sobel(self._img(self.puzzle))
            results = []
            for method in (cv2.TM_CCOEFF_NORMED, cv2.TM_CCORR_NORMED):
                matched = cv2.matchTemplate(p, t, method)
                _, mx, _, mx_loc = cv2.minMaxLoc(matched)
                results.append((mx_loc[0], mx))
            ep = self._edges(p)
            et = self._edges(t)
            matched = cv2.matchTemplate(ep, et, cv2.TM_CCOEFF_NORMED)
            _, mx, _, mx_loc = cv2.minMaxLoc(matched)
            results.append((mx_loc[0], mx))
            results.sort(key=lambda x: x[1], reverse=True)
            return results[0][0]
        except Exception as e:
            log.debug('PuzzleSolver advanced method failed: %s, using fallback', e)
            p = self._sobel(self._img(self.piece))
            t = self._sobel(self._img(self.puzzle))
            matched = cv2.matchTemplate(p, t, cv2.TM_CCOEFF_NORMED)
            _, _, _, mx_loc = cv2.minMaxLoc(matched)
            return mx_loc[0]

    def _img(self, b64):
        data = base64.b64decode(b64)
        arr = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise ValueError('Failed to decode image')
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        return img

    def _edges(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        return cv2.Canny(blurred, 50, 150)

    def _sobel(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        gx = cv2.Sobel(gray, cv2.CV_16S, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_16S, 0, 1, ksize=3)
        ax = cv2.convertScaleAbs(gx)
        ay = cv2.convertScaleAbs(gy)
        grad = cv2.addWeighted(ax, 0.5, ay, 0.5, 0)
        return cv2.normalize(grad, None, 0, 255, cv2.NORM_MINMAX)


class TikTokCaptchaSolver:
    VERIFICATION_URL = 'https://rc-verification-sg.tiktokv.com'

    def __init__(self, device, proxy=None):
        self.device = device
        self.session = requests.Session()
        if proxy:
            self.session.proxies = {'https': proxy, 'http': proxy}
        self.session.headers.update({
            'User-Agent': _get_user_agent(),
            'Content-Type': 'application/json; charset=utf-8',
        })

    def get_captcha(self):
        params = _get_captcha_base_params(self.device)
        params_str = urlencode(sorted(params.items()))
        sign_headers = _sign_params_tiksign(params_str, device=self.device)

        headers = {
            'content-type': 'application/json; charset=utf-8',
            'user-agent': _get_user_agent(),
        }
        headers.update(sign_headers)

        url = f'{self.VERIFICATION_URL}/captcha/get'
        resp = self.session.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code != 200:
            log.error('get_captcha failed: status %d', resp.status_code)
            return None

        j = resp.json()
        cap = None
        if 'edata' in j:
            cap = j['edata']
        elif 'data' in j and isinstance(j['data'], dict) and 'edata' in j['data']:
            cap = j['data']['edata']

        if not cap:
            log.error('get_captcha: no edata in response')
            return None

        dec = edata_decrypt(cap)
        return json.loads(dec)

    def solve_slide_captcha(self, captcha_data):
        try:
            challenges = captcha_data.get('data', {}).get('challenges', [])
            if not challenges:
                log.error('No challenges in captcha data')
                return None

            cd = challenges[0]
            q = cd.get('question', {})
            url1 = q.get('url1')
            url2 = q.get('url2')

            if not url1 or not url2:
                log.error('Missing puzzle image URLs')
                return None

            r1 = self.session.get(url1, timeout=10)
            r2 = self.session.get(url2, timeout=10)
            if r1.status_code != 200 or r2.status_code != 200:
                log.error('Failed to download captcha images')
                return None

            puzzle_b64 = base64.b64encode(r1.content).decode()
            piece_b64 = base64.b64encode(r2.content).decode()

            solver = PuzzleSolver(puzzle_b64, piece_b64)
            max_loc = solver.get_position()

            movements = []
            total_time = 0
            num_steps = random.randint(40, 100)
            tip_y = q.get('tip_y', 0)

            for i in range(num_steps):
                progress = (i + 1) / num_steps
                x_pos = round(max_loc * progress)
                y_offset = random.randint(-2, 2) if 0 < i < num_steps - 1 else 0
                y_pos = tip_y + y_offset
                step = random.randint(8, 40)
                total_time += step
                movements.append({
                    'relative_time': total_time,
                    'x': x_pos,
                    'y': y_pos,
                })

            payload = {
                'modified_img_width': 552,
                'id': cd['id'],
                'mode': 'slide',
                'reply': movements,
                'verify_id': captcha_data['data']['verify_id'],
            }
            return payload

        except Exception as e:
            log.error('Error solving slide captcha: %s', e)
            return None

    def verify_captcha(self, payload_dict, original_params):
        try:
            data_str = json.dumps(payload_dict)
            encrypted = edata_encrypt(data_str)
            body = json.dumps({'edata': encrypted})

            params_str = urlencode(sorted(original_params.items()))
            sign_headers = _sign_params_tiksign(params_str, payload=body, device=self.device)

            headers = {
                'content-type': 'application/json; charset=utf-8',
                'user-agent': _get_user_agent(),
            }
            headers.update(sign_headers)

            url = f'{self.VERIFICATION_URL}/captcha/verify'
            resp = self.session.post(url, headers=headers, params=original_params, data=body, timeout=15)

            if resp.status_code != 200:
                log.error('verify_captcha failed: status %d', resp.status_code)
                return None

            j = resp.json()
            edata_val = None
            if 'edata' in j:
                edata_val = j['edata']
            elif 'data' in j and isinstance(j['data'], dict) and 'edata' in j['data']:
                edata_val = j['data']['edata']

            if edata_val:
                return edata_decrypt(edata_val)
            else:
                log.error('verify_captcha: no edata in response')
                return None

        except Exception as e:
            log.error('Error verifying captcha: %s', e)
            return None

    def solve(self):
        try:
            captcha_data = self.get_captcha()
            if not captcha_data:
                log.error('Failed to get captcha')
                return None

            log.info('Captcha obtained, solving slide puzzle...')
            payload = self.solve_slide_captcha(captcha_data)
            if not payload:
                log.error('Failed to solve slide captcha')
                return None

            log.info('Slide position calculated, verifying...')
            result = self.verify_captcha(payload, _get_captcha_base_params(self.device))
            if result:
                log.info('Captcha solved successfully!')
                return json.loads(result) if isinstance(result, str) else result
            else:
                log.warning('Captcha verification failed')
                return None

        except Exception as e:
            log.error('Captcha solver error: %s', e)
            return None


def solve_captcha_for_client(client, max_attempts=3):
    device_data = client.device
    proxy = client.proxy

    solver = TikTokCaptchaSolver(device_data, proxy=proxy)

    for attempt in range(max_attempts):
        log.info('Captcha solve attempt %d/%d', attempt + 1, max_attempts)
        result = solver.solve()
        if result:
            return result
        if attempt < max_attempts - 1:
            time.sleep(random.uniform(2, 5))

    log.error('All captcha solve attempts failed')
    return None
