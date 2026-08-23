import time
import random
import logging
import threading
import signal
import sys
from datetime import datetime

from .client import TikTokClient, TikTokAPIError
from .accounts import AccountManager, Account
from .device import generate_device, save_device

log = logging.getLogger(__name__)


class BotStats:
    def __init__(self):
        self.lock = threading.Lock()
        self.start_time = time.time()
        self.total_follows = 0
        self.total_likes = 0
        self.total_views = 0
        self.total_errors = 0
        self.total_accounts_created = 0
        self.total_accounts_banned = 0
        self.current_cycle = 0

    def record(self, action_type, success=True):
        with self.lock:
            if action_type == 'follow' and success:
                self.total_follows += 1
            elif action_type == 'like' and success:
                self.total_likes += 1
            elif action_type == 'view' and success:
                self.total_views += 1
            if not success:
                self.total_errors += 1

    def get_uptime(self):
        elapsed = time.time() - self.start_time
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        return f'{hours}h {minutes}m {seconds}s'

    def get_rates(self):
        elapsed = max(time.time() - self.start_time, 1)
        return {
            'follows_per_hour': round(self.total_follows / (elapsed / 3600), 1),
            'likes_per_hour': round(self.total_likes / (elapsed / 3600), 1),
            'errors_per_hour': round(self.total_errors / (elapsed / 3600), 1),
        }

    def summary(self):
        rates = self.get_rates()
        return (
            f'\n{"="*50}\n'
            f'  BOT STATISTICS\n'
            f'{"="*50}\n'
            f'  Uptime:           {self.get_uptime()}\n'
            f'  Follows sent:     {self.total_follows} ({rates["follows_per_hour"]}/h)\n'
            f'  Likes sent:       {self.total_likes} ({rates["likes_per_hour"]}/h)\n'
            f'  Views sent:       {self.total_views}\n'
            f'  Errors:           {self.total_errors} ({rates["errors_per_hour"]}/h)\n'
            f'  Accounts created: {self.total_accounts_created}\n'
            f'  Accounts banned:  {self.total_accounts_banned}\n'
            f'  Cycles completed: {self.current_cycle}\n'
            f'{"="*50}'
        )


