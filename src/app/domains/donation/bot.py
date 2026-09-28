from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.core.config import settings
from app.core.telegram import get_user_name_from_tg_id, send_message
from app.databases import db
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.donation import service as donation_service


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
    tg_id = int(text[1])
    donation = float(text[2])
    add_credits = len(text) == 3
    info = db.get_stats_by_tg_id(tg_id)
    if not info:
        await send_message(
            chat_id=chat_id, text=f"错误：用户 {tg_id} 不存在，请确认", context=context
        )
        return
    _donation = info[1]
    donate = _donation + donation
    res = db.update_user_donation(donate, tg_id=tg_id)
    if not res:
        await send_message(
            chat_id=chat_id, text="错误：更新捐赠金额失败，请检查", context=context
        )
        return
    if add_credits:
        try:
            credits_service.add(
                CreditAccount.tg(int(tg_id)),
                donation * donation_service.get_donation_multiplier(),
            )
        except Exception:
            await send_message(
                chat_id=chat_id, text="错误：更新积分失败，请检查", context=context
            )
            return
        # 通知该用户
        await send_message(
            chat_id=tg_id,
            text=f"通知：感谢您的捐赠，已为您增加积分 {donation * 2}",
            context=context,
        )

    await send_message(
        chat_id=chat_id,
        text=f"信息：成功为 {get_user_name_from_tg_id(tg_id)} 设置捐赠金额 {donation}",
        context=context,
    )


set_donation_handler = CommandHandler("set_donation", set_donation)
