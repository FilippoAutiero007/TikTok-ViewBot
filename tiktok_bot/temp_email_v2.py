import re
import time
import random
import string
import logging
import requests

log = logging.getLogger(__name__)


class MailTmClient:
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
        r = self.session.get('https://api.mail.tm/domains', timeout=15)
        data = r.json()
        domains = [d['domain'] for d in data.get('hydra:member', [])]
        if not domains:
            raise Exception('No domains available from mail.tm')
        return domains[0]

    def get_email_address(self):
        domain = self._get_domain()
        username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
        self.email_addr = f'{username}@{domain}'
        self.password = ''.join(random.choices(string.ascii_letters + string.digits, k=20))

        r = self.session.post('https://api.mail.tm/accounts', json={
            'address': self.email_addr,
            'password': self.password,
        }, timeout=15)
        data = r.json()
        self.account_id = data.get('id', '')
        log.info('Created mail.tm account: %s', self.email_addr)

        r = self.session.post('https://api.mail.tm/token', json={
            'address': self.email_addr,
            'password': self.password,
        }, timeout=15)
        token_data = r.json()
        self.token = token_data.get('token', '')
        log.info('Got mail.tm token')

        return self.email_addr

    def check_email(self):
        if not self.token:
            return []
        r = self.session.get('https://api.mail.tm/messages', headers={
            'Authorization': f'Bearer {self.token}',
        }, timeout=15)
        data = r.json()
        return data.get('hydra:member', [])

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
            emails = self.check_email()
            for email_info in emails:
                email_id = email_info.get('id')
                if email_id in seen_ids:
                    continue
                subject = email_info.get('subject', '')
                sender = email_info.get('from', {})
                sender_addr = sender.get('address', '') if isinstance(sender, dict) else ''
                log.info('New email from %s: %s', sender_addr, subject)
                if 'tiktok' in sender_addr.lower() or 'tiktok' in subject.lower():
                    return self.fetch_email(email_id)
                seen_ids.add(email_id)
            time.sleep(poll_interval)
        log.warning('Timeout waiting for TikTok email')
        return None

    @staticmethod
    def extract_verification_code(email_data):
        text = ''
        if isinstance(email_data, dict):
            text = email_data.get('text', '') or email_data.get('html', [''])[0] if isinstance(email_data.get('html'), list) else email_data.get('html', '')
        if not text:
            text = str(email_data)

        patterns = [
            r'verification code[:\s]*(\d{4,8})',
            r'code[:\s]*(\d{4,8})',
            r'(\d{4,8})\s*is your.*code',
            r'your.*code.*?(\d{4,8})',
            r'code\s*[:=]\s*(\d{4,8})',
            r'>(\d{4,8})<',
            r'(\d{6})',
            r'(\d{4})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                code = match.group(1)
                log.info('Extracted verification code: %s', code)
                return code
        log.warning('Could not extract verification code')
        return None
