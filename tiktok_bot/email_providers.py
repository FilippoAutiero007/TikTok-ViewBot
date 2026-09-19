"""
Multi-provider temp email system for TikTok account creation.
Supports Mail.tm, GuerrillaMail, 1SecMail with automatic fallback
when TikTok blocks a disposable domain.
"""
import re
import time
import random
import string
import logging
import requests

log = logging.getLogger(__name__)


def extract_code_generic(text):
    """Extract 4-6 digit verification code from email body text/html."""
    if not text:
        return None
    # ensure string
    if not isinstance(text, str):
        text = str(text)
    patterns = [
        r'verification code[:\s]*(\d{4,8})',
        r'verify.*?code[:\s]*(\d{4,8})',
        r'code[:\s]*(\d{4,8})',
        r'(\d{4,8})\s*is your.*code',
        r'your.*code.*?(\d{4,8})',
        r'code\s*[:=]\s*(\d{4,8})',
        r'>(\d{4,8})<',
        r'(\d{6})',
        r'(\d{4})',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            code = m.group(1)
            # prefer 6-digit codes
            if len(code) >= 4:
                log.info('Extracted verification code: %s', code)
                return code
    log.warning('Could not extract verification code')
    return None


class BaseEmailProvider:
    name = "base"

    def get_email_address(self):
        raise NotImplementedError

    def wait_for_email(self, timeout=120, poll_interval=5):
        raise NotImplementedError

    def extract_verification_code(self, email_data):
        raise NotImplementedError

    def cleanup(self):
        pass


class MailTmProvider(BaseEmailProvider):
    """Mail.tm provider with dynamic domain fetching."""
    name = "mail.tm"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        })
        self.email_addr = None
        self.token = None
        self.account_id = None
        self.password = None

    def _get_domain(self):
        try:
            r = self.session.get('https://api.mail.tm/domains', timeout=15)
            data = r.json()
            domains = [d['domain'] for d in data.get('hydra:member', []) if d.get('isActive', True)]
            if not domains:
                raise Exception('No active mail.tm domains')
            # randomize to avoid always picking same blocked domain
            random.shuffle(domains)
            return domains[0]
        except Exception as e:
            log.warning('MailTm _get_domain failed: %s, fallback to guerillamail domain', e)
            return 'wildraman.com'

    def get_email_address(self):
        # limit retries if mail.tm down
        for attempt in range(3):
            try:
                domain = self._get_domain()
                username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
                self.email_addr = f'{username}@{domain}'
                self.password = ''.join(random.choices(string.ascii_letters + string.digits, k=20))

                r = self.session.post('https://api.mail.tm/accounts', json={
                    'address': self.email_addr,
                    'password': self.password,
                }, timeout=15)
                if r.status_code not in (200, 201):
                    log.warning('MailTm account creation failed: %s %s', r.status_code, r.text[:200])
                    time.sleep(1)
                    continue
                data = r.json()
                self.account_id = data.get('id', '')

                r = self.session.post('https://api.mail.tm/token', json={
                    'address': self.email_addr,
                    'password': self.password,
                }, timeout=15)
                token_data = r.json()
                self.token = token_data.get('token', '')
                if not self.token:
                    log.warning('MailTm token not received')
                    continue
                log.info('Created mail.tm account: %s', self.email_addr)
                return self.email_addr
            except Exception as e:
                log.warning('MailTm get_email_address attempt %d failed: %s', attempt + 1, e)
                time.sleep(1)
        raise Exception('MailTm failed after 3 attempts')

    def check_email(self):
        if not self.token:
            return []
        try:
            r = self.session.get('https://api.mail.tm/messages', headers={
                'Authorization': f'Bearer {self.token}',
            }, timeout=15)
            data = r.json()
            return data.get('hydra:member', [])
        except Exception as e:
            log.debug('MailTm check_email error: %s', e)
            return []

    def fetch_email(self, email_id):
        if not self.token:
            return {}
        r = self.session.get(f'https://api.mail.tm/messages/{email_id}', headers={
            'Authorization': f'Bearer {self.token}',
        }, timeout=15)
        return r.json()

    def wait_for_email(self, timeout=120, poll_interval=5):
        start = time.time()
        seen_ids = set()
        while time.time() - start < timeout:
            try:
                emails = self.check_email()
                for info in emails:
                    email_id = info.get('id')
                    if email_id in seen_ids:
                        continue
                    subject = info.get('subject', '') or ''
                    sender = info.get('from', {}) or {}
                    sender_addr = sender.get('address', '') if isinstance(sender, dict) else str(sender)
                    log.debug('MailTm email from %s: %s', sender_addr, subject)
                    # TikTok sender variations
                    if 'tiktok' in sender_addr.lower() or 'tiktok' in subject.lower() or 'bytedance' in sender_addr.lower():
                        full = self.fetch_email(email_id)
                        return full
                    seen_ids.add(email_id)
                # also check if any email exists but not filtered - maybe sender format changed
                # if we have unseen emails and timeout is half over, return first unseen
                if emails and (time.time() - start > timeout * 0.6):
                    for info in emails:
                        if info.get('id') not in seen_ids:
                            # fetch it anyway if subject contains code-like
                            full = self.fetch_email(info.get('id'))
                            text = str(full)
                            if re.search(r'\d{4,6}', text):
                                log.info('MailTm fallback: returning email with code pattern')
                                return full
            except Exception as e:
                log.debug('MailTm wait error: %s', e)
            time.sleep(poll_interval)
        log.warning('Timeout waiting for TikTok email on %s', self.email_addr)
        return None

    @staticmethod
    def extract_verification_code(email_data):
        text = ''
        if isinstance(email_data, dict):
            # mail.tm structure: intro, html, text
            text = email_data.get('text', '') or ''
            html = email_data.get('html', '')
            if isinstance(html, list):
                html = html[0] if html else ''
            if not text:
                text = html
            if not text:
                text = email_data.get('intro', '') or str(email_data)
        else:
            text = str(email_data)
        return extract_code_generic(text)


