from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.domains.reports import service as reports_service


async def get_server_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_plex_user_num, current_emby_user_num = (
        reports_service.get_current_playing_users()
    )
    body_text = f"""
======================
<strong>当前观看人数</strong>
- <strong>Plex</strong>: {current_plex_user_num}
- <strong>Emby</strong>: {current_emby_user_num}
======================
        """

    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=body_text, parse_mode="HTML"
    )


get_server_status_handler = CommandHandler("server_status", get_server_status)

__all__ = ["get_server_status_handler"]
