from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.domains.invitation import service as invitation_service
from app.domains.invitation.exceptions import (
    InvitationAccountNotFound,
    InvitationError,
)
from app.integrations.telegram.messaging import send_message


async def exchange(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    try:
        code = invitation_service.generate_one_code(chat_id)
    except InvitationAccountNotFound:
        await send_message(
            chat_id=chat_id,
            text="错误：未绑定 Plex/Emby，请先绑定",
            context=context,
        )
        return
    except InvitationError:
        await send_message(
            chat_id=chat_id,
            text="错误：您的积分不足，无法兑换邀请码",
            context=context,
        )
        return
    except Exception:
        await send_message(
            chat_id=chat_id, text="错误: 更新邀请码失败, 请联系管理员", context=context
        )
        return
    await send_message(
        chat_id=chat_id,
        text=f"信息: 生成邀请码成功，邀请码为 `{code}`",
        parse_mode="markdown",
        context=context,
    )


exchange_handler = CommandHandler("exchange", exchange)
