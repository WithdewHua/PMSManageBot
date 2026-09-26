import asyncio
import pickle

import aiohttp
import filelock
from telegram.ext import ContextTypes

from app.core.config import settings
from app.core.log import logger


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


from app.core.http import get_thread_safe_session


async def send_message_by_url(
    chat_id: int | str,
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

    def _normalize_chat_id(value: int | str) -> int | str:
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
        if s.startswith(("http://", "https://")):
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
    if isinstance(chat_id, str) and chat_id.startswith(("http://", "https://")):
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

        except (TimeoutError, aiohttp.ClientError, aiohttp.ServerTimeoutError) as e:
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


def _save_tg_user_info_cache(cache: dict, cache_file_lock: filelock.FileLock) -> None:
    """Write the cache while holding its cross-process file lock (off the event loop)."""
    with cache_file_lock, open(settings.TG_USER_INFO_CACHE_PATH, "wb") as f:
        pickle.dump(cache, f)


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
