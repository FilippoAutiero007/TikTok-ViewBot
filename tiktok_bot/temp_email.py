import re
import time
import logging
import requests

log = logging.getLogger(__name__)

API_BASE = 'https://api.guerrillamail.com/ajax.php'


class GuerrillaMailClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        })
        self.email_addr = None
        self.email_timestamp = None

    def _api_call(self, func, extra_params=None):
        params = {
            'f': func,
            'ip': '127.0.0.1',
            'agent': 'Mozilla/5.0',
        }
        if extra_params:
            params.update(extra_params)

        resp = self.session.get(API_BASE, params=params, timeout=15)
        return resp.json()

    def get_email_address(self):
        result = self._api_call('get_email_address')
        self.email_addr = result.get('email_addr', '')
        self.email_timestamp = result.get('email_timestamp', 0)
        log.info('Temp email: %s', self.email_addr)
        return self.email_addr

    def set_email_user(self, username):
        result = self._api_call('set_email_user', {'email_user': username})
        self.email_addr = result.get('email_addr', '')
        self.email_timestamp = result.get('email_timestamp', 0)
        log.info('Set email: %s', self.email_addr)
        return self.email_addr

    def check_email(self, seq=0):
        result = self._api_call('check_email', {'seq': str(seq)})
        return result.get('list', [])

    def fetch_email(self, email_id):
        result = self._api_call('fetch_email', {'email_id': str(email_id)})
        return result

    def wait_for_email(self, timeout=120, poll_interval=5, sender_filter=None, subject_filter=None):
        start = time.time()
        seen_ids = set()

        while time.time() - start < timeout:
            emails = self.check_email()
            for email_info in emails:
                mail_id = email_info.get('mail_id')
                if mail_id in seen_ids:
                    continue

                mail_from = email_info.get('mail_from', '')
                mail_subject = email_info.get('mail_subject', '')

                if sender_filter and sender_filter.lower() not in mail_from.lower():
                    continue
                if subject_filter and subject_filter.lower() not in mail_subject.lower():
                    continue

                log.info('New email from %s: %s', mail_from, mail_subject)
                return self.fetch_email(mail_id)

            log.debug('No matching email yet, checking again in %ds...', poll_interval)
            time.sleep(poll_interval)

        log.warning('Timeout waiting for email after %ds', timeout)
        return None

    @staticmethod
    def extract_verification_code(email_body):
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
            match = re.search(pattern, email_body, re.IGNORECASE)
            if match:
                code = match.group(1)
                log.info('Extracted verification code: %s', code)
                return code

        log.warning('Could not extract verification code from email')
        return None
