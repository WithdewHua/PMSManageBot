"""Vaultwarden redemption notifications."""

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.utils.utils import send_message_by_url


async def _notify_admins_vaultwarden_redeem(
    user_id: int,
    user_name: str,
    email: str,
    required_credits: float,
    new_credits: float,
):
    """后台发送 Vaultwarden 兑换成功管理员通知"""
    for admin in settings.TG_ADMIN_CHAT_ID:
        try:
            await send_message_by_url(
                chat_id=admin,
                text=(
                    f"📬 <b>Vaultwarden 兑换通知</b>\n\n"
                    f"用户 <b>{user_name}</b>（TG ID: <code>{user_id}</code>）\n"
                    f"成功兑换 Vaultwarden 账户\n"
                    f"邮箱：<code>{email}</code>\n"
                    f"消耗积分：{required_credits}\n"
                    f"剩余积分：{new_credits}"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"发送管理员通知失败 {admin}: {e}")
