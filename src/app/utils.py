#!/usr/bin/env python3

import asyncio
import pickle
import threading
from time import time
from typing import Optional

import aiohttp
import filelock
from app.config import settings
from app.db import DB
from app.emby import Emby
from app.log import logger
from telegram.ext import ContextTypes


# Global session manager to avoid SSL connection issues
class HTTPSessionManager:
    """Manages global HTTP session to avoid connection pool issues"""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._connector: Optional[aiohttp.TCPConnector] = None

    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session"""
        if self._session is None or self._session.closed:
            await self._create_session()
        return self._session

    async def _create_session(self):
        """Create new HTTP session with optimized settings"""
        # Close existing resources if any
        await self.close()

        self._connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=30,
            enable_cleanup_closed=True,
            keepalive_timeout=30,  # 使用 keepalive 而不是 force_close
            ssl=None,
        )

        timeout = aiohttp.ClientTimeout(total=10, connect=5)

        self._session = aiohttp.ClientSession(
            connector=self._connector,
            connector_owner=True,
            trust_env=True,
            timeout=timeout,
        )

    async def close(self):
        """Close session and connector safely"""
        if self._session and not self._session.closed:
            try:
                await self._session.close()
            except Exception as e:
                logger.debug(f"Error closing session: {e}")

        if self._connector:
            try:
                await self._connector.close()
            except Exception as e:
                logger.debug(f"Error closing connector: {e}")

        self._session = None
        self._connector = None


# thread local session
_thread_local_session_manager = threading.local()


async def get_thread_safe_session() -> aiohttp.ClientSession:
    if not hasattr(_thread_local_session_manager, "session_manager"):
        _thread_local_session_manager.session_manager = HTTPSessionManager()
    return await _thread_local_session_manager.session_manager.get_session()


async def send_message(chat_id, text: str, context: ContextTypes.DEFAULT_TYPE, **kargs):
    """send telegram message"""
    retry = 10
    while retry > 0:
        try:
            if "connect_timeout" not in kargs:
                kargs["connect_timeout"] = 3
            await context.bot.send_message(chat_id=chat_id, text=text, **kargs)
            break
        except Exception as e:
            logger.error(f"Error: {e}, retrying in 1 seconds...")
            await asyncio.sleep(1)
            retry -= 1


async def send_message_by_url(
    chat_id,
    text: str,
    token: str = settings.TG_API_TOKEN,
    max_retries: int = 10,
    **kwargs,
) -> bool:
    """Send telegram message by url with improved error handling and retry logic

    Args:
        chat_id: Telegram chat ID
        text: Message text to send
        token: Telegram bot token
        max_retries: Maximum number of retry attempts
        **kwargs: Additional parameters for sendMessage API

    Returns:
        bool: True if message sent successfully, False otherwise

    Raises:
        ValueError: If required parameters are invalid
    """
    # Parameter validation
    if not chat_id:
        raise ValueError("chat_id cannot be empty")
    if not text or not text.strip():
        raise ValueError("text cannot be empty")
    if not token:
        raise ValueError("token cannot be empty")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": text.strip()}
    data.update(kwargs)

    # Use global session manager to avoid connection pool issues
    session = await get_thread_safe_session()

    for attempt in range(max_retries):
        try:
            logger.debug(
                f"Attempt {attempt + 1}/{max_retries}: Sending message to {chat_id}"
            )

            async with session.post(url, data=data) as response:
                response.raise_for_status()
                result = await response.json()

                if result.get("ok"):
                    logger.info(
                        f"Message sent successfully to {chat_id}: {data.get('text')}"
                    )
                    return True
                else:
                    logger.warning(f"Telegram API returned error: {result}")
                    return False

        except (
            aiohttp.ClientError,
            aiohttp.ServerTimeoutError,
            asyncio.TimeoutError,
        ) as e:
            # Network-related errors, worth retrying
            logger.warning(
                f"Network error on attempt {attempt + 1}: {type(e).__name__}: {e}"
            )
            if attempt == max_retries - 1:
                logger.error(
                    f"Failed to send message to {chat_id} after {max_retries} attempts: {e}"
                )
                return False

        except Exception as e:
            # Other errors, may not be worth retrying
            logger.error(
                f"Unexpected error on attempt {attempt + 1}: {type(e).__name__}: {e}"
            )
            if attempt == max_retries - 1:
                logger.error(
                    f"Failed to send message to {chat_id} after {max_retries} attempts: {e}"
                )
                return False

        # Exponential backoff for retries
        if attempt < max_retries - 1:
            wait_time = min(2**attempt, 10)  # Cap at 10 seconds
            logger.debug(f"Waiting {wait_time} seconds before retry...")
            await asyncio.sleep(wait_time)

    return False


def get_user_total_duration(home_stats: dict):
    """Get user's total watched duration"""
    user_total_duration: dict = {}
    for row in home_stats.get("rows", []):
        user_id = row.get("user_id")
        total_duration = float(row.get("total_duration") / 3600)
        user_total_duration.update({user_id: total_duration})
    return user_total_duration


def caculate_credits_fund(unlock_time, unlock_credits: int):
    if not unlock_time:
        return 0
    cur_time = time()
    gap = cur_time - unlock_time
    # 一天内，返还 90%
    if gap <= 3600 * 24:
        return unlock_credits * 0.9
    elif gap <= 3600 * 24 * 7:
        return unlock_credits * 0.7
    elif gap <= 3600 * 24 * 30:
        return unlock_credits * 0.5
    else:
        return 0


