"""Shim for backwards compatibility - v2 creator is now the main one."""
from .account_creator import TikTokAccountCreator, TikTokAccountCreatorV2, create_accounts_batch, _random_password, _random_birthday

__all__ = ['TikTokAccountCreator', 'TikTokAccountCreatorV2', 'create_accounts_batch']
