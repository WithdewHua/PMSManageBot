#!/usr/bin/env python3

import asyncio
import pickle
import threading
from time import time
from typing import Optional, Union

import aiohttp
import filelock
from app.config import settings
from app.databases.session import get_session as get_db_session
from app.log import logger
from app.models.models import EmbyUser, Statistics
from app.modules.emby import Emby
from sqlalchemy import select
from telegram.ext import ContextTypes


def format_traffic_size(bytes_size: int) -> str:
    """
    格式化流量大小为可读格式
    :param bytes_size: 字节大小
    :return: 格式化后的字符串
    """
    if bytes_size == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    size = float(bytes_size)

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    else:
        return f"{size:.2f} {units[unit_index]}"


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
    chat_id: Union[int, str],
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

    def _normalize_chat_id(value: Union[int, str]) -> Union[int, str]:
        """Normalize chat_id.

        Accepts:
        - int / numeric string (user id / group id)
        - @channelusername

        Rejects (returns as-is but will likely fail):
        - t.me links / invite links (not a valid chat_id)
        """
        if isinstance(value, int):
            return value
        s = str(value).strip()
        # common mistake: passing an invite link like https://t.me/+xxxx
        if s.startswith("http://") or s.startswith("https://"):
            return s
        if s.startswith("@"):
            return s
        if s.lstrip("-").isdigit():
            # keep negative ids for groups/supergroups
            try:
                return int(s)
            except Exception:
                return s
        return s

    # Parameter validation
    if chat_id is None:
        raise ValueError("chat_id cannot be empty")
    chat_id = _normalize_chat_id(chat_id)
    if isinstance(chat_id, str) and (
        chat_id.startswith("http://") or chat_id.startswith("https://")
    ):
        raise ValueError(
            f"chat_id looks like a URL ({chat_id}). Telegram sendMessage requires a chat id (numeric id or @username), not a t.me link."
        )
    if not text or not text.strip():
        raise ValueError("text cannot be empty")
    if not token:
        raise ValueError("token cannot be empty")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": text.strip(), **kwargs}

    # Use global session manager to avoid connection pool issues
    session = await get_thread_safe_session()

    for attempt in range(max_retries):
        try:
            logger.debug(
                f"Attempt {attempt + 1}/{max_retries}: Sending message to {chat_id}"
            )

            async with session.post(url, data=data) as response:
                # Always read body for better diagnostics (Telegram returns useful description on 400)
                content_type = response.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    payload = await response.json(content_type=None)
                else:
                    raw_text = await response.text()
                    payload = {"raw": raw_text}

                if (
                    response.status == 200
                    and isinstance(payload, dict)
                    and payload.get("ok")
                ):
                    logger.info(f"Message sent successfully to {chat_id}")
                    return True

                # Telegram errors are usually not retryable (400/403), but log description.
                description = None
                if isinstance(payload, dict):
                    description = payload.get("description")
                logger.warning(
                    "Telegram sendMessage failed: status=%s chat_id=%s description=%s payload=%s",
                    response.status,
                    chat_id,
                    description,
                    payload,
                )

                # Don't retry on client errors except 429
                if response.status in (400, 401, 403, 404):
                    return False
                if response.status == 429 and isinstance(payload, dict):
                    retry_after = payload.get("parameters", {}).get("retry_after")
                    if isinstance(retry_after, int) and retry_after > 0:
                        await asyncio.sleep(min(retry_after, 30))
                        continue

        except (
            aiohttp.ClientError,
            aiohttp.ServerTimeoutError,
            asyncio.TimeoutError,
        ) as e:
            logger.warning(
                f"Network error on attempt {attempt + 1}: {type(e).__name__}: {e}"
            )
            if attempt == max_retries - 1:
                logger.error(
                    f"Failed to send message to {chat_id} after {max_retries} attempts: {e}"
                )
                return False

        except Exception as e:
            logger.error(
                f"Unexpected error on attempt {attempt + 1}: {type(e).__name__}: {e}"
            )
            if attempt == max_retries - 1:
                logger.error(
                    f"Failed to send message to {chat_id} after {max_retries} attempts: {e}"
                )
                return False

        if attempt < max_retries - 1:
            wait_time = min(2**attempt, 10)
            logger.debug(f"Waiting {wait_time} seconds before retry...")
            await asyncio.sleep(wait_time)

    return False


async def notify_admins_by_url(text: str, **kwargs) -> None:
    """Send a Telegram message to every configured admin."""
    for admin in settings.TG_ADMIN_CHAT_ID:
        try:
            success = await send_message_by_url(chat_id=admin, text=text, **kwargs)
            if not success:
                logger.warning(f"发送管理员通知失败 {admin}")
        except Exception as e:
            logger.warning(f"发送管理员通知失败 {admin}: {e}")


def get_service_label(service: str) -> tuple[str, str]:
    service_name = service.upper()
    service_emoji = "🎬" if service == "plex" else "📺"
    return service_name, service_emoji


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
    gap = cur_time - float(unlock_time)
    # 一天内，返还 90%
    if gap <= 3600 * 24:
        return unlock_credits * 0.9
    elif gap <= 3600 * 24 * 7:
        return unlock_credits * 0.7
    elif gap <= 3600 * 24 * 30:
        return unlock_credits * 0.5
    else:
        return 0


