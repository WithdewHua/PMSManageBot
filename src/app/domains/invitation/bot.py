from time import time
from uuid import NAMESPACE_URL, uuid3

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.core.config import settings
from app.core.telegram import send_message
from app.databases import db


# 生成邀请码
async def exchange(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _info = db.get_stats_by_tg_id(chat_id)
    if not _info:
        await send_message(
            chat_id=chat_id, text="错误：未绑定 Plex/Emby，请先绑定", context=context
        )
        return
    _credits = _info[2]
    # 检查剩余积分
    if _credits < settings.INVITATION_CREDITS:
        await send_message(
            chat_id=chat_id, text="错误：您的积分不足，无法兑换邀请码", context=context
        )
        return
    # 减去积分
    _credits -= settings.INVITATION_CREDITS
    # 生成邀请码
    _code = uuid3(NAMESPACE_URL, str(chat_id + time())).hex
    # 更新数据库
    # > 先更新邀请码
    res = db.add_invitation_code(code=_code, owner=chat_id)
    if not res:
        await send_message(
            chat_id=chat_id, text="错误: 更新邀请码失败, 请联系管理员", context=context
        )
        return
    # > 再更新积分情况
    res = db.update_user_credits(_credits, tg_id=chat_id)
    if not res:
        await send_message(
            chat_id=chat_id, text="错误: 更新积分失败, 请联系管理员", context=context
        )
        return
    await send_message(
        chat_id=chat_id,
        text=f"""信息: 生成邀请码成功，邀请码为 `{_code}`""",
        parse_mode="markdown",
        context=context,
    )


exchange_handler = CommandHandler("exchange", exchange)
