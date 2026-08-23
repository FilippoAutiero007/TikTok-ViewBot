#!/usr/bin/env python3
import os
import sys
import json
import logging
import argparse
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tiktok_bot.bot import TikTokBot, BotDashboard
from tiktok_bot.accounts import AccountManager
from tiktok_bot.device import generate_batch, load_all_devices
from tiktok_bot.utils import parse_tiktok_url, resolve_sec_uid, validate_tiktok_url

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/tiktok_bot.log'),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)

try:
    from colorama import Fore, init
    init()
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False
    class Fore:
        RED = GREEN = YELLOW = CYAN = WHITE = RESET = ''


BANNER = (
    "\n" + ("#"*60) + "\n"
    "#                                                      #\n"
    "#       TikTok Autonomous Bot - Hybrid Engine          #\n"
    "#       Follow + Like + View (no login required)       #\n"
    "#                                                      #\n"
    "#       Creates fake accounts to boost your profile    #\n"
    "#       Your main account stays 100% safe              #\n"
    "#                                                      #\n"
    + ("#"*60)
)


def _c(color, text, reset=True):
    if HAS_COLOR:
        return color + text + (Fore.RESET if reset else "")
    return text


def cmd_run(args):
    print(BANNER)

    target = args.target
    if not validate_tiktok_url(target):
        print(_c(Fore.RED, "Invalid TikTok URL"))
        return

    parsed = parse_tiktok_url(target)
    username = parsed.get('username')

    if not username:
        print(_c(Fore.RED, "Could not extract username from URL"))
        return

    print(_c(Fore.GREEN, f"Resolving @{username}..."))
    sec_uid = resolve_sec_uid(username)

    if not sec_uid:
        print(_c(Fore.YELLOW, "Could not resolve sec_uid, will try during runtime"))
    else:
        print(_c(Fore.GREEN, f"Found: {sec_uid[:30]}..."))

    actions = []
    if args.follows > 0 or not args.no_follow:
        actions.append('follow')
    if args.likes > 0 or not args.no_like:
        actions.append('like')
    if args.views > 0:
        actions.append('view')

    if not actions:
        actions = ['follow', 'like']

    if args.no_delay:
        min_d = 0
        max_d = 0
    elif args.delay is not None:
        min_d = args.delay
        max_d = args.delay
    else:
        min_d = args.min_delay
        max_d = args.max_delay

    config = {
        'min_delay': min_d,
        'max_delay': max_d,
        'accounts_per_batch': args.batch_size,
        'auto_create_accounts': True,
        'target_follows': args.follows,
        'target_likes': args.likes,
        'proxy': args.proxy,
    }

    bot = TikTokBot(
        target_url=target,
        target_sec_uid=sec_uid,
        actions=actions,
        config=config,
    )

    am = AccountManager()
    print(_c(Fore.GREEN, f"Active accounts: {len(am.accounts)}"))

    if len(am.accounts) < 3:
        print(_c(Fore.YELLOW, "Generating device configs..."))
        generate_batch(5)
        print(_c(Fore.GREEN, "Done. Run account creation to populate."))

    if args.dashboard:
        dashboard = BotDashboard(bot)
        import threading
        d_thread = threading.Thread(target=dashboard.start, daemon=True)
        d_thread.start()

    bot.start()


def cmd_register(args):
    print(BANNER)
    am = AccountManager()

    count = args.count
    proxy = args.proxy
    email = args.email
    password = args.password

    if args.batch:
        print(_c(Fore.CYAN, f"Registering {count} accounts (batch mode)..."))
        results = am.register_batch(count, proxy=proxy)
        print("")
        print(_c(Fore.GREEN, "Batch Registration Complete"))
        print(f"  Successful:  {results['success']}")
        print(f"  Failed:      {results['failed']}")
        print(f"  Total:       {count}")
        print("")
    else:
        if email and password:
            print(_c(Fore.CYAN, "Registering single account..."))
            account = am.register_account(email=email, password=password, proxy=proxy)
            if account:
                print("")
                print(_c(Fore.GREEN, "Account Registered Successfully!"))
                print(f"  Username:  {account.username}")
                print(f"  Email:     {account.email}")
                print(f"  User ID:   {account.user_id}")
                print(f"  Status:    {account.status}")
                print("")
            else:
                print(_c(Fore.RED, "Registration failed. Check logs for details."))
        else:
            print(_c(Fore.YELLOW, "Provide --email and --password for single registration, or use --batch for batch mode."))
            print("")
            print("Examples:")
            print("  python main.py register --batch --count 5")
            print("  python main.py register --email test@example.com --password MyPass123")
            print("  python main.py register --batch --count 10 --proxy socks5://127.0.0.1:1080")
            print("")


def cmd_login(args):
    print(BANNER)
    am = AccountManager()

    username = args.username
    password = args.password

    if not username or not password:
        print(_c(Fore.RED, "Provide --username and --password"))
        return

    is_email = '@' in username
    print(_c(Fore.CYAN, f"Logging in as {username}..."))

    account = am.login_account(username, password, is_email=is_email, proxy=args.proxy)
    if account:
        print("")
        print(_c(Fore.GREEN, "Login Successful!"))
        print(f"  Username:  {account.username}")
        print(f"  User ID:   {account.user_id}")
        print(f"  Status:    {account.status}")
        print("")
    else:
        print(_c(Fore.RED, "Login failed. Check logs for details."))


def cmd_create_accounts(args):
    print(BANNER)
    am = AccountManager()

    count = args.count
    print(_c(Fore.CYAN, f"Creating {count} account configurations..."))

    for i in range(count):
        account = am.create_account(
            email=args.email,
            password=args.password,
            username=args.username,
        )
        account.save()
        msg = f'  [{i+1}/{count}] {account.username} - {account.email}'
        print(_c(Fore.GREEN, msg) if HAS_COLOR else msg)

    print("")
    print(_c(Fore.GREEN, f"Created {count} accounts. Use 'register' to activate them on TikTok."))