class GuerrillaMailProvider(BaseEmailProvider):
    name = "guerrillamail"

    API_BASE = 'https://api.guerrillamail.com/ajax.php'

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        })
        self.email_addr = None
        self.email_timestamp = None

    def _api_call(self, func, extra_params=None):
        params = {'f': func, 'ip': '127.0.0.1', 'agent': 'Mozilla/5.0'}
        if extra_params:
            params.update(extra_params)
        resp = self.session.get(self.API_BASE, params=params, timeout=15)
        return resp.json()

    def get_email_address(self):
        result = self._api_call('get_email_address')
        self.email_addr = result.get('email_addr', '')
        self.email_timestamp = result.get('email_timestamp', 0)
        if not self.email_addr:
            # retry once
            time.sleep(1)
            result = self._api_call('get_email_address')
            self.email_addr = result.get('email_addr', '')
        log.info('Temp email (Guerrilla): %s', self.email_addr)
        if not self.email_addr:
            raise Exception('GuerrillaMail failed to get email')
        return self.email_addr

    def check_email(self, seq=0):
        result = self._api_call('check_email', {'seq': str(seq)})
        return result.get('list', [])

    def fetch_email(self, email_id):
        result = self._api_call('fetch_email', {'email_id': str(email_id)})
        return result

    def wait_for_email(self, timeout=120, poll_interval=5, sender_filter='tiktok'):
        start = time.time()
        while time.time() - start < timeout:
            try:
                emails = self.check_email()
                for info in emails:
                    mail_from = info.get('mail_from', '')
                    mail_subject = info.get('mail_subject', '')
                    mail_body = info.get('mail_body', '')
                    # filter by tiktok sender
                    if sender_filter and sender_filter.lower() not in mail_from.lower() and sender_filter.lower() not in mail_subject.lower():
                        # but if body contains code, consider it
                        if not re.search(r'\d{4,6}', mail_body):
                            continue
                    log.info('Guerrilla new email from %s: %s', mail_from, mail_subject)
                    return self.fetch_email(info.get('mail_id'))
            except Exception as e:
                log.debug('Guerrilla wait error: %s', e)
            time.sleep(poll_interval)
        log.warning('Timeout waiting for Guerrilla email')
        return None

    @staticmethod
    def extract_verification_code(email_body):
        if isinstance(email_body, dict):
            text = email_body.get('mail_body', '') or email_body.get('mail_excerpt', '') or str(email_body)
        else:
            text = str(email_body)
        return extract_code_generic(text)


