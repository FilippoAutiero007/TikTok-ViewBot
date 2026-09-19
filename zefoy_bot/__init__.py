"""Zefoy.com view bot - standalone automation for zefoy.com service."""

# Re-export public API from .bot so that both work:
#   from zefoy_bot.bot import decode, ...
#   from zefoy_bot import decode, ...
# plus `patch('zefoy_bot.sleep')` in tests forwards to zefoy_bot.bot.
from .bot import *  # noqa: F401,F403
from . import bot as _bot  # noqa: E402
import sys as _sys  # noqa: E402

# Keep a reference so `import zefoy_bot.bot` and `import zefoy_bot`
# share the same objects for mutable patching.
_bot_module = _sys.modules.get('zefoy_bot.bot')


def __getattr__(name):
    # Fall back to zefoy_bot.bot for any name not defined here.
    # This makes `zefoy_bot.CSV_FILE`, `zefoy_bot.SqliteStats`, etc. work
    # even if `from .bot import *` didn't pick them up.
    mod = _sys.modules.get('zefoy_bot.bot')
    if mod is not None and hasattr(mod, name):
        return getattr(mod, name)
    raise AttributeError(f"module 'zefoy_bot' has no attribute {name!r}")


def __setattr__(name, value):
    # Forward attribute writes to zefoy_bot.bot as well, so that
    # `patch('zefoy_bot.sleep')`, `zefoy_bot.CSV_FILE = ...`, etc.
    # actually affect the running bot code in zefoy_bot.bot.
    globals()[name] = value
    mod = _sys.modules.get('zefoy_bot.bot')
    if mod is not None and mod is not _sys.modules.get('zefoy_bot'):
        try:
            setattr(mod, name, value)
        except Exception:
            pass


def __dir__():
    mod = _sys.modules.get('zefoy_bot.bot')
    base = set(globals().keys())
    if mod is not None:
        base.update(n for n in dir(mod) if not n.startswith('_'))
    return sorted(base)
