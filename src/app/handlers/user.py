from time import time
from uuid import NAMESPACE_URL, uuid3

from app.config import settings
from app.db import DB
from app.log import logger
from app.overseerr import Overseerr
from app.utils import get_user_name_from_tg_id, send_message
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes


# 生成邀请码
async def exchange(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    _info = _db.get_stats_by_tg_id(chat_id)
    if not _info:
        _db.close()
        await send_message(
            chat_id=chat_id, text="错误：未绑定 Plex/Emby，请先绑定", context=context
        )
        return
    _credits = _info[2]
    # 检查剩余积分
    if _credits < settings.INVITATION_CREDITS:
        _db.close()
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
    res = _db.add_invitation_code(code=_code, owner=chat_id)
    if not res:
        _db.close()
        await send_message(
            chat_id=chat_id, text="错误: 更新邀请码失败, 请联系管理员", context=context
        )
        return
    # > 再更新积分情况
    res = _db.update_user_credits(_credits, tg_id=chat_id)
    if not res:
        _db.close()
        await send_message(
            chat_id=chat_id, text="错误: 更新积分失败, 请联系管理员", context=context
        )
        return
    _db.close()
    await send_message(
        chat_id=chat_id,
        text="""信息: 生成邀请码成功，邀请码为 `{}`""".format(_code),
        parse_mode="markdown",
        context=context,
    )


# 查看个人信息
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    _plex_info = _db.get_plex_info_by_tg_id(chat_id)
    _emby_info = _db.get_emby_info_by_tg_id(chat_id)
    _stats_info = _db.get_stats_by_tg_id(chat_id)
    _codes = _db.get_invitation_code_by_owner(chat_id)
    _db.close()
    if _plex_info is None and _emby_info is None:
        await send_message(
            chat_id=chat_id,
            text="错误：Plex/Emby 均未绑定，请先绑定任一",
            context=context,
        )
        return
    _credits, _donation = _stats_info[2], _stats_info[1]
    _codes = "" if not _codes else "\n".join(_codes)
    body_text = f"""
{"=" * 44}
<strong>可用积分: </strong>{_credits:.2f}
<strong>捐赠金额: </strong>{_donation}
<strong>可用邀请码：</strong>
{_codes}
{"=" * 44}

"""
    if _plex_info:
        body_text += f"""
{"=" * 20} Plex {"=" * 20}
<strong>Plex 用户名：</strong>{_plex_info[4]}
<strong>总观看时长：</strong>{_plex_info[7]:.2f}h
<strong>当前权限：</strong>{"全部" if _plex_info[5] == 1 else "部分"}

"""
    if _emby_info:
        body_text += f"""
{"=" * 20} Emby {"=" * 20}
<strong>Emby 用户名: </strong>{_emby_info[0]}
<strong>总观看时长：</strong>{_emby_info[5]:.2f}h
<strong>当前权限：</strong>{"全部" if _emby_info[3] == 1 else "部分"}
<strong>当前线路：</strong>{_emby_info[7]}
"""
    await send_message(
        chat_id=chat_id, text=body_text, parse_mode="HTML", context=context
    )


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
    db = DB()
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
            raise
        if plex_info:
            await send_message(
                chat_id=chat_id,
                text="错误：您已绑定 Plex 账户，请使用 Plex 帐号登录 Overseer",
                context=context,
            )
            raise
        if overseerr_info:
            await send_message(
                chat_id=chat_id,
                text="错误：您已创建过 Overseerr 账户，请勿重复创建",
                context=context,
            )
            raise
        if overseerr_info_by_email:
            await send_message(
                chat_id=chat_id,
                text="错误：已存在该邮箱创建的 Overseerr 账户，请勿重复创建",
                context=context,
            )
            raise
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
            raise
        # 保存至数据库
        rslt = db.add_overseerr_user(user_id=msg, user_email=email, tg_id=chat_id)
        if not rslt:
            await send_message(
                chat_id=chat_id,
                text="错误：数据库操作失败，请联系管理员",
                context=context,
            )
            raise
    except Exception as e:
        logger.error(e)
    finally:
        db.close()


# 管理员命令: 设置捐赠信息
async def set_donation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    if chat_id not in settings.ADMIN_CHAT_ID:
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
    add_credits = True if len(text) == 3 else False
    _db = DB()
    info = _db.get_stats_by_tg_id(tg_id)
    if not info:
        await send_message(
            chat_id=chat_id, text=f"错误：用户 {tg_id} 不存在，请确认", context=context
        )
        _db.close()
        return
    _credits = info[2]
    _donation = info[1]
    credits = _credits + donation * settings.DONATION_MULTIPLIER
    donate = _donation + donation
    res = _db.update_user_donation(donate, tg_id=tg_id)
    if not res:
        _db.close()
        await send_message(
            chat_id=chat_id, text="错误：更新捐赠金额失败，请检查", context=context
        )
        return
    if add_credits:
        res = _db.update_user_credits(credits, tg_id=tg_id)
        if not res:
            _db.close()
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

    _db.close()

    await send_message(
        chat_id=chat_id,
        text=f"信息：成功为 {get_user_name_from_tg_id(tg_id)} 设置捐赠金额 {donation}",
        context=context,
    )


info_handler = CommandHandler("info", info)
set_donation_handler = CommandHandler("set_donation", set_donation)
exchange_handler = CommandHandler("exchange", exchange)
create_overseerr_handler = CommandHandler("create_overseerr", create_overseerr)

__all__ = [
    "info_handler",
    "set_donation_handler",
    "exchange_handler",
    "create_overseerr_handler",
]
