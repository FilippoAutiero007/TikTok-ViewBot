import json
import os
import time
import random
import string
import logging
from datetime import datetime, timedelta

from .device import generate_device, save_device, load_device, load_all_devices
from .client import TikTokClient, TikTokAPIError

log = logging.getLogger(__name__)

ACCOUNTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'accounts')
CREDS_DIR = os.path.join(ACCOUNTS_DIR, 'credentials')
ACTIVE_DIR = os.path.join(ACCOUNTS_DIR, 'active')
BANNED_DIR = os.path.join(ACCOUNTS_DIR, 'banned')

TEMP_EMAIL_DOMAINS = [
    'guerrillamail.com', 'mailinator.com', 'yopmail.com',
    'throwaway.email', 'tempmail.com', '10minutemail.com',
    'guerrillamailblock.com', 'grr.la', 'dispostable.com',
    'sharklasers.com', 'guerrillamail.info', 'grr.la',
    'lr78.com', 'zehnminutenmail.de', 'mohmal.com',
]

NAMES_FIRST = [
    'Alex', 'Jordan', 'Taylor', 'Morgan', 'Casey', 'Riley', 'Quinn',
    'Avery', 'Cameron', 'Drew', 'Blake', 'Hayden', 'Skyler', 'Dakota',
    'Reese', 'Parker', 'Finley', 'Sage', 'Rowan', 'Emerson',
]

NAMES_LAST = [
    'Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller',
    'Davis', 'Rodriguez', 'Martinez', 'Anderson', 'Taylor', 'Thomas',
    'Moore', 'Jackson', 'Martin', 'Lee', 'Thompson', 'White', 'Harris',
]


def _random_email():
    name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=random.randint(8, 14)))
    domain = random.choice(TEMP_EMAIL_DOMAINS)
    return f'{name}@{domain}'


def _random_password():
    chars = string.ascii_letters + string.digits + '!@#$%'
    return ''.join(random.choices(chars, k=random.randint(12, 18)))


def _random_username():
    first = random.choice(NAMES_FIRST).lower()
    last = random.choice(NAMES_LAST).lower()
    num = random.randint(1, 9999)
    sep = random.choice(['', '_', '.', ''])
    templates = [
        f'{first}{sep}{last}{num}',
        f'{first}{sep}{num}',
        f'{first}{last}{sep}{num}',
        f'{num}{sep}{first}{last}',
        f'{first}_{random.randint(100,999)}',
    ]
    return random.choice(templates)


class Account:
    def __init__(self, data=None):
        self.data = data or {}
        self.username = self.data.get('username', '')
        self.email = self.data.get('email', '')
        self.password = self.data.get('password', '')
        self.user_id = self.data.get('user_id', '')
        self.sec_uid = self.data.get('sec_uid', '')
        self.nickname = self.data.get('nickname', '')
        self.device_id = self.data.get('device_id', '')
        self.device = self.data.get('device', {})
        self.cookies = self.data.get('cookies', {})
        self.x_tt_token = self.data.get('x_tt_token', '')
        self.domain = self.data.get('domain', '')
        self.passport_domain = self.data.get('passport_domain', '')
        self.tt_target_idc = self.data.get('tt_target_idc', '')
        self.status = self.data.get('status', 'active')
        self.created_at = self.data.get('created_at', int(time.time()))
        self.last_used = self.data.get('last_used', 0)
        self.actions_count = self.data.get('actions_count', 0)
        self.follows_sent = self.data.get('follows_sent', 0)
        self.likes_sent = self.data.get('likes_sent', 0)
        self.views_sent = self.data.get('views_sent', 0)

    def to_dict(self):
        return {
            'username': self.username,
            'email': self.email,
            'password': self.password,
            'user_id': self.user_id,
            'sec_uid': self.sec_uid,
            'nickname': self.nickname,
            'device_id': self.device_id,
            'device': self.device,
            'cookies': self.cookies,
            'x_tt_token': self.x_tt_token,
            'domain': self.domain,
            'passport_domain': self.passport_domain,
            'tt_target_idc': self.tt_target_idc,
            'status': self.status,
            'created_at': self.created_at,
            'last_used': self.last_used,
            'actions_count': self.actions_count,
            'follows_sent': self.follows_sent,
            'likes_sent': self.likes_sent,
            'views_sent': self.views_sent,
        }

    def save(self):
        os.makedirs(ACTIVE_DIR, exist_ok=True)
        path = os.path.join(ACTIVE_DIR, f'{self.user_id or self.username}.json')
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    def mark_banned(self):
        self.status = 'banned'
        os.makedirs(BANNED_DIR, exist_ok=True)
        path = os.path.join(BANNED_DIR, f'{self.user_id or self.username}.json')
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
        active_path = os.path.join(ACTIVE_DIR, f'{self.user_id or self.username}.json')
        if os.path.exists(active_path):
            os.remove(active_path)

    def update(self, **kwargs):
        self.data.update(kwargs)
        self.__init__(self.data)

    @property
    def is_cooled_down(self):
        if self.last_used == 0:
            return False
        elapsed = time.time() - self.last_used
        return elapsed < random.randint(30, 90)

    @property
    def age_hours(self):
        return (time.time() - self.created_at) / 3600

    @property
    def is_too_new(self):
        return self.age_hours < 1


