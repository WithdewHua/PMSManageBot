from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.core.config import settings
from app.core.telegram import send_message


async def get_register_status(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    chat_id = update._effective_chat.id
    text = f"""
Plex: {"可注册" if settings.PLEX_REGISTER else "注册关闭"}
Emby: {"可注册" if settings.EMBY_REGISTER else "注册关闭"}
    """
    await send_message(chat_id=chat_id, text=text, parse_mode="HTML", context=context)


async def set_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    if chat_id not in settings.TG_ADMIN_CHAT_ID:
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
        settings.PLEX_REGISTER = flag != "0"
    elif server.lower() == "emby":
        settings.EMBY_REGISTER = flag != "0"
    await send_message(
        chat_id=chat_id,
        text=f"信息: 设置 {server} 注册状态为 {'开启' if flag != '0' else '关闭'}",
        context=context,
    )


get_register_status_handler = CommandHandler("register_status", get_register_status)

set_register_handler = CommandHandler("set_register", set_register)


from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.core.log import logger
from app.databases import db
from app.integrations.overseerr import Overseerr


# 创建 overseerr 用户
async def create_overseerr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    text = update.message.text
    text_parts = text.split()
    if len(text_parts) != 3:
        await send_message(
            chat_id=chat_id, text="错误: 请按照格式填写", context=context
        )
        return
    email, password = text_parts[1:]
    if len(password) < 8:
        await send_message(
            chat_id=chat_id, text="错误：密码长度至少为 8", context=context
        )
        return

    try:
        # 检查是否绑定了 Emby
        emby_info = db.get_emby_info_by_tg_id(tg_id=chat_id)
        plex_info = db.get_plex_info_by_tg_id(tg_id=chat_id)
        overseerr_info = db.get_overseerr_info_by_tg_id(tg_id=chat_id)
        overseerr_info_by_email = db.get_overseerr_info_by_email(email=email)
        if not emby_info:
            await send_message(
                chat_id=chat_id,
                text="错误: 未绑定 Emby 帐号，不允许创建 Overseer 账户",
                context=context,
            )
            return
        if plex_info:
            await send_message(
                chat_id=chat_id,
                text="错误：您已绑定 Plex 账户，请使用 Plex 帐号登录 Overseer",
                context=context,
            )
            return
        if overseerr_info:
            await send_message(
                chat_id=chat_id,
                text="错误：您已创建过 Overseerr 账户，请勿重复创建",
                context=context,
            )
            return
        if overseerr_info_by_email:
            await send_message(
                chat_id=chat_id,
                text="错误：已存在该邮箱创建的 Overseerr 账户，请勿重复创建",
                context=context,
            )
            return
        # 创建账户
        _overseerr = Overseerr()
        flag, msg = _overseerr.add_user(email, password)
        if not flag:
            logger.error(f"Failed to create overseerr user: {msg}")
            await send_message(
                chat_id=chat_id,
                text="错误：创建账户失败，请联系管理员",
                context=context,
            )
            return
        # 保存至数据库
        rslt = db.add_overseerr_user(user_id=msg, user_email=email, tg_id=chat_id)
        if not rslt:
            await send_message(
                chat_id=chat_id,
                text="错误：数据库操作失败，请联系管理员",
                context=context,
            )
            return
    except Exception as e:
        logger.error(e)


create_overseerr_handler = CommandHandler("create_overseerr", create_overseerr)
