"""Telegram administrator notification delivery."""

from __future__ import annotations

from app.core.config import settings
from app.core.log import logger
from app.integrations.telegram.messaging import send_message_by_url


async def notify_admins_by_url(text: str, **kwargs) -> None:
    """Send a Telegram message to every configured administrator."""
    for admin in settings.TG_ADMIN_CHAT_ID:
        try:
            success = await send_message_by_url(chat_id=admin, text=text, **kwargs)
            if not success:
                logger.warning(f"发送管理员通知失败 {admin}")
        except Exception as error:
            logger.warning(f"发送管理员通知失败 {admin}: {error}")


__all__ = ["notify_admins_by_url"]
