import sys
from re import findall
from io import BytesIO
from PIL import Image
from time import sleep, time
from base64 import b64decode
from random import choices
from string import ascii_letters, digits
from requests import Session, post
from colorama import Fore, init
from datetime import datetime
from urllib.parse import unquote
from PIL.Image import DecompressionBombError

init()

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36'
ZIFOY_URL = 'https://zefoy.com'
API_URL = f'{ZIFOY_URL}/c2VuZF9mb2xsb3dlcnNfdGlrdG9L'

HEADERS = {
    'authority': 'zefoy.com',
    'accept': '*/*',
    'accept-language': 'en,fr-FR;q=0.9,fr;q=0.8,es-ES;q=0.7,es;q=0.6,en-US;q=0.5,am;q=0.4,de;q=0.3',
    'cache-control': 'no-cache',
    'origin': ZIFOY_URL,
    'pragma': 'no-cache',
    'sec-ch-ua': '"Google Chrome";v="111", "Not(A:Brand";v="8", "Chromium";v="111"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': USER_AGENT,
    'x-requested-with': 'XMLHttpRequest',
}


def log(msg, level='INFO'):
    colors = {'DEBUG': Fore.GREEN, 'INFO': Fore.BLUE, 'WARNING': Fore.YELLOW, 'ERROR': Fore.RED}
    color = colors.get(level, colors['INFO'])
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f'{Fore.CYAN}{ts} {color}{level}{Fore.RESET} {msg}')


def decode(text):
    return b64decode(unquote(text[::-1])).decode()


def http_request(session, method, url, max_retries=3, **kwargs):
    kwargs.setdefault('timeout', 30)
    for attempt in range(max_retries + 1):
        try:
            resp = session.request(method, url, **kwargs)
            if resp.status_code == 429:
                delay = 2 ** attempt
                log(f'Rate limited, waiting {delay}s...', 'WARNING')
                sleep(delay)
                continue
            if resp.status_code >= 500:
                delay = 2 ** attempt
                log(f'Server error {resp.status_code}, waiting {delay}s...', 'WARNING')
                sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt == max_retries:
                log(f'Request failed after {max_retries} retries: {e}', 'ERROR')
                raise
            delay = 2 ** attempt
            log(f'Attempt {attempt + 1} failed: {e}, retrying in {delay}s...', 'WARNING')
            sleep(delay)
    raise Exception(f'Failed after {max_retries} retries')


def parse_captcha_fields(html):
    text_inputs = []
    hidden_fields = []
    captcha_img = None

    for pattern in [
        r'<input[^>]*type="text"[^>]*name="([^"]*)"[^>]*value="([^"]*)"[^>]*>',
        r'type="text"[^>]*name="([^"]*)"[^>]*value="([^"]*)"',
        r'type="text" maxlength="50" name="([^"]*)" oninput="this.value',
        r'name="([^"]*)"[^>]*placeholder="([^"]*)"',
    ]:
        text_inputs = findall(pattern, html)
        if text_inputs:
            break

    for pattern in [
        r'<input[^>]*type="hidden"[^>]*name="([^"]*)"[^>]*value="([^"]*)"[^>]*>',
    ]:
        hidden_fields = findall(pattern, html)
        if hidden_fields:
            break

    for img in findall(r'<img[^>]*src="([^"]*)"[^>]*>', html):
        if 'captcha' in img.lower() or img.endswith('.png'):
            captcha_img = img if img.startswith('http') else f'{ZIFOY_URL}/{img}'
            break

    if not captcha_img:
        for img in findall(r'<img[^>]*src="([^"]*)"[^>]*>', html):
            if img:
                captcha_img = img if img.startswith('http') else f'{ZIFOY_URL}/{img}'
                break

    return text_inputs, hidden_fields, captcha_img


def validate_captcha_page(html):
    if not html:
        log('Empty response from homepage', 'ERROR')
        return False
    if len(html) < 1000:
        log(f'HTML too short ({len(html)} chars)', 'WARNING')
        return False
    if 'Captcha code is incorrect' in html:
        log('Captcha incorrect - previous submission failed or captcha expired', 'ERROR')
        return False
    if 'captcha' not in html.lower():
        log('No captcha detected in page', 'ERROR')
        return False
    return True