def get_user_info_from_tg_id(chat_id, token=settings.TG_API_TOKEN):
    """Get telegram user's info
    cache format: {tg_id: {"first_name": first_name, "username": username, "added": timestamp}}
    """
    cache_file = settings.TG_USER_INFO_CACHE_PATH
    cache = {}
    if not cache_file.exists():
        logger.warning(f"Not found {settings.TG_USER_INFO_CACHE_PATH}")
        return {}
    with open(cache_file, "rb") as f:
        cache = pickle.load(f)
    return cache.get(chat_id, {})


async def get_tg_user_photo_url(tg_id: int, token: str = settings.TG_API_TOKEN):
    """获取 Telegram 头像"""
    session = await get_thread_safe_session()
    retry = 5
    while retry > 0:
        try:
            # 获取用户头像
            async with session.get(
                f"https://api.telegram.org/bot{token}/getUserProfilePhotos?user_id={tg_id}&limit=1",
            ) as photos_response:
                photo_url = None
                if photos_response.status == 200:
                    photos_data = await photos_response.json()
                    if photos_data.get("result", {}).get("total_count", 0) > 0:
                        photo_file_id = photos_data["result"]["photos"][0][0]["file_id"]

                        # 获取文件路径
                        async with session.get(
                            f"https://api.telegram.org/bot{token}/getFile?file_id={photo_file_id}",
                        ) as file_response:
                            if file_response.status == 200:
                                file_data = await file_response.json()
                                if file_data.get("ok"):
                                    file_path = file_data["result"]["file_path"]
                                    photo_url = f"https://api.telegram.org/file/bot{token}/{file_path}"

            return photo_url
        except Exception:
            logger.error(f"Error: failed to get photo for {tg_id}, retrying...")
            await asyncio.sleep(1)
            retry -= 1
    return None


def get_user_name_from_tg_id(chat_id, token=settings.TG_API_TOKEN):
    user_info = get_user_info_from_tg_id(chat_id, token=token)
    return user_info.get("first_name") or user_info.get("username") or chat_id


def get_user_avatar_from_tg_id(chat_id, token=settings.TG_API_TOKEN):
    """从缓存中获取用户头像URL"""
    user_info = get_user_info_from_tg_id(chat_id, token=token)
    return user_info.get("photo_url")


async def refresh_tg_user_info(token: str = settings.TG_API_TOKEN):
    """刷新用户信息"""
    try:
        cache_file_lock = filelock.FileLock(
            str(settings.TG_USER_INFO_CACHE_PATH) + ".lock"
        )
        cache = {}
        db = DB()
        session = await get_thread_safe_session()

        # 从 statistics 表获取所有用户
        stats_users = db.cur.execute("SELECT tg_id FROM statistics").fetchall()
        stats_users = [user[0] for user in stats_users]

        for tg_id in stats_users:
            if settings.TG_USER_INFO_CACHE_PATH.exists():
                with open(settings.TG_USER_INFO_CACHE_PATH, "rb") as f:
                    cache = pickle.load(f)
            # 缓存保留 7 天
            if tg_id in cache:
                if time() - cache.get(tg_id).get("added") <= 7 * 24 * 3600:
                    logger.info(
                        f"{cache.get(tg_id).get('username')}({tg_id}) info is not expired, skip"
                    )
                    continue
            retry = 10
            while retry > 0:
                try:
                    async with session.get(
                        url=f"https://api.telegram.org/bot{token}/getChat?chat_id={tg_id}",
                    ) as response:
                        if response.status != 200:
                            logger.error(f"Error: failed to get info. for {tg_id}")
                            break
                        result = (await response.json()).get("result", {})
                except Exception as e:
                    logger.error(f"Error: {e}, retrying in 1 seconds...")
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
            # 获取用户 photo url
            photo_url = await get_tg_user_photo_url(tg_id, token=token)
            if photo_url:
                # 下载头像到本地
                photo_path = settings.TG_USER_PROFILE_CACHE_PATH / f"{tg_id}.jpg"
                try:
                    async with session.get(
                        photo_url,
                    ) as response:
                        if response.status == 200:
                            content = await response.read()
                            with open(photo_path, "wb") as f:
                                f.write(content)
                except Exception as e:
                    logger.error(f"Error: {e}")
                user_info["photo_url"] = (
                    f"{settings.WEBAPP_URL.strip('/')}/pics/{tg_id}.jpg"
                )
            # add cache
            cache.update({tg_id: user_info})
            logger.info(f"Updated tg user info: {user_info.get('username')}({tg_id})")
            with cache_file_lock:
                with open(settings.TG_USER_INFO_CACHE_PATH, "wb") as f:
                    pickle.dump(cache, f)
    except Exception as e:
        logger.error(f"Refresh user tg info failed: {e}")
    finally:
        db.close()


def refresh_emby_user_info():
    """刷新 emby user info"""
    emby = Emby()
    # 获取所有的 emby 用户名
    try:
        db = DB()

        emby_users = db.cur.execute("SELECT emby_username from emby_user").fetchall()
        emby_users = [user[0] for user in emby_users]
        for user in emby_users:
            emby.get_user_info_from_username(user)
    except Exception as e:
        logger.error(f"Refresh emby user info failed: {e}")
    finally:
        db.close()


class SingletonMeta(type):
    """Singleton metaclass"""

    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


def is_binded_premium_line(line: str) -> bool:
    """检查绑定线路是否为高级线路

    通用函数，适用于 Plex 和 Emby

    Args:
        line: 线路名称

    Returns:
        bool: 是否为高级线路
    """
    for premium_line in settings.PREMIUM_STREAM_BACKEND:
        if premium_line in line:
            return True
    return False


async def cleanup_http_resources():
    """Clean up HTTP resources on application shutdown"""
    if hasattr(_thread_local_session_manager, "session_manager"):
        await _thread_local_session_manager.session_manager.close()
