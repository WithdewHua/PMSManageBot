from time import time

from app.cache import emby_user_defined_line_cache
from app.config import settings
from app.db import DB
from app.emby import Emby
from app.utils import (
    caculate_credits_fund,
    get_user_name_from_tg_id,
    send_message,
)
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes


async def bind_emby(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text
    text = text.split()
    if len(text) != 2:
        await send_message(
            chat_id=chat_id, text="错误：请按照格式填写", context=context
        )
        return
    emby_username = text[1]
    db = DB()
    info = db.get_emby_info_by_tg_id(chat_id)
    if info:
        db.close()
        await send_message(
            chat_id=chat_id,
            text="信息: 已绑定 Emby 账户, 请勿重复操作",
            context=context,
        )
        return
    emby = Emby()
    # 检查 emby 用户是否存在
    uid = emby.get_uid_from_username(emby_username)
    if not uid:
        db.close()
        await send_message(
            chat_id=chat_id, text=f"错误: {emby_username} 不存在", context=context
        )
        return
    emby_info = db.get_emby_info_by_emby_username(emby_username)
    # 更新 emby 用户表
    # todo: 更新观看时间等信息
    if emby_info:
        if emby_info[2]:
            db.close()
            await send_message(
                chat_id=chat_id, text="错误：该 Emby 账户已经绑定 TG", context=context
            )
            return
        emby_credits = emby_info[6]
        # 更新 tg id
        db.update_user_tg_id(chat_id, emby_id=uid)
        # 清空 emby 用户表中的积分信息
        db.update_user_credits(0, emby_id=uid)
    else:
        emby_credits = 0
        db.add_emby_user(emby_username, emby_id=uid, tg_id=chat_id)
    # 更新用户数据表
    stats_info = db.get_stats_by_tg_id(chat_id)
    if stats_info:
        tg_user_credits = stats_info[2] + emby_credits
        db.update_user_credits(tg_user_credits, tg_id=chat_id)
    else:
        db.add_user_data(chat_id, credits=emby_credits)

    db.close()
    await send_message(
        chat_id=chat_id,
        text=f"信息： 绑定 Emby 用户 {emby_username} 成功，请加入群组 {settings.TG_GROUP} 并仔细阅读群置顶",
        context=context,
    )


async def redeem_emby(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    text = update.message.text
    text_parts = text.split()
    if len(text_parts) != 3:
        await send_message(
            chat_id=chat_id, text="错误: 请按照格式填写", context=context
        )
        return
    if not settings.EMBY_REGISTER:
        await send_message(chat_id=chat_id, text="错误：Emby 暂停注册", context=context)
        return
    emby_username, redeem_code = text_parts[1:]
    _db = DB()
    # 检查邀请码有效性
    res = _db.verify_invitation_code_is_used(redeem_code)
    if not res:
        await send_message(
            chat_id=chat_id, text="错误：您输入的邀请码无效", context=context
        )
        _db.close()
        return
    if res[0]:
        await send_message(
            chat_id=chat_id, text="错误：您输入的邀请码已被使用", context=context
        )
        _db.close()
        return
    code_owner = res[1]
    # 检查该用户是否存在
    if _db.get_emby_info_by_emby_username(emby_username):
        await send_message(chat_id=chat_id, text="错误: 该用户已存在", context=context)
        _db.close()
        return
    # 创建用户
    emby = Emby()
    flag, msg = emby.add_user(username=emby_username)
    if flag:
        # 更新数据库
        _db.add_emby_user(emby_username, emby_id=msg)
    else:
        await send_message(
            chat_id=chat_id, text=f"错误: {msg}, 请联系 @WithdewHua", context=context
        )
        _db.close()
        return
    # 创建成功,更新邀请码状态
    res = _db.update_invitation_status(code=redeem_code, used_by=emby_username)
    if not res:
        await send_message(
            chat_id=chat_id,
            text="错误：更新邀请码状态失败，请联系管理员",
            context=context,
        )
        _db.close()
        return
    _db.close()
    await send_message(
        chat_id=chat_id,
        text=f"信息：兑换邀请码成功，用户名为 `{emby_username}`, 密码为空, 请及时登录 Emby 修改密码，"
        f"可使用 `/bind_emby {emby_username}`绑定机器人获取更多功能, 更多帮助请加入群组 {settings.TG_GROUP}",
        context=context,
    )
    for admin in settings.ADMIN_CHAT_ID:
        await send_message(
            chat_id=admin,
            text=f"信息：{get_user_name_from_tg_id(code_owner)} 成功邀请 {emby_username}",
            context=context,
        )


# 解锁 emby nsfw 库权限
async def unlock_nsfw_emby(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    _info = _db.get_emby_info_by_tg_id(chat_id)
    if not _info:
        await send_message(
            chat_id=chat_id, text="错误: 未查询到用户, 请先绑定", context=context
        )
        _db.close()
        return
    # 用户数据
    _stats_info = _db.get_stats_by_tg_id(chat_id)
    _emby_id = _info[1]
    _credits = _stats_info[2]
    _is_unlock = _info[3]
    if _is_unlock == 1:
        _db.close()
        await send_message(
            chat_id=chat_id, text="错误: 您已拥有全部库权限, 无需解锁", context=context
        )
        return
    if _credits < settings.UNLOCK_CREDITS:
        await send_message(
            chat_id=chat_id, text="错误: 您的积分不足, 解锁失败", context=context
        )
        _db.close()
        return
    _credits -= settings.UNLOCK_CREDITS
    _emby = Emby()
    # 更新权限
    flag, msg = _emby.add_user_library(user_id=_emby_id)
    if not flag:
        await send_message(
            chat_id=chat_id,
            text=f"错误: 更新权限失败 ({msg}), 请联系管理员",
            context=context,
        )
        _db.close()
        return
    # 解锁权限的时间
    unlock_time = time()
    # 更新数据库
    res = _db.update_user_credits(_credits, tg_id=chat_id)
    if not res:
        _db.close()
        await send_message(
            chat_id=chat_id, text="错误: 数据库更新失败, 请联系管理员", context=context
        )
        return
    res = _db.update_all_lib_flag(
        all_lib=1, unlock_time=unlock_time, tg_id=chat_id, media_server="emby"
    )
    if not res:
        _db.close()
        await send_message(
            chat_id=chat_id, text="错误: 数据库更新失败, 请联系管理员", context=context
        )
        return
    _db.close()
    await send_message(
        chat_id=chat_id, text="信息: 解锁成功, 请尽情享受", context=context
    )


# 锁定 emby NSFW 权限
async def lock_nsfw_emby(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    _info = _db.get_emby_info_by_tg_id(chat_id)
    if not _info:
        await send_message(
            chat_id=chat_id, text="错误: 未查询到用户, 请先绑定", context=context
        )
        _db.close()
        return
    _stats_info = _db.get_stats_by_tg_id(chat_id)
    _emby_id = _info[1]
    _credits = _stats_info[2]
    _is_unlock = _info[3]
    _unlock_time = _info[4]
    if _is_unlock == 0:
        _db.close()
        await send_message(
            chat_id=chat_id, text="错误: 您未解锁 NSFW 内容", context=context
        )
        return
    _credits_fund = caculate_credits_fund(_unlock_time, settings.UNLOCK_CREDITS)
    _credits += _credits_fund
    _emby = Emby()
    # 更新权限
    flag, msg = _emby.remove_user_library(user_id=_emby_id)
    if not flag:
        await send_message(
            chat_id=chat_id,
            text=f"错误: 更新权限失败 ({msg}), 请联系管理员",
            context=context,
        )
        _db.close()
        return
    # 更新数据库
    res = _db.update_user_credits(_credits, tg_id=chat_id)
    if not res:
        _db.close()
        await send_message(
            chat_id=chat_id, text="错误: 数据库更新失败, 请联系管理员", context=context
        )
        return
    res = _db.update_all_lib_flag(
        all_lib=0, unlock_time=None, tg_id=chat_id, media_server="emby"
    )
    if not res:
        _db.close()
        await send_message(
            chat_id=chat_id, text="错误: 数据库更新失败, 请联系管理员", context=context
        )
        return
    _db.close()
    await send_message(
        chat_id=chat_id,
        text=f"信息: 成功关闭 NSFW 内容, 退回积分 {_credits_fund}",
        context=context,
    )


async def bind_emby_line(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text
    text = text.split()
    if len(text) not in [2, 3]:
        await send_message(
            chat_id=chat_id, text="错误：请按照格式填写", context=context
        )
        return
    db = DB()
    if len(text) == 2:
        line = text[1]
        info = db.get_emby_info_by_tg_id(chat_id)
        # 未绑定 tg
        if not info:
            db.close()
            await send_message(
                chat_id=chat_id,
                text="错误: 未绑定 emby 账户，请先绑定",
                context=context,
            )
            return
        emby_id = info[1]
    if len(text) == 3:
        emby_id, line = text[1:]
        info = db.get_emby_info_by_emby_id(emby_id)
        if not info:
            db.close()
            await send_message(
                chat_id=chat_id,
                text="错误: 未查询到用户, 请检查 emby id",
                context=context,
            )
            return

    emby_username = info[0]
    emby_line = info[7]
    if emby_line == line:
        db.close()
        await send_message(
            chat_id=chat_id,
            text=f"信息: {emby_username} 已绑定 {emby_line}, 无需重复绑定",
            context=context,
        )
        return
    # 更新数据库
    emby_user_defined_line_cache.put(str(emby_username).lower(), line)
    res = db.set_emby_line(line, emby_id=emby_id)
    if not res:
        db.close()
        await send_message(
            chat_id=chat_id, text="错误: 数据库更新失败, 请联系管理员", context=context
        )
        return

    db.close()
    await send_message(
        chat_id=chat_id,
        text=f"信息: {emby_username} 绑定 Emby 线路 {line} 成功",
        context=context,
    )


async def unbind_emby_line(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text
    text = text.split()
    if len(text) not in [1, 2]:
        await send_message(
            chat_id=chat_id, text="错误：请按照格式填写", context=context
        )
        return
    db = DB()
    if len(text) == 1:
        info = db.get_emby_info_by_tg_id(chat_id)
        if not info:
            db.close()
            await send_message(
                chat_id=chat_id,
                text="错误: 未绑定 emby 账户，请先绑定",
                context=context,
            )
            return
        emby_id = info[1]
    if len(text) == 2:
        emby_id = text[1]
        info = db.get_emby_info_by_emby_id(emby_id)
        if not info:
            db.close()
            await send_message(
                chat_id=chat_id,
                text="错误: 未查询到用户, 请检查 emby id",
                context=context,
            )
            return
    emby_username = info[0]
    emby_line = info[7]
    if not emby_line:
        db.close()
        await send_message(
            chat_id=chat_id,
            text=f"错误: {emby_username} 未绑定 emby 线路，无需解绑",
            context=context,
        )
        return
    # 更新数据库
    emby_user_defined_line_cache.delete(str(emby_username).lower())
    res = db.set_emby_line(line=None, emby_id=emby_id)
    if not res:
        db.close()
        await send_message(
            chat_id=chat_id, text="错误: 数据库更新失败, 请联系管理员", context=context
        )
        return
    db.close()
    await send_message(
        chat_id=chat_id,
        text=f"信息: {emby_username} 解绑 Emby 线路 {emby_line} 成功",
        context=context,
    )


bind_emby_handler = CommandHandler("bind_emby", bind_emby)
redeem_emby_handler = CommandHandler("redeem_emby", redeem_emby)
unlock_nsfw_emby_handler = CommandHandler("unlock_nsfw_emby", unlock_nsfw_emby)
lock_nsfw_emby_handler = CommandHandler("lock_nsfw_emby", lock_nsfw_emby)
bind_emby_line_handler = CommandHandler("bind_emby_line", bind_emby_line)
unbind_emby_line_handler = CommandHandler("unbind_emby_line", unbind_emby_line)

__all__ = [
    "bind_emby_handler",
    "redeem_emby_handler",
    "unlock_nsfw_emby_handler",
    "lock_nsfw_emby_handler",
    "bind_emby_line_handler",
    "unbind_emby_line_handler",
]
