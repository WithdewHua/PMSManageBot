"""Profile aggregation workflows."""

import asyncio
from time import time

import filelock

from app.core.config import settings
from app.core.http import get_thread_safe_session
from app.core.log import logger
from app.core.telegram import (
    _save_tg_user_info_cache,
    get_tg_user_photo_url,
    load_tg_user_info_cache,
)
from app.domains.identity import service as identity_service


async def refresh_tg_user_info(
    tg_id: int | None = None, token: str = settings.TG_API_TOKEN
) -> None:
    """Refresh Telegram profile cache for one user or all known users."""
    try:
        cache_file_lock = filelock.FileLock(
            str(settings.TG_USER_INFO_CACHE_PATH) + ".lock"
        )
        cache = {}
        session = await get_thread_safe_session()
        stats_users = (
            identity_service.list_statistics_tg_ids() if tg_id is None else [tg_id]
        )
        for user_id in stats_users:
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
            await asyncio.to_thread(_save_tg_user_info_cache, cache, cache_file_lock)
    except Exception as error:
        logger.error(f"Refresh user tg info failed: {error}")


__all__ = ["refresh_tg_user_info"]
