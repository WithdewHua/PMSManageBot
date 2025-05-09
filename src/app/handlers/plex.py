from time import time

from app.config import settings
from app.db import DB
from app.log import logger
from app.plex import Plex
from app.tautulli import Tautulli
from app.utils import (
    caculate_credits_fund,
    get_user_name_from_tg_id,
    get_user_total_duration,
    send_message,
)
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes


# 绑定账户
async def bind_plex(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text
    text = text.split()
    if len(text) != 2:
        await send_message(
            chat_id=chat_id, text="错误：请按照格式填写", context=context
        )
        return
    email = text[1]
    _db = DB()
    _info = _db.get_plex_info_by_tg_id(chat_id)
    if _info:
        _db.close()
        await send_message(
            chat_id=chat_id,
            text="信息：已绑定 Plex 账户，请勿重复操作",
            context=context,
        )
        return

    _plex = Plex()
    plex_id = _plex.get_user_id_by_email(email)
    # 用户不存在
    if plex_id == 0:
        _db.close()
        await send_message(
            chat_id=chat_id,
            text="错误：该用户不是 @WithdewHua 好友，请检查输入的邮箱",
            context=context,
        )
        return
    # 检查数据库中是否存在该 plex_id，如存在直接更新 tg_id
    plex_info = _db.get_plex_info_by_plex_id(plex_id)

    if plex_info:
        tg_id = plex_info[1]
        if tg_id:
            _db.close()
            await send_message(
                chat_id=chat_id, text="错误：该 Plex 账户已经绑定 TG", context=context
            )
            return
        rslt = _db.update_user_tg_id(chat_id, plex_id=plex_id)
        if not rslt:
            _db.close()
            await send_message(
                chat_id=chat_id,
                text="错误：数据库错误，请联系管理员 @WithdewHua",
                context=context,
            )
            return
        # plex 用户表中的积分信息
        plex_credits = plex_info[2]
        # 清空 plex 用户表中积分信息
        _db.update_user_credits(0, plex_id=plex_info[0])
    else:
        plex_username = _plex.get_username_by_user_id(plex_id)
        plex_cur_libs = _plex.get_user_shared_libs_by_id(plex_id)
        plex_all_lib = (
            1 if not set(_plex.get_libraries()).difference(set(plex_cur_libs)) else 0
        )
        # 初始化积分
        try:
            user_total_duration = get_user_total_duration(
                Tautulli().get_home_stats(
                    1365, "duration", len(_plex.users_by_id), stat_id="top_users"
                )
            )
        except Exception as e:
            _db.close()
            logger.error("Error: ", e)
            await send_message(
                chat_id=chat_id,
                text="错误：获取用户观看时长失败，请联系管理员 @WithdewHua",
                context=context,
            )
            return
        plex_credits = user_total_duration.get(plex_id, 0)
        # 写入数据库
        rslt = _db.add_plex_user(
            plex_id=plex_id,
            tg_id=chat_id,
            plex_email=email,
            plex_username=plex_username,
            credits=0,
            all_lib=plex_all_lib,
            watched_time=plex_credits,
        )

        if not rslt:
            _db.close()
            await send_message(
                chat_id=chat_id,
                text="错误：数据库错误，请联系管理员 @WithdewHua",
                context=context,
            )
            return
    # 获取用户数据表信息
    stats_info = _db.get_stats_by_tg_id(chat_id)
    # 更新用户数据表
    if stats_info:
        tg_user_credits = stats_info[2] + plex_credits
        _db.update_user_credits(tg_user_credits, tg_id=chat_id)
    else:
        _db.add_user_data(chat_id, credits=plex_credits)

    _db.close()
    await send_message(
        chat_id=chat_id,
        text=f"信息： 绑定 Plex 用户 {plex_id} 成功，请加入群组 {settings.TG_GROUP} 并仔细阅读群置顶",
        context=context,
    )


# 用户兑换邀请码
async def redeem_plex(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    text = update.message.text
    text_parts = text.split()
    if len(text_parts) != 3:
        await send_message(
            chat_id=chat_id, text="错误：请按照格式填写", context=context
        )
        return
    if not settings.PLEX_REGISTER:
        await send_message(chat_id=chat_id, text="错误：Plex 暂停注册", context=context)
        return
    plex_email = text_parts[1]
    if "@" not in plex_email:
        await send_message(
            chat_id=chat_id, text="错误: 请输入正确的邮箱", context=context
        )
        return
    code = text_parts[2]
    _db = DB()
    res = _db.verify_invitation_code_is_used(code)
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
    owner = res[1]
    _plex = Plex()
    # 检查该用户是否已经被邀请
    if plex_email in _plex.users_by_email:
        await send_message(
            chat_id=chat_id, text="错误：该用户已被邀请", context=context
        )
        _db.close()
        return
    # 发送邀请
    if not _plex.invite_friend(plex_email):
        await send_message(
            chat_id=chat_id, text="错误: 邀请失败，请联系管理员", context=context
        )
        _db.close()
        return
    # 更新邀请码状态
    res = _db.update_invitation_status(code=code, used_by=plex_email)
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
        text=f"信息：兑换邀请码成功，请登录 Plex 确认邀请，"
        f"确认邀请后, 可使用 `/bind_plex {plex_email}` 绑定机器人获取更多功能, "
        f"更多帮助请加入群组 {settings.TG_GROUP}",
        context=context,
    )
    for admin in settings.ADMIN_CHAT_ID:
        await send_message(
            chat_id=admin,
            text=f"信息：{get_user_name_from_tg_id(owner)} 成功邀请 {plex_email}",
            context=context,
        )


# 解锁 nsfw 库权限
async def unlock_nsfw_plex(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    _info = _db.get_plex_info_by_tg_id(chat_id)
    if not _info:
        await send_message(
            chat_id=chat_id, text="错误: 未查询到用户, 请先绑定", context=context
        )
        _db.close()
        return
    # 用户数据
    _stats_info = _db.get_stats_by_tg_id(chat_id)
    _plex_id = _info[0]
    _credits = _stats_info[2]
    _all_lib = _info[5]
    if _all_lib == 1:
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
    _plex = Plex()
    # 更新权限
    try:
        _plex.update_user_shared_libs(_plex_id, _plex.get_libraries())
    except Exception:
        await send_message(
            chat_id=chat_id, text="错误: 更新权限失败, 请联系管理员", context=context
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
    res = _db.update_all_lib_flag(all_lib=1, unlock_time=unlock_time, plex_id=_plex_id)
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


# 锁定 NSFW 权限
async def lock_nsfw_plex(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    _info = _db.get_plex_info_by_tg_id(chat_id)
    if not _info:
        await send_message(
            chat_id=chat_id, text="错误: 未查询到用户, 请先绑定", context=context
        )
        _db.close()
        return
    _stats_info = _db.get_stats_by_tg_id(chat_id)
    _plex_id = _info[0]
    _credits = _stats_info[2]
    _all_lib = _info[5]
    _unlock_time = _info[6]
    if _all_lib == 0:
        _db.close()
        await send_message(
            chat_id=chat_id, text="错误: 您未解锁 NSFW 内容", context=context
        )
        return
    _credits_fund = caculate_credits_fund(_unlock_time, settings.UNLOCK_CREDITS)
    _credits += _credits_fund
    _plex = Plex()
    # 更新权限
    sections = _plex.get_libraries()
    for section in settings.NSFW_LIBS:
        sections.remove(section)
    try:
        _plex.update_user_shared_libs(_plex_id, sections)
    except Exception:
        await send_message(
            chat_id=chat_id, text="错误: 更新权限失败, 请联系管理员", context=context
        )
        _db.close()
        return
    # 更新数据库
    res = _db.update_user_credits(_credits, tg_id=chat_id)
    if not res:
        _db.close()
        await send_message(
            chat_id=chat_id,
            text="错误: 数据库更新失败, 请联系管理员",
            context=context,
        )
        return
    res = _db.update_all_lib_flag(all_lib=0, unlock_time=None, plex_id=_plex_id)
    if not res:
        _db.close()
        await send_message(
            chat_id=chat_id,
            text="错误: 数据库更新失败, 请联系管理员",
            context=context,
        )
        return
    _db.close()
    await send_message(
        chat_id=chat_id,
        text=f"信息: 成功关闭 NSFW 内容, 退回积分 {_credits_fund}",
        context=context,
    )


bind_plex_handler = CommandHandler("bind_plex", bind_plex)
unlock_nsfw_plex_handler = CommandHandler("unlock_nsfw_plex", unlock_nsfw_plex)
lock_nsfw_plex_handler = CommandHandler("lock_nsfw_plex", lock_nsfw_plex)
redeem_plex_handler = CommandHandler("redeem_plex", redeem_plex)

__all__ = [
    "bind_plex_handler",
    "unlock_nsfw_plex_handler",
    "lock_nsfw_plex_handler",
    "redeem_plex_handler",
]
