"""Telegram Bot API message transport."""

from __future__ import annotations

import asyncio

import aiohttp
from telegram.ext import ContextTypes

from app.core.config import settings
from app.core.http import get_thread_safe_session
from app.core.log import logger


async def send_message(chat_id, text: str, context: ContextTypes.DEFAULT_TYPE, **kargs):
    """Send a Telegram message through a bot application context."""
    retry = 10
    while retry > 0:
        try:
            if "connect_timeout" not in kargs:
                kargs["connect_timeout"] = 3
            await context.bot.send_message(chat_id=chat_id, text=text, **kargs)
            break
        except Exception as error:
            logger.error(f"Error: {error}, retrying in 1 seconds...")
            await asyncio.sleep(1)
            retry -= 1


async def send_message_by_url(
    chat_id: int | str,
    text: str,
    token: str = settings.TG_API_TOKEN,
    max_retries: int = 10,
    **kwargs,
) -> bool:
    """Send a Telegram sendMessage request with legacy validation and retries."""

    def _normalize_chat_id(value: int | str) -> int | str:
        if isinstance(value, int):
            return value
        value = str(value).strip()
        if value.startswith(("http://", "https://", "@")):
            return value
        if value.lstrip("-").isdigit():
            try:
                return int(value)
            except Exception:
                return value
        return value

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
    session = await get_thread_safe_session()

    for attempt in range(max_retries):
        try:
            logger.debug(
                f"Attempt {attempt + 1}/{max_retries}: Sending message to {chat_id}"
            )
            async with session.post(url, data=data) as response:
                content_type = response.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    payload = await response.json(content_type=None)
                else:
                    payload = {"raw": await response.text()}

                if (
                    response.status == 200
                    and isinstance(payload, dict)
                    and payload.get("ok")
                ):
                    logger.info(f"Message sent successfully to {chat_id}")
                    return True

                description = (
                    payload.get("description") if isinstance(payload, dict) else None
                )
                logger.warning(
                    "Telegram sendMessage failed: status=%s chat_id=%s description=%s payload=%s",
                    response.status,
                    chat_id,
                    description,
                    payload,
                )
                if response.status in (400, 401, 403, 404):
                    return False
                if response.status == 429 and isinstance(payload, dict):
                    retry_after = payload.get("parameters", {}).get("retry_after")
                    if isinstance(retry_after, int) and retry_after > 0:
                        await asyncio.sleep(min(retry_after, 30))
                        continue
        except (TimeoutError, aiohttp.ClientError, aiohttp.ServerTimeoutError) as error:
            logger.warning(
                f"Network error on attempt {attempt + 1}: {type(error).__name__}: {error}"
            )
            if attempt == max_retries - 1:
                logger.error(
                    f"Failed to send message to {chat_id} after {max_retries} attempts: {error}"
                )
                return False
        except Exception as error:
            logger.error(
                f"Unexpected error on attempt {attempt + 1}: {type(error).__name__}: {error}"
            )
            if attempt == max_retries - 1:
                logger.error(
                    f"Failed to send message to {chat_id} after {max_retries} attempts: {error}"
                )
                return False

        if attempt < max_retries - 1:
            await asyncio.sleep(min(2**attempt, 10))

    return False