def load_tg_user_info_cache() -> dict:
    """读取整个 Telegram 用户信息缓存。

    cache format: {tg_id: {"first_name": first_name, "username": username, "added": timestamp}}
    """
    cache_file = settings.TG_USER_INFO_CACHE_PATH
    if not cache_file.exists():
        logger.warning(f"Not found {settings.TG_USER_INFO_CACHE_PATH}")
        return {}
    with open(cache_file, "rb") as f:
        return pickle.load(f)


def get_user_info_from_tg_id(chat_id: int, token=settings.TG_API_TOKEN):
    """Get telegram user's info
    cache format: {tg_id: {"first_name": first_name, "username": username, "added": timestamp}}
    """
    return load_tg_user_info_cache().get(chat_id, {})


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


def get_user_name_from_tg_id(chat_id: int, token=settings.TG_API_TOKEN):
    user_info = get_user_info_from_tg_id(chat_id, token=token)
    return user_info.get("first_name") or user_info.get("username") or chat_id


def get_user_names_from_tg_ids(chat_ids) -> dict:
    """批量取显示名，返回 {tg_id: 名字}。缓存文件**只读一次**。

    `get_user_info_from_tg_id` 每次调用都要 open + `pickle.load` 整个缓存，逐行
    调用等于把同一个文件反序列化 N 遍；在 async 端点里那是同步阻塞事件循环。
    统一回落成 `str`：查不到名字时单条版本会回落成 int，直接塞进 `str` 字段会让
    整个响应模型校验失败。
    """
    ids = [int(i) for i in chat_ids]
    if not ids:
        return {}
    try:
        cache = load_tg_user_info_cache()
    except Exception as e:
        logger.error(f"读取 Telegram 用户缓存失败: {e}")
        cache = {}
    names = {}
    for tg_id in ids:
        info = cache.get(tg_id) or {}
        names[tg_id] = str(info.get("first_name") or info.get("username") or tg_id)
    return names


def get_user_avatar_from_tg_id(chat_id: int, token=settings.TG_API_TOKEN):
    """从缓存中获取用户头像URL"""
    user_info = get_user_info_from_tg_id(chat_id, token=token)
    return user_info.get("photo_url")


async def refresh_tg_user_info(
    tg_id: Optional[int] = None, token: str = settings.TG_API_TOKEN
):
    """刷新用户信息"""
    try:
        cache_file_lock = filelock.FileLock(
            str(settings.TG_USER_INFO_CACHE_PATH) + ".lock"
        )
        cache = {}

        session = await get_thread_safe_session()

        if not tg_id:
            # 从 statistics 表获取所有用户
            with get_db_session() as db_session:
                stmt = select(Statistics.tg_id)
                stats_users = [
                    tg_id for tg_id in db_session.execute(stmt).scalars().all()
                ]
        else:
            stats_users = [tg_id]
        for tg_id in stats_users:
            if settings.TG_USER_INFO_CACHE_PATH.exists():
                with open(settings.TG_USER_INFO_CACHE_PATH, "rb") as f:
                    cache = pickle.load(f)
            # 缓存保留 1 天
            if tg_id in cache:
                if time() - cache.get(tg_id).get("added") <= 1 * 24 * 3600:
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


def refresh_emby_user_info(emby_username: Optional[str] = None):
    """刷新 emby user info"""
    emby = Emby()
    # 获取所有的 emby 用户名
    try:
        if not emby_username:
            with get_db_session() as session:
                stmt = select(EmbyUser.emby_username)
                emby_users = [
                    username for username in session.execute(stmt).scalars().all()
                ]
        else:
            emby_users = [emby_username]

        for user in emby_users:
            emby.get_user_info_from_username(user)
    except Exception as e:
        logger.error(f"Refresh emby user info failed: {e}")


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


def normalize_line_domain(line_domain: str) -> str:
    """
    将线路域名规范化为纯主机名（host 或 host:port），去除协议前缀和路径后缀。

    数据库 line_traffic_stats/line_traffic_monthly_stats 中的 line 字段存储的是
    不含协议、不含路径的主机名（例如 example.com:8096），而 CustomLine.domain
    用户提交时可能包含协议前缀（https://）或路径后缀，需要统一处理后才能匹配。

    示例：
        "https://example.com:8096"      -> "example.com:8096"
        "https://example.com:8096/path" -> "example.com:8096"
        "example.com:8096/path"         -> "example.com:8096"
        "example.com:8096"              -> "example.com:8096"
        "example.com"                   -> "example.com"

    Args:
        line_domain: 原始线路域名

    Returns:
        规范化后的纯主机名
    """
    from urllib.parse import urlparse

    domain = line_domain.strip()
    # 如果不含协议前缀，urlparse 无法正确解析 netloc，需手动补充
    if "://" not in domain:
        domain = "dummy://" + domain
    parsed = urlparse(domain)
    # netloc 即为 host(:port)，若解析失败则回退到去除路径的原始值
    netloc = parsed.netloc or domain.split("/")[0].replace("dummy://", "")
    return netloc


async def cleanup_http_resources():
    """Clean up HTTP resources on application shutdown"""
    if hasattr(_thread_local_session_manager, "session_manager"):
        await _thread_local_session_manager.session_manager.close()
