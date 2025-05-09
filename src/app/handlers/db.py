from app.config import (
    settings,
)
from app.update_db import add_all_plex_user
from app.utils import send_message
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes


# 管理员命令：更新数据库
async def update_database(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    if chat_id not in settings.ADMIN_CHAT_ID:
        await send_message(chat_id=chat_id, text="错误：越权操作", context=context)
        return
    try:
        add_all_plex_user()
    except Exception:
        await send_message(
            chat_id=chat_id, text="错误：更新数据库失败，请检查", context=context
        )
        return

    await send_message(chat_id=chat_id, text="信息：更新数据库成功", context=context)


update_database_handler = CommandHandler("update_database", update_database)

__all__ = ["update_database_handler"]