class AccountManager:
    def __init__(self):
        self.accounts = []
        self._load_accounts()

    def _load_accounts(self):
        os.makedirs(ACTIVE_DIR, exist_ok=True)
        for fname in os.listdir(ACTIVE_DIR):
            if fname.endswith('.json'):
                with open(os.path.join(ACTIVE_DIR, fname)) as f:
                    data = json.load(f)
                    self.accounts.append(Account(data))
        log.info('Loaded %d accounts', len(self.accounts))

    def create_account(self, email=None, password=None, username=None):
        device = generate_device()
        save_device(device)

        if not email:
            email = _random_email()
        if not password:
            password = _random_password()
        if not username:
            username = _random_username()

        account = Account({
            'username': username,
            'email': email,
            'password': password,
            'device_id': device['device_id'],
            'device': device,
            'status': 'pending',
            'created_at': int(time.time()),
        })
        return account

    def register_account(self, email=None, password=None, proxy=None):
        device = generate_device()
        save_device(device)

        if not email:
            email = _random_email()
        if not password:
            password = _random_password()

        log.info('Registering account: %s', email)
        client = TikTokClient(device, proxy=proxy)

        result = client.register_account(email, password)

        if not result:
            log.error('Registration returned None')
            return None

        status = result.get('status', 'error')

        if status == 'captcha_required':
            log.warning('Captcha required for registration (error_code: %d)', result.get('error_code', 0))
            from .captcha_solver import TikTokCaptchaSolver
            solver = TikTokCaptchaSolver(device, proxy=proxy)
            captcha_result = solver.solve()
            if captcha_result:
                log.info('Captcha solved, retrying registration...')
                result = client.register_account(email, password)
                if result:
                    status = result.get('status', 'error')
                else:
                    log.error('Registration retry failed after captcha solve')
                    return None
            else:
                log.error('Failed to solve captcha')
                return None

        if status == 'error':
            log.error('Registration failed: %s', result.get('message', 'Unknown'))
            return None

        if status == 'success':
            acc_info = result.get('account', {})
            account = Account({
                'email': email,
                'password': password,
                'username': acc_info.get('username', ''),
                'nickname': acc_info.get('nickname', ''),
                'user_id': acc_info.get('user_id', ''),
                'sec_uid': acc_info.get('sec_uid', ''),
                'device_id': device['device_id'],
                'device': acc_info.get('device', device),
                'cookies': acc_info.get('cookies', {}),
                'x_tt_token': acc_info.get('x_tt_token', ''),
                'domain': acc_info.get('domain', ''),
                'passport_domain': acc_info.get('passport_domain', ''),
                'tt_target_idc': acc_info.get('tt_target_idc', ''),
                'status': 'active',
                'created_at': int(time.time()),
            })
            account.save()
            self.accounts.append(account)
            log.info('Account registered: %s (user_id: %s)', account.username, account.user_id)
            return account

        log.error('Unexpected registration status: %s', status)
        return None

    def register_batch(self, count, proxy=None, delay_min=5, delay_max=15):
        results = {'success': 0, 'failed': 0, 'captcha_solved': 0}
        for i in range(count):
            log.info('Registering account %d/%d...', i + 1, count)
            account = self.register_account(proxy=proxy)
            if account:
                results['success'] += 1
                log.info('[%d/%d] Success: %s', i + 1, count, account.username)
            else:
                results['failed'] += 1
                log.warning('[%d/%d] Failed', i + 1, count)

            if i < count - 1:
                delay = random.uniform(delay_min, delay_max)
                log.info('Waiting %.1fs before next registration...', delay)
                time.sleep(delay)

        log.info('Batch done: %d success, %d failed', results['success'], results['failed'])
        return results

    def login_account(self, username, password, is_email=True, proxy=None):
        device = generate_device()
        save_device(device)

        client = TikTokClient(device, proxy=proxy)
        result = client.login(username, password, is_email=is_email)

        if not result:
            return None

        status = result.get('status', 'error')
        if status == 'success':
            acc_info = result.get('account', {})
            account = Account({
                'email': username if is_email else '',
                'username': acc_info.get('username', username),
                'password': password,
                'user_id': acc_info.get('user_id', ''),
                'sec_uid': acc_info.get('sec_uid', ''),
                'device_id': device['device_id'],
                'device': acc_info.get('device', device),
                'cookies': acc_info.get('cookies', {}),
                'x_tt_token': acc_info.get('x_tt_token', ''),
                'domain': acc_info.get('domain', ''),
                'passport_domain': acc_info.get('passport_domain', ''),
                'tt_target_idc': acc_info.get('tt_target_idc', ''),
                'status': 'active',
                'created_at': int(time.time()),
            })
            account.save()
            self.accounts.append(account)
            log.info('Logged in: %s', account.username)
            return account

        if status == 'captcha_required':
            log.warning('Captcha required for login (error_code: %d)', result.get('error_code', 0))
            from .captcha_solver import TikTokCaptchaSolver
            solver = TikTokCaptchaSolver(device, proxy=proxy)
            captcha_result = solver.solve()
            if captcha_result:
                log.info('Captcha solved, retrying login...')
                result = client.login(username, password, is_email=is_email)
                if result and result.get('status') == 'success':
                    acc_info = result.get('account', {})
                    account = Account({
                        'email': username if is_email else '',
                        'username': acc_info.get('username', username),
                        'password': password,
                        'user_id': acc_info.get('user_id', ''),
                        'sec_uid': acc_info.get('sec_uid', ''),
                        'device_id': device['device_id'],
                        'device': acc_info.get('device', device),
                        'cookies': acc_info.get('cookies', {}),
                        'x_tt_token': acc_info.get('x_tt_token', ''),
                        'domain': acc_info.get('domain', ''),
                        'passport_domain': acc_info.get('passport_domain', ''),
                        'tt_target_idc': acc_info.get('tt_target_idc', ''),
                        'status': 'active',
                        'created_at': int(time.time()),
                    })
                    account.save()
                    self.accounts.append(account)
                    log.info('Logged in after captcha: %s', account.username)
                    return account
            log.error('Failed to solve captcha or retry login')
            return None

        log.error('Login failed: %s', result.get('message', 'Unknown'))
        return None

    def get_available_account(self):
        available = [
            a for a in self.accounts
            if a.status == 'active'
            and not a.is_cooled_down
            and not a.is_too_new
        ]
        if not available:
            return None
        return min(available, key=lambda a: a.actions_count)

    def get_accounts_for_action(self, action_type, count=1):
        available = [
            a for a in self.accounts
            if a.status == 'active'
            and not a.is_too_new
        ]
        if action_type == 'follow':
            available = [a for a in available if a.follows_sent < 50]
        elif action_type == 'like':
            available = [a for a in available if a.likes_sent < 100]
        elif action_type == 'view':
            available = [a for a in available if a.views_sent < 200]

        available.sort(key=lambda a: (a.actions_count, a.last_used))
        return available[:count]

    def record_action(self, account, action_type):
        account.actions_count += 1
        account.last_used = int(time.time())
        if action_type == 'follow':
            account.follows_sent += 1
        elif action_type == 'like':
            account.likes_sent += 1
        elif action_type == 'view':
            account.views_sent += 1
        account.save()

    def get_stats(self):
        active = [a for a in self.accounts if a.status == 'active']
        banned = [a for a in self.accounts if a.status == 'banned']
        total_follows = sum(a.follows_sent for a in self.accounts)
        total_likes = sum(a.likes_sent for a in self.accounts)
        total_views = sum(a.views_sent for a in self.accounts)
        return {
            'total': len(self.accounts),
            'active': len(active),
            'banned': len(banned),
            'total_follows': total_follows,
            'total_likes': total_likes,
            'total_views': total_views,
        }