class OneSecMailProvider(BaseEmailProvider):
    """1secmail provider - simple and often not blocked."""
    name = "1secmail"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})
        self.email_addr = None
        self.login = None
        self.domain = None

    def get_email_address(self):
        # get domains
        try:
            r = self.session.get('https://www.1secmail.com/api/v1/?action=getDomainList', timeout=10)
            domains = r.json()
            if not domains:
                domains = ['1secmail.com', '1secmail.org', '1secmail.net']
        except Exception:
            domains = ['1secmail.com', '1secmail.org', '1secmail.net']
        self.domain = random.choice(domains)
        self.login = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        self.email_addr = f'{self.login}@{self.domain}'
        log.info('Temp email (1SecMail): %s', self.email_addr)
        return self.email_addr

    def check_email(self):
        if not self.login or not self.domain:
            return []
        try:
            r = self.session.get(f'https://www.1secmail.com/api/v1/?action=getMessages&login={self.login}&domain={self.domain}', timeout=10)
            return r.json()
        except Exception as e:
            log.debug('1SecMail check error: %s', e)
            return []

    def fetch_email(self, email_id):
        try:
            r = self.session.get(f'https://www.1secmail.com/api/v1/?action=readMessage&login={self.login}&domain={self.domain}&id={email_id}', timeout=10)
            return r.json()
        except Exception as e:
            log.debug('1SecMail fetch error: %s', e)
            return {}

    def wait_for_email(self, timeout=120, poll_interval=5):
        start = time.time()
        seen = set()
        while time.time() - start < timeout:
            try:
                msgs = self.check_email()
                for m in msgs:
                    mid = m.get('id')
                    if mid in seen:
                        continue
                    frm = m.get('from', '')
                    subject = m.get('subject', '')
                    if 'tiktok' in frm.lower() or 'tiktok' in subject.lower() or 'bytedance' in frm.lower():
                        full = self.fetch_email(mid)
                        return full
                    # if any message has code pattern, return it after 40s
                    if time.time() - start > 40:
                        full = self.fetch_email(mid)
                        body = full.get('body', '') or full.get('textBody', '') or str(full)
                        if re.search(r'\d{4,6}', body):
                            return full
                    seen.add(mid)
            except Exception as e:
                log.debug('1SecMail wait error: %s', e)
            time.sleep(poll_interval)
        log.warning('Timeout waiting for 1SecMail email on %s', self.email_addr)
        return None

    @staticmethod
    def extract_verification_code(email_data):
        if isinstance(email_data, dict):
            text = email_data.get('body', '') or email_data.get('textBody', '') or email_data.get('htmlBody', '') or str(email_data)
        else:
            text = str(email_data)
        return extract_code_generic(text)


class MultiTempEmailProvider:
    """
    Tries multiple providers until one successfully gets a verification code.
    Also handles TikTok blocking specific disposable domains.
    """
    PROVIDER_CLASSES = [MailTmProvider, GuerrillaMailProvider, OneSecMailProvider]

    def __init__(self, preferred_order=None):
        self.providers = []
        order = preferred_order or ['mail.tm', 'guerrillamail', '1secmail']
        name_to_class = {c.name: c for c in self.PROVIDER_CLASSES}
        for name in order:
            if name in name_to_class:
                self.providers.append(name_to_class[name])
        self.current_provider = None
        self.current_instance = None
        self.email_addr = None
        # track blocked domains to avoid reuse
        self.blocked_emails = set()

    def get_email_address(self):
        last_err = None
        for ProviderCls in self.providers:
            try:
                inst = ProviderCls()
                email = inst.get_email_address()
                if email in self.blocked_emails:
                    log.info('Skipping previously blocked email %s', email)
                    continue
                self.current_provider = ProviderCls.name
                self.current_instance = inst
                self.email_addr = email
                log.info('Using provider %s with email %s', self.current_provider, email)
                return email
            except Exception as e:
                last_err = e
                log.warning('Provider %s failed to get email: %s', ProviderCls.name, e)
                continue
        raise Exception(f'All email providers failed: {last_err}')

    def wait_for_email(self, timeout=120, poll_interval=5):
        if not self.current_instance:
            log.error('No current provider instance')
            return None
        return self.current_instance.wait_for_email(timeout=timeout, poll_interval=poll_interval)

    def extract_verification_code(self, email_data):
        if not self.current_instance:
            return None
        # Try provider-specific extractor first, then generic fallback
        try:
            code = self.current_instance.extract_verification_code(email_data)
            if code:
                return code
        except Exception:
            pass
        # fallback generic
        if isinstance(email_data, dict):
            text = str(email_data)
        else:
            text = str(email_data)
        return extract_code_generic(text)

    def mark_blocked(self):
        """Mark current email as blocked by TikTok."""
        if self.email_addr:
            self.blocked_emails.add(self.email_addr)
            log.warning('Marked email as blocked: %s', self.email_addr)

    def rotate_provider(self):
        """Rotate to next provider and get new email."""
        log.info('Rotating email provider...')
        if self.current_instance:
            try:
                self.current_instance.cleanup()
            except Exception:
                pass
        return self.get_email_address()

    @property
    def provider_name(self):
        return self.current_provider or 'unknown'
