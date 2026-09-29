"""Local Telegram profile snapshot storage; this module performs no network I/O."""

from __future__ import annotations

import pickle

import filelock

from app.core.config import settings
from app.core.log import logger


def load_tg_user_info_cache() -> dict:
    """Read the complete Telegram user information cache."""
    cache_file = settings.TG_USER_INFO_CACHE_PATH
    if not cache_file.exists():
        logger.warning(f"Not found {settings.TG_USER_INFO_CACHE_PATH}")
        return {}
    with open(cache_file, "rb") as file:
        return pickle.load(file)


def save_tg_user_info_cache(cache: dict, cache_file_lock: filelock.FileLock) -> None:
    """Write the cache while holding its cross-process file lock."""
    with cache_file_lock, open(settings.TG_USER_INFO_CACHE_PATH, "wb") as file:
        pickle.dump(cache, file)


__all__ = ["load_tg_user_info_cache", "save_tg_user_info_cache"]
