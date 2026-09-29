"""Telegram profile refresh and local snapshot lookup."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from time import time

import filelock

from app.core.config import settings
from app.core.http import get_thread_safe_session
from app.core.log import logger
from app.integrations.telegram.client import get_tg_user_photo_url
from app.integrations.telegram.profile_cache import (
    load_tg_user_info_cache,
    save_tg_user_info_cache,
)


async def refresh_tg_user_profile(
    tg_id: int, token: str = settings.TG_API_TOKEN
) -> None:
    """Refresh one Telegram profile cache entry."""
    try:
        cache_file_lock = filelock.FileLock(
            str(settings.TG_USER_INFO_CACHE_PATH) + ".lock"
        )
        cache = await asyncio.to_thread(load_tg_user_info_cache)
        cached = cache.get(tg_id)
        if cached and time() - cached.get("added", 0) <= 24 * 3600:
            return
        session = await get_thread_safe_session()
        retry = 10
        result = {}
        while retry > 0:
            try:
                async with session.get(
                    url=f"https://api.telegram.org/bot{token}/getChat?chat_id={tg_id}"
                ) as response:
                    if response.status != 200:
                        break
                    result = (await response.json()).get("result", {})
            except Exception as error:
                logger.error(f"Error: {error}, retrying in 1 seconds...")
                await asyncio.sleep(1)
                retry -= 1
                continue
            break
        if retry == 0:
            return
        user_info = {
            "first_name": result.get("first_name"),
            "username": result.get("username"),
            "added": time(),
        }
        photo_url = await get_tg_user_photo_url(tg_id, token=token)
        if photo_url:
            photo_path = settings.TG_USER_PROFILE_CACHE_PATH / f"{tg_id}.jpg"
            try:
                async with session.get(photo_url) as response:
                    if response.status == 200:
                        content = await response.read()
                        await asyncio.to_thread(photo_path.write_bytes, content)
            except Exception as error:
                logger.error(f"Error: {error}")
            user_info["photo_url"] = (
                f"{settings.WEBAPP_URL.strip('/')}/pics/{tg_id}.jpg"
            )
        cache[tg_id] = user_info
        await asyncio.to_thread(save_tg_user_info_cache, cache, cache_file_lock)
    except Exception as error:
        logger.error(f"Refresh Telegram profile failed: {error}")


async def refresh_tg_user_info(
    tg_ids: Iterable[int], token: str = settings.TG_API_TOKEN
) -> None:
    """Refresh profile snapshots for the supplied identity IDs."""
    try:
        cache_file_lock = filelock.FileLock(
            str(settings.TG_USER_INFO_CACHE_PATH) + ".lock"
        )
        cache = {}
        session = await get_thread_safe_session()
        for user_id in tg_ids:
            if settings.TG_USER_INFO_CACHE_PATH.exists():
                cache = await asyncio.to_thread(load_tg_user_info_cache)
            if (
                user_id in cache
                and time() - cache.get(user_id).get("added") <= 24 * 3600
            ):
                logger.info(
                    f"{cache.get(user_id).get('username')}({user_id}) info is not expired, skip"
                )
                continue
            retry = 10
            result = {}
            while retry > 0:
                try:
                    async with session.get(
                        url=f"https://api.telegram.org/bot{token}/getChat?chat_id={user_id}"
                    ) as response:
                        if response.status != 200:
                            logger.error(f"Error: failed to get info. for {user_id}")
                            break
                        result = (await response.json()).get("result", {})
                except Exception as error:
                    logger.error(f"Error: {error}, retrying in 1 seconds...")
                    await asyncio.sleep(1)
                    retry -= 1
                    continue
                else:
                    break
            if retry == 0:
                continue
            user_info = {
                "first_name": result.get("first_name"),
                "username": result.get("username"),
                "added": time(),
            }
            photo_url = await get_tg_user_photo_url(user_id, token=token)
            if photo_url:
                photo_path = settings.TG_USER_PROFILE_CACHE_PATH / f"{user_id}.jpg"
                try:
                    async with session.get(photo_url) as response:
                        if response.status == 200:
                            content = await response.read()
                            await asyncio.to_thread(photo_path.write_bytes, content)
                except Exception as error:
                    logger.error(f"Error: {error}")
                user_info["photo_url"] = (
                    f"{settings.WEBAPP_URL.strip('/')}/pics/{user_id}.jpg"
                )
            cache[user_id] = user_info
            logger.info(f"Updated tg user info: {user_info.get('username')}({user_id})")
            await asyncio.to_thread(save_tg_user_info_cache, cache, cache_file_lock)
    except Exception as error:
        logger.error(f"Refresh user tg info failed: {error}")


def get_user_info_from_tg_id(chat_id: int, token=settings.TG_API_TOKEN):
    """Return one cached Telegram profile without network I/O."""
    return load_tg_user_info_cache().get(chat_id, {})


def get_user_name_from_tg_id(chat_id: int, token=settings.TG_API_TOKEN):
    user_info = get_user_info_from_tg_id(chat_id, token=token)
    return user_info.get("first_name") or user_info.get("username") or chat_id


def get_user_names_from_tg_ids(chat_ids) -> dict:
    """Read the profile cache once and return display names by Telegram ID."""
    ids = [int(i) for i in chat_ids]
    if not ids:
        return {}
    try:
        cache = load_tg_user_info_cache()
    except Exception as error:
        logger.error(f"读取 Telegram 用户缓存失败: {error}")
        cache = {}
    names = {}
    for tg_id in ids:
        info = cache.get(tg_id) or {}
        names[tg_id] = str(info.get("first_name") or info.get("username") or tg_id)
    return names


def get_user_avatar_from_tg_id(chat_id: int, token=settings.TG_API_TOKEN):
    """Return a cached Telegram avatar URL."""
    user_info = get_user_info_from_tg_id(chat_id, token=token)
    return user_info.get("photo_url")


__all__ = [
    "get_user_avatar_from_tg_id",
    "get_user_info_from_tg_id",
    "get_user_name_from_tg_id",
    "get_user_names_from_tg_ids",
    "load_tg_user_info_cache",
    "refresh_tg_user_info",
    "refresh_tg_user_profile",
]
