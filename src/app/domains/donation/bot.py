"""Donation Telegram bot commands."""

from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.core.config import settings
from app.core.log import logger
from app.domains.donation import (
    exceptions as donation_exceptions,
)
from app.domains.donation import (
    notifications,
)
from app.domains.donation import (
    service as donation_service,
)
from app.integrations.telegram.messaging import send_message
from app.integrations.telegram.profiles import get_user_name_from_tg_id


# 管理员命令: 设置捐赠信息
async def set_donation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    if chat_id not in settings.TG_ADMIN_CHAT_ID:
        await send_message(chat_id=chat_id, text="错误：越权操作", context=context)
        return
    text = update.message.text
    text = text.split()
    if len(text) not in [3, 4]:
        await send_message(
            chat_id=chat_id, text="错误：请按照格式填写", context=context
        )
        return
    try:
        tg_id = int(text[1])
        donation = float(text[2])
    except (ValueError, TypeError):
        await send_message(
            chat_id=chat_id, text="错误：请按照格式填写", context=context
        )
        return

    add_credits = len(text) == 3

    try:
        _cumulative, credits_delta = donation_service.bot_record_donation(
            tg_id=tg_id,
            amount=donation,
            add_credits=add_credits,
        )
    except donation_exceptions.DonationUserNotFound:
        await send_message(
            chat_id=chat_id, text=f"错误：用户 {tg_id} 不存在，请确认", context=context
        )
        return
    except Exception as e:
        logger.error(f"Bot set_donation error: {e}")
        await send_message(
            chat_id=chat_id, text="错误：更新捐赠金额失败，请检查", context=context
        )
        return

    if credits_delta is not None:
        await notifications.send_bot_donation_credit_notification(
            tg_id=tg_id,
            delta=credits_delta,
            context=context,
        )

    await send_message(
        chat_id=chat_id,
        text=f"信息：成功为 {get_user_name_from_tg_id(tg_id)} 设置捐赠金额 {donation}",
        context=context,
    )


set_donation_handler = CommandHandler("set_donation", set_donation)

__all__ = ["set_donation", "set_donation_handler"]