class TikTokBot:
    def __init__(self, target_url, target_sec_uid=None, actions=None, config=None):
        self.target_url = target_url
        self.target_sec_uid = target_sec_uid
        self.actions = actions or ['follow', 'like']
        self.config = config or {}
        self.account_manager = AccountManager()
        self.stats = BotStats()
        self.running = False
        self._stop_event = threading.Event()

        self.min_delay = self.config.get('min_delay', 2)
        self.max_delay = self.config.get('max_delay', 8)
        self.accounts_per_batch = self.config.get('accounts_per_batch', 3)
        self.max_actions_per_account = self.config.get('max_actions_per_account', 5)
        self.auto_create_accounts = self.config.get('auto_create_accounts', True)
        self.target_follows = self.config.get('target_follows', 0)
        self.target_likes = self.config.get('target_likes', 0)

    def start(self):
        self.running = True
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        log.info('Bot started. Target: %s', self.target_url)
        log.info('Actions: %s', ', '.join(self.actions))
        log.info('Accounts: %d active', len(self.account_manager.accounts))

        try:
            self._main_loop()
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            log.info(self.stats.summary())

    def stop(self):
        self.running = False
        self._stop_event.set()

    def _signal_handler(self, signum, frame):
        log.info('Stopping bot...')
        self.stop()
        sys.exit(0)

    def _main_loop(self):
        while self.running and not self._stop_event.is_set():
            self.stats.current_cycle += 1

            if self.target_follows > 0 and self.stats.total_follows >= self.target_follows:
                log.info('Target follows reached: %d', self.target_follows)
                break
            if self.target_likes > 0 and self.stats.total_likes >= self.target_likes:
                log.info('Target likes reached: %d', self.target_likes)
                break

            accounts = self.account_manager.get_accounts_for_action(
                'any', self.accounts_per_batch
            )

            if not accounts:
                if self.auto_create_accounts:
                    log.info('No available accounts, creating new ones...')
                    self._create_accounts_batch(3)
                    time.sleep(5)
                    continue
                else:
                    log.warning('No available accounts and auto-create is disabled')
                    time.sleep(30)
                    continue

            for account in accounts:
                if not self.running:
                    break

                if account.is_cooled_down:
                    continue

                action = random.choice(self.actions)
                try:
                    self._perform_action(account, action)
                except TikTokAPIError as e:
                    log.error('Action failed for %s: %s', account.username, e)
                    self.stats.record(action, success=False)
                    if 'login' in str(e).lower() or 'session' in str(e).lower():
                        account.mark_banned()
                        self.stats.total_accounts_banned += 1
                        log.warning('Account %s marked as banned', account.username)
                except Exception as e:
                    log.error('Unexpected error: %s', e)
                    self.stats.record(action, success=False)

                delay = random.uniform(self.min_delay, self.max_delay) if self.max_delay > 0 else 0
                if delay > 0:
                    time.sleep(delay)

            if self.stats.current_cycle % 10 == 0:
                log.info(self.stats.summary())

            time.sleep(random.uniform(1, 3))

    def _perform_action(self, account, action):
        device = account.device
        client = TikTokClient(device, proxy=self.config.get('proxy'))

        if account.cookies:
            client.session.cookies.update(account.cookies)
        if account.x_tt_token:
            client.x_token = account.x_tt_token
        if account.domain:
            client.domain = account.domain
        if account.passport_domain:
            client.passport_domain = account.passport_domain

        try:
            if action == 'follow' and self.target_sec_uid:
                client.follow(self.target_sec_uid)
                self.stats.record('follow')
                self.account_manager.record_action(account, 'follow')
                log.info('[FOLLOW] %s -> target (total: %d)',
                         account.username, self.stats.total_follows)

            elif action == 'like':
                videos = self._get_target_videos(client)
                if videos:
                    video = random.choice(videos)
                    aweme_id = video.get('aweme_id', '')
                    if aweme_id:
                        client.like(aweme_id)
                        self.stats.record('like')
                        self.account_manager.record_action(account, 'like')
                        log.info('[LIKE] %s -> video %s (total: %d)',
                                 account.username, aweme_id, self.stats.total_likes)

            elif action == 'view':
                videos = self._get_target_videos(client)
                if videos:
                    video = random.choice(videos)
                    aweme_id = video.get('aweme_id', '')
                    if aweme_id:
                        client.view(aweme_id)
                        self.stats.record('view')
                        self.account_manager.record_action(account, 'view')
                        log.info('[VIEW] %s -> video %s (total: %d)',
                                 account.username, aweme_id, self.stats.total_views)

        except TikTokAPIError as e:
            if 'login' in str(e).lower() or 'session' in str(e).lower():
                account.mark_banned()
                self.stats.total_accounts_banned += 1
                log.warning('Account %s marked as banned: %s', account.username, e)
            raise

    def _get_target_videos(self, client):
        try:
            if self.target_sec_uid:
                resp = client.get_user_videos(self.target_sec_uid, count=5)
                return resp.get('aweme_list', [])
        except Exception as e:
            log.debug('Failed to get videos: %s', e)
        return []

    def _create_accounts_batch(self, count):
        for i in range(count):
            try:
                account = self.account_manager.create_account()
                log.info('Created account placeholder: %s (email: %s)',
                         account.username, account.email)
                self.stats.total_accounts_created += 1
                account.save()
            except Exception as e:
                log.error('Failed to create account: %s', e)


class BotDashboard:
    def __init__(self, bot):
        self.bot = bot
        self.running = False

    def start(self):
        self.running = True
        self._loop()

    def stop(self):
        self.running = False

    def _loop(self):
        while self.running:
            self._print_dashboard()
            time.sleep(5)

    def _print_dashboard(self):
        stats = self.bot.stats
        am = self.bot.account_manager
        acc_stats = am.get_stats()
        rates = stats.get_rates()

        sys.stdout.write('\033[2J\033[H')
        sys.stdout.flush()

        print(f'''
{"#"*60}
#  TikTok Bot - Autonomous Engagement Engine
#  Target: {self.bot.target_url}
#  Uptime: {stats.get_uptime()}
{"#"*60}

  ACTIONS
  -------
  Follows sent:   {stats.total_follows:>8}  ({rates["follows_per_hour"]}/h)
  Likes sent:     {stats.total_likes:>8}  ({rates["likes_per_hour"]}/h)
  Views sent:     {stats.total_views:>8}
  Errors:         {stats.total_errors:>8}  ({rates["errors_per_hour"]}/h)

  ACCOUNTS
  --------
  Active:         {acc_stats["active"]:>8}
  Banned:         {acc_stats["banned"]:>8}
  Total:          {acc_stats["total"]:>8}
  Total follows:  {acc_stats["total_follows"]:>8}
  Total likes:    {acc_stats["total_likes"]:>8}

  CYCLE: {stats.current_cycle}
  Press Ctrl+C to stop
{"="*60}''')
