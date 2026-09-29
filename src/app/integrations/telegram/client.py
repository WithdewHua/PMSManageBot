"""Telegram Bot API profile-photo client."""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.http import get_thread_safe_session
from app.core.log import logger


async def get_tg_user_photo_url(
    tg_id: int, token: str = settings.TG_API_TOKEN
) -> str | None:
    """Fetch a Telegram user's first profile photo URL with legacy retries."""
    session = await get_thread_safe_session()
    retry = 5
    while retry > 0:
        try:
            async with session.get(
                f"https://api.telegram.org/bot{token}/getUserProfilePhotos?user_id={tg_id}&limit=1"
            ) as photos_response:
                photo_url = None
                if photos_response.status == 200:
                    photos_data = await photos_response.json()
                    if photos_data.get("result", {}).get("total_count", 0) > 0:
                        photo_file_id = photos_data["result"]["photos"][0][0]["file_id"]
                        async with session.get(
                            f"https://api.telegram.org/bot{token}/getFile?file_id={photo_file_id}"
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


__all__ = ["get_tg_user_photo_url"]
