from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.core.config import settings
from app.domains.accounts import service as accounts_service
from app.integrations.telegram.messaging import send_message


async def get_register_status(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    chat_id = update._effective_chat.id
    config = accounts_service.get_registration_config()
    text = f"""
    Plex: {"可注册" if config.plex_register else "注册关闭"}
    Emby: {"可注册" if config.emby_register else "注册关闭"}
    """
    await send_message(chat_id=chat_id, text=text, parse_mode="HTML", context=context)


async def set_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    if chat_id not in settings.TG_ADMIN_CHAT_ID:
        await send_message(chat_id=chat_id, text="错误：越权操作", context=context)
        return
    parts = update.message.text.split()
    if len(parts) != 3:
        await send_message(
            chat_id=chat_id, text="错误：请按照格式填写", context=context
        )
        return
    server, flag = parts[1:]
    if server.lower() not in {"plex", "emby"}:
        await send_message(
            chat_id=chat_id, text="错误: 请指定正确的媒体服务器", context=context
        )
        return
    accounts_service.set_registration_enabled(server, flag != "0")
    await send_message(
        chat_id=chat_id,
        text=f"信息: 设置 {server} 注册状态为 {'开启' if flag != '0' else '关闭'}",
        context=context,
    )


get_register_status_handler = CommandHandler("register_status", get_register_status)
set_register_handler = CommandHandler("set_register", set_register)


async def create_overseerr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    parts = update.message.text.split()
    if len(parts) != 3:
        await send_message(
            chat_id=chat_id, text="错误: 请按照格式填写", context=context
        )
        return
    email, password = parts[1:]
    if len(password) < 8:
        await send_message(
            chat_id=chat_id, text="错误：密码长度至少为 8", context=context
        )
        return

    try:
        success, result = accounts_service.create_overseerr(chat_id, email, password)
        if not success:
            await send_message(chat_id=chat_id, text=f"错误：{result}", context=context)
    except Exception:
        await send_message(
            chat_id=chat_id, text="错误：创建账户失败，请联系管理员", context=context
        )


create_overseerr_handler = CommandHandler("create_overseerr", create_overseerr)