def create_session():
    s = Session()
    s.headers.update(HEADERS)
    return s


def solve_captcha():
    log('Fetching Zefoy homepage...')
    session = create_session()
    resp = http_request(session, 'GET', ZIFOY_URL)
    html = resp.text.replace('&amp;', '&')

    if not validate_captcha_page(html):
        return None, None

    text_inputs, hidden_fields, captcha_img = parse_captcha_fields(html)
    if not captcha_img:
        log('Could not find captcha image', 'ERROR')
        return None, None

    field = text_inputs[0][0] if text_inputs else 'captcha_secure'
    log(f'Captcha field: {field}')

    log('Downloading captcha image...')
    try:
        img_resp = http_request(session, 'GET', f'{ZIFOY_URL}{captcha_img}')
        image = Image.open(BytesIO(img_resp.content))
        with open('captcha.png', 'wb') as f:
            f.write(img_resp.content)
        log('Saved captcha.png')
        try:
            image.show()
        except Exception:
            log('Open captcha.png manually to view', 'WARNING')
    except Exception as e:
        log(f'Failed to download captcha: {e}', 'ERROR')
        return None, None

    log('Solve the captcha and enter the answer:')
    answer = input('> ').strip()
    if not answer:
        log('No answer provided', 'ERROR')
        return None, None

    log('Submitting captcha...')
    data = {field: answer}
    for name, value in hidden_fields:
        if name and value:
            data[name] = value
    data['token'] = ''

    session.headers['Content-Type'] = 'application/x-www-form-urlencoded'
    resp = http_request(session, 'POST', ZIFOY_URL, data=data)

    if 'captcha' in resp.text.lower():
        log('Captcha submission failed', 'WARNING')
        return None, None

    for pattern in [r'remove-spaces" name="([^"]*)" placeholder', r'name="([^"]*)" value="([^"]*)"', r'key=(\w+)']:
        for match in findall(pattern, resp.text):
            key = match[0] if isinstance(match, tuple) else match
            if len(key) < 100:
                log(f'Captcha solved! Key: {key}')
                return session, key

    log('Could not extract key from response', 'ERROR')
    return None, None


def send_views(session, key, aweme_id):
    token = ''.join(choices(ascii_letters + digits, k=16))
    boundary = f'----WebKitFormBoundary{token}'
    data = f'{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{aweme_id}\r\n{boundary}--\r\n'

    headers = {**HEADERS, 'content-type': f'multipart/form-data; boundary={boundary}'}
    resp = decode(post(API_URL, data=data, cookies=session.cookies.get_dict(), headers=headers).text)

    if 'Session expired' in resp:
        raise Exception('Session expired')
    if 'views sent' in resp:
        log(f'Views sent to {aweme_id}')
    else:
        log(f'Failed to send views to {aweme_id}', 'WARNING')


def search_link(session, key, tiktok_url):
    boundary = '----WebKitFormBoundary'
    data = f'{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{tiktok_url}\r\n{boundary}--\r\n'

    headers = {**HEADERS, 'content-type': f'multipart/form-data; boundary={boundary}'}
    resp = decode(post(API_URL, data=data, headers=headers).text)

    if "onsubmit=\"showHideElements('.w1r','.w2r')" in resp:
        token, aweme_id = findall(r'name="(.*)" value="(.*)" hidden', resp)[0]
        log(f'Sending to: {aweme_id}')
        sleep(3)
        send_views(session, token, aweme_id)
    else:
        timer = int(findall(r'ltm=(\d*);', resp)[0])
        if timer == 0:
            return
        end_time = time() + timer
        while time() < end_time:
            remaining = round(end_time - time())
            print(f'\rWaiting {remaining}s...', end='', flush=True)
            sleep(1)
        print(f'\rSending views...           ')


def main():
    tiktok_url = input('TikTok URL: ').strip()
    if not tiktok_url:
        log('No URL provided', 'ERROR')
        return

    log('Starting Zefoy ViewBot...')
    session, key = solve_captcha()

    if not key:
        log('Failed to solve captcha (zefoy may have blocked you)', 'ERROR')
        return

    log('Sending views...')
    while True:
        try:
            search_link(session, key, tiktok_url)
        except Exception as e:
            log(f'Error: {e}', 'ERROR')
        sleep(5)


if __name__ == '__main__':
    main()