def cmd_devices(args):
    print(BANNER)
    if args.generate:
        print(_c(Fore.CYAN, f"Generating {args.generate} device configs..."))
        devices = generate_batch(args.generate)
        for d in devices:
            print(f'  {d["device_id"]} - {d["model"]} (Android {d["android_version"]})')
        print(_c(Fore.GREEN, "Done."))
    else:
        devices = load_all_devices()
        print(_c(Fore.GREEN, f"Found {len(devices)} device configs"))
        for d in devices[:20]:
            print(f'  {d["device_id"]} - {d["model"]} (Android {d["android_version"]})')


def cmd_stats(args):
    print(BANNER)
    am = AccountManager()
    stats = am.get_stats()

    print("")
    print(_c(Fore.CYAN, "ACCOUNT STATISTICS"))
    print("")
    print(f"  Total accounts:    {stats['total']}")
    print(f"  Active:            {_c(Fore.GREEN, str(stats['active']))}")
    print(f"  Banned:            {_c(Fore.RED, str(stats['banned']))}")
    print(f"")
    print(f"  Total follows:     {stats['total_follows']}")
    print(f"  Total likes:       {stats['total_likes']}")
    print(f"  Total views:       {stats['total_views']}")
    print("")


def cmd_config(args):
    print(BANNER)
    config_path = 'config_bot.json'
    if args.show:
        if os.path.exists(config_path):
            with open(config_path) as f:
                print(json.dumps(json.load(f), indent=2))
        else:
            print('No config file found. Using defaults.')
    elif args.init:
        default_config = {
            'min_delay': 2,
            'max_delay': 8,
            'accounts_per_batch': 3,
            'max_actions_per_account': 5,
            'auto_create_accounts': True,
            'target_follows': 0,
            'target_likes': 0,
            'proxy': None,
            'target_url': '',
        }
        with open(config_path, 'w') as f:
            json.dump(default_config, f, indent=2)
        print(_c(Fore.GREEN, f"Config created: {config_path}"))


def main():
    parser = argparse.ArgumentParser(
        description='TikTok Autonomous Bot',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py register --batch --count 5
  python main.py register --email test@example.com --password MyPass123
  python main.py login --username test@example.com --password MyPass123
  python main.py run --target https://www.tiktok.com/@username
  python main.py run --target https://www.tiktok.com/@username --follows 100 --likes 50
  python main.py devices --generate 5
  python main.py stats
        """
    )
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    register_parser = subparsers.add_parser('register', help='Register new accounts on TikTok')
    register_parser.add_argument('--batch', action='store_true', help='Batch mode: register multiple accounts')
    register_parser.add_argument('--count', '-n', type=int, default=1, help='Number of accounts to register (batch mode)')
    register_parser.add_argument('--email', default=None, help='Email for single registration')
    register_parser.add_argument('--password', default=None, help='Password for single registration')
    register_parser.add_argument('--proxy', default=None, help='Proxy (socks5://host:port)')

    login_parser = subparsers.add_parser('login', help='Login to existing TikTok account')
    login_parser.add_argument('--username', '-u', required=True, help='Username or email')
    login_parser.add_argument('--password', '-p', required=True, help='Password')
    login_parser.add_argument('--proxy', default=None, help='Proxy (socks5://host:port)')

    run_parser = subparsers.add_parser('run', help='Start the bot')
    run_parser.add_argument('--target', '-t', required=True, help='TikTok profile/video URL')
    run_parser.add_argument('--follows', type=int, default=0, help='Target follows (0=unlimited)')
    run_parser.add_argument('--likes', type=int, default=0, help='Target likes (0=unlimited)')
    run_parser.add_argument('--views', type=int, default=0, help='Target views (0=unlimited)')
    run_parser.add_argument('--no-follow', action='store_true', help='Disable follow action')
    run_parser.add_argument('--no-like', action='store_true', help='Disable like action')
    run_parser.add_argument('--min-delay', type=float, default=0, help='Min delay between actions in seconds')
    run_parser.add_argument('--max-delay', type=float, default=2, help='Max delay between actions in seconds')
    run_parser.add_argument('--delay', type=float, default=None, help='Fixed delay (overrides min/max)')
    run_parser.add_argument('--no-delay', action='store_true', help='No delay at all')
    run_parser.add_argument('--batch-size', type=int, default=3, help='Accounts per batch')
    run_parser.add_argument('--proxy', default=None, help='Proxy (socks5://host:port)')
    run_parser.add_argument('--dashboard', action='store_true', help='Show live dashboard')

    create_parser = subparsers.add_parser('create-accounts', help='Create local account configs (not registered on TikTok)')
    create_parser.add_argument('--count', '-n', type=int, default=5, help='Number of accounts')
    create_parser.add_argument('--email', default=None, help='Specific email')
    create_parser.add_argument('--password', default=None, help='Specific password')
    create_parser.add_argument('--username', default=None, help='Specific username')

    devices_parser = subparsers.add_parser('devices', help='Manage device configs')
    devices_parser.add_argument('--generate', '-g', type=int, help='Generate N device configs')

    subparsers.add_parser('stats', help='Show account statistics')

    config_parser = subparsers.add_parser('config', help='Manage config')
    config_parser.add_argument('--show', action='store_true', help='Show current config')
    config_parser.add_argument('--init', action='store_true', help='Create default config')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        'register': cmd_register,
        'login': cmd_login,
        'run': cmd_run,
        'create-accounts': cmd_create_accounts,
        'devices': cmd_devices,
        'stats': cmd_stats,
        'config': cmd_config,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
