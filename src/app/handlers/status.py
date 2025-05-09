from app.config import settings
from app.utils import send_message
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes


# 获取当前注册状态
async def get_register_status(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    chat_id = update._effective_chat.id
    text = f"""
Plex: {"可注册" if settings.PLEX_REGISTER else "注册关闭"}
Emby: {"可注册" if settings.EMBY_REGISTER else "注册关闭"}
    """
    await send_message(chat_id=chat_id, text=text, parse_mode="HTML", context=context)


# 管理员命令: 设置注册状态
async def set_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    if chat_id not in settings.ADMIN_CHAT_ID:
        await send_message(chat_id=chat_id, text="错误：越权操作", context=context)
        return
    text = update.message.text
    text = text.split()
    if len(text) != 3:
        await send_message(
            chat_id=chat_id, text="错误：请按照格式填写", context=context
        )
        return
    server, flag = text[1:]
    if server.lower() not in {"plex", "emby"}:
        await send_message(
            chat_id=chat_id, text="错误: 请指定正确的媒体服务器", context=context
        )
        return
    if server.lower() == "plex":
        settings.PLEX_REGISTER = True if flag != "0" else False
    elif server.lower() == "emby":
        settings.EMBY_REGISTER = True if flag != "0" else False
    await send_message(
        chat_id=chat_id,
        text=f"信息: 设置 {server} 注册状态为 {'开启' if flag != '0' else '关闭'}",
        context=context,
    )


get_register_status_handler = CommandHandler("register_status", get_register_status)
set_register_handler = CommandHandler("set_register", set_register)

__all__ = ["get_register_status_handler", "set_register_handler"]
