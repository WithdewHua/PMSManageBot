"""Post-commit luckywheel notifications."""

from app.core.config import settings
from app.core.log import logger
from app.integrations.telegram.messaging import send_message_by_url
from app.integrations.telegram.profiles import get_user_name_from_tg_id


async def notify_invite_code_awarded(tg_id: int, *, privileged: bool) -> None:
    """Notify every configured administrator without affecting the committed spin."""
    label = "特权" if privileged else ""
    for chat_id in settings.TG_ADMIN_CHAT_ID:
        try:
            await send_message_by_url(
                chat_id=chat_id,
                text=f"用户 {get_user_name_from_tg_id(tg_id)} 在转盘中获得了{label}邀请码",
                token=settings.TG_API_TOKEN,
            )
        except Exception as error:
            logger.error(
                f"邀请码管理员通知发送失败 (chat_id={chat_id}，不影响抽奖结果): {error}"
            )


__all__ = ["notify_invite_code_awarded"]
