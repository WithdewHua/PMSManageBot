from time import time

from app.config import settings
from app.db import DB
from app.emby import Emby
from app.utils import (
    caculate_credits_fund,
    get_user_name_from_tg_id,
)
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes


async def bind_emby(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text
    text = text.split()
    if len(text) != 2:
        await context.bot.send_message(chat_id=chat_id, text="错误：请按照格式填写")
        return
    emby_username = text[1]
    db = DB()
    info = db.get_emby_info_by_tg_id(chat_id)
    if info:
        db.close()
        await context.bot.send_message(
            chat_id=chat_id, text="信息: 已绑定 Emby 账户, 请勿重复操作"
        )
        return
    emby = Emby()
    # 检查 emby 用户是否存在
    uid = emby.get_uid_from_username(emby_username)
    if not uid:
        db.close()
        await context.bot.send_message(
            chat_id=chat_id, text=f"错误: {emby_username} 不存在"
        )
        return
    emby_info = db.get_emby_info_by_emby_username(emby_username)
    # 更新 emby 用户表
    # todo: 更新观看时间等信息
    if emby_info:
        if emby_info[2]:
            db.close()
            await context.bot.send_message(
                chat_id=chat_id, text="错误：该 Emby 账户已经绑定 TG"
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
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"信息： 绑定 Emby 用户 {emby_username} 成功，请加入群组 {settings.TG_GROUP} 并仔细阅读群置顶",
    )


async def redeem_emby(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    text = update.message.text
    text_parts = text.split()
    if len(text_parts) != 3:
        await context.bot.send_message(chat_id=chat_id, text="错误: 请按照格式填写")
        return
    if not settings.EMBY_REGISTER:
        await context.bot.send_message(chat_id=chat_id, text="错误：Emby 暂停注册")
    emby_username, redeem_code = text_parts[1:]
    _db = DB()
    # 检查邀请码有效性
    res = _db.verify_invitation_code_is_used(redeem_code)
    if not res:
        await context.bot.send_message(chat_id=chat_id, text="错误：您输入的邀请码无效")
        _db.close()
        return
    if res[0]:
        await context.bot.send_message(
            chat_id=chat_id, text="错误：您输入的邀请码已被使用"
        )
        _db.close()
        return
    code_owner = res[1]
    # 检查该用户是否存在
    if _db.get_emby_info_by_emby_username(emby_username):
        await context.bot.send_message(chat_id=chat_id, text="错误: 该用户已存在")
        _db.close()
        return
    # 创建用户
    emby = Emby()
    flag, msg = emby.add_user(username=emby_username)
    if flag:
        # 更新数据库
        _db.add_emby_user(emby_username, emby_id=msg)
    else:
        await context.bot.send_message(
            chat_id=chat_id, text=f"错误: {msg}, 请联系 @WithdewHua"
        )
        _db.close()
        return
    # 创建成功,更新邀请码状态
    res = _db.update_invitation_status(code=redeem_code, used_by=emby_username)
    if not res:
        await context.bot.send_message(
            chat_id=chat_id, text="错误：更新邀请码状态失败，请联系管理员"
        )
        _db.close()
        return
    _db.close()
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"信息：兑换邀请码成功，用户名为 `{emby_username}`, 密码为空, 请及时登录 Emby 修改密码，"
        f"可使用 `/bind_emby {emby_username}`绑定机器人获取更多功能, 更多帮助请加入群组 {settings.TG_GROUP}",
    )
    for admin in settings.ADMIN_CHAT_ID:
        await context.bot.send_message(
            chat_id=admin,
            text=f"信息：{get_user_name_from_tg_id(code_owner)} 成功邀请 {emby_username}",
        )


# 解锁 emby nsfw 库权限
async def unlock_nsfw_emby(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    _info = _db.get_emby_info_by_tg_id(chat_id)
    if not _info:
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 未查询到用户, 请先绑定"
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
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 您已拥有全部库权限, 无需解锁"
        )
        return
    if _credits < settings.UNLOCK_CREDITS:
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 您的积分不足, 解锁失败"
        )
        _db.close()
        return
    _credits -= settings.UNLOCK_CREDITS
    _emby = Emby()
    # 更新权限
    flag, msg = _emby.add_user_library(user_id=_emby_id)
    if not flag:
        await context.bot.send_message(
            chat_id=chat_id, text=f"错误: 更新权限失败 ({msg}), 请联系管理员"
        )
        _db.close()
        return
    # 解锁权限的时间
    unlock_time = time()
    # 更新数据库
    res = _db.update_user_credits(_credits, tg_id=chat_id)
    if not res:
        _db.close()
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 数据库更新失败, 请联系管理员"
        )
        return
    res = _db.update_all_lib_flag(
        all_lib=1, unlock_time=unlock_time, tg_id=chat_id, media_server="emby"
    )
    if not res:
        _db.close()
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 数据库更新失败, 请联系管理员"
        )
        return
    _db.close()
    await context.bot.send_message(chat_id=chat_id, text="信息: 解锁成功, 请尽情享受")


# 锁定 emby NSFW 权限
async def lock_nsfw_emby(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    _info = _db.get_emby_info_by_tg_id(chat_id)
    if not _info:
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 未查询到用户, 请先绑定"
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
        await context.bot.send_message(chat_id=chat_id, text="错误: 您未解锁 NSFW 内容")
        return
    _credits_fund = caculate_credits_fund(_unlock_time, settings.UNLOCK_CREDITS)
    _credits += _credits_fund
    _emby = Emby()
    # 更新权限
    flag, msg = _emby.remove_user_library(user_id=_emby_id)
    if not flag:
        await context.bot.send_message(
            chat_id=chat_id, text=f"错误: 更新权限失败 ({msg}), 请联系管理员"
        )
        _db.close()
        return
    # 更新数据库
    res = _db.update_user_credits(_credits, tg_id=chat_id)
    if not res:
        _db.close()
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 数据库更新失败, 请联系管理员"
        )
        return
    res = _db.update_all_lib_flag(
        all_lib=0, unlock_time=None, tg_id=chat_id, media_server="emby"
    )
    if not res:
        _db.close()
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 数据库更新失败, 请联系管理员"
        )
        return
    _db.close()
    await context.bot.send_message(
        chat_id=chat_id, text=f"信息: 成功关闭 NSFW 内容, 退回积分 {_credits_fund}"
    )


bind_emby_handler = CommandHandler("bind_emby", bind_emby)
redeem_emby_handler = CommandHandler("redeem_emby", redeem_emby)
unlock_nsfw_emby_handler = CommandHandler("unlock_nsfw_emby", unlock_nsfw_emby)
lock_nsfw_emby_handler = CommandHandler("lock_nsfw_emby", lock_nsfw_emby)

__all__ = [
    bind_emby_handler,
    redeem_emby_handler,
    unlock_nsfw_emby_handler,
    lock_nsfw_emby_handler,
]
