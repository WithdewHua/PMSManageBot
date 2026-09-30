from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.domains.profile import service
from app.integrations.telegram import messaging


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    body = service.get_info_message(chat_id)
    if body is None:
        await messaging.send_message(
            chat_id=chat_id,
            text="错误：Plex/Emby 均未绑定，请先绑定任一",
            context=context,
        )
        return
    await messaging.send_message(
        chat_id=chat_id, text=body, parse_mode="HTML", context=context
    )


info_handler = CommandHandler("info", info)
