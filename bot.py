import logging
import textwrap
from time import time

from uuid import uuid3, NAMESPACE_URL

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from plex import Plex
from emby import Emby
from overseerr import Overseerr
from db import DB
from tautulli import Tautulli
from settings import (
    TG_API_TOKEN,
    ADMIN_CHAT_ID,
    UNLOCK_CREDITS,
    INVITATION_CREDITS,
    NSFW_LIBS,
    PLEX_REGISTER,
    EMBY_REGISTER,
)
from utils import (
    get_user_total_duration,
    caculate_credits_fund,
    get_user_name_from_tg_id,
)
from update_db import add_all_plex_user


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    body_text = """
    欢迎来到 FunMedia 小助手

    公共命令：
    /info - 查看个人信息
    /exchange - 生成邀请码，消耗 {} 积分
    /credits\_rank - 查看积分榜
    /donation\_rank - 查看捐赠榜
    /play\_duration\_rank - 查看观看时长榜
    /register\_status - 查看 Plex/Emby 是否可注册


    Plex 命令:
    /redeem\_plex - 兑换邀请码，格式为 `/redeem_plex 邮箱 邀请码` (注意空格)
    /bind\_plex - 绑定 Plex 用户，格式为 `/bind_plex 邮箱` (注意空格)
    /unlock\_nsfw\_plex - 解锁 NSFW 相关库权限, 消耗 {} 积分
    /lock\_nsfw\_plex - 关闭 NSFW 权限, 积分返还规则：一天内返还 90%, 7 天内 70%, 一月内 50%，超出一个月 0
    
    Emby 命令:
    /redeem\_emby - 兑换邀请码，格式为 `/redeem_emby 用户名 邀请码` (注意空格)
    /bind\_emby - 绑定 Emby 用户，格式为 `/bind_emby 用户名` (注意空格)
    /unlock\_nsfw\_emby - 解锁 NSFW 相关库权限, 消耗 {} 积分
    /lock\_nsfw\_emby - 关闭 NSFW 权限, 积分返还规则：一天内返还 90%, 7 天内 70%, 一月内 50%，超出一个月 0

    Overseerr 命令:
    /create\_overseerr - 创建 Overseerr 账户，格式为 `/create_overseerr 邮箱 密码` (注意空格)
 
    管理员命令：
    /set\_donation - 设置捐赠金额
    /update\_database - 更新数据库
    /set\_register - 设置可注册状态

    群组：https://t.me/+VCHVfOhRTAxmOGE9
    """.format(INVITATION_CREDITS, UNLOCK_CREDITS, UNLOCK_CREDITS)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=textwrap.dedent(body_text),
        parse_mode="markdown",
    )


# 绑定账户
async def bind_plex(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text
    text = text.split()
    if len(text) != 2:
        await context.bot.send_message(chat_id=chat_id, text="错误：请按照格式填写")
        return
    email = text[1]
    _db = DB()
    _info = _db.get_plex_info_by_tg_id(chat_id)
    if _info:
        _db.close()
        await context.bot.send_message(
            chat_id=chat_id, text="信息：已绑定 Plex 账户，请勿重复操作"
        )
        return

    _plex = Plex()
    plex_id = _plex.get_user_id_by_email(email)
    # 用户不存在
    if plex_id == 0:
        _db.close()
        await context.bot.send_message(
            chat_id=chat_id, text="错误：该用户不是 @WithdewHua 好友，请检查输入的邮箱"
        )
        return
    # 检查数据库中是否存在该 plex_id，如存在直接更新 tg_id
    plex_info = _db.get_plex_info_by_plex_id(plex_id)

    if plex_info:
        tg_id = plex_info[1]
        if tg_id:
            _db.close()
            await context.bot.send_message(
                chat_id=chat_id, text="错误：该 Plex 账户已经绑定 TG"
            )
            return
        rslt = _db.update_user_tg_id(chat_id, plex_id=plex_id)
        if not rslt:
            _db.close()
            await context.bot.send_message(
                chat_id=chat_id, text="错误：数据库错误，请联系管理员 @WithdewHua"
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
            logging.error("Error: ", e)
            await context.bot.send_message(
                chat_id=chat_id,
                text="错误：获取用户观看时长失败，请联系管理员 @WithdewHua",
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
            await context.bot.send_message(
                chat_id=chat_id, text="错误：数据库错误，请联系管理员 @WithdewHua"
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
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"信息： 绑定 Plex 用户 {plex_id} 成功，请加入群组 https://t.me/+VCHVfOhRTAxmOGE9 并仔细阅读群置顶",
    )


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
        text=f"信息： 绑定 Emby 用户 {emby_username} 成功，请加入群组 https://t.me/+VCHVfOhRTAxmOGE9 并仔细阅读群置顶",
    )


# 生成邀请码
async def exchange(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    _info = _db.get_stats_by_tg_id(chat_id)
    if not _info:
        _db.close()
        await context.bot.send_message(
            chat_id=chat_id, text="错误：未绑定 Plex/Emby，请先绑定"
        )
        return
    _credits = _info[2]
    # 检查剩余积分
    if _credits < INVITATION_CREDITS:
        _db.close()
        await context.bot.send_message(
            chat_id=chat_id, text="错误：您的积分不足，无法兑换邀请码"
        )
        return
    # 减去积分
    _credits -= INVITATION_CREDITS
    # 生成邀请码
    _code = uuid3(NAMESPACE_URL, str(chat_id + time())).hex
    # 更新数据库
    # > 先更新邀请码
    res = _db.add_invitation_code(code=_code, owner=chat_id)
    if not res:
        _db.close()
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 更新邀请码失败, 请联系管理员"
        )
        return
    # > 再更新积分情况
    res = _db.update_user_credits(_credits, tg_id=chat_id)
    if not res:
        _db.close()
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 更新积分失败, 请联系管理员"
        )
        return
    _db.close()
    await context.bot.send_message(
        chat_id=chat_id,
        text="""信息: 生成邀请码成功，邀请码为 `{}`""".format(_code),
        parse_mode="markdown",
    )


# 用户兑换邀请码
async def redeem_plex(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    text = update.message.text
    text_parts = text.split()
    if len(text_parts) != 3:
        await context.bot.send_message(chat_id=chat_id, text="错误：请按照格式填写")
        return
    if not PLEX_REGISTER:
        await context.bot.send_message(chat_id=chat_id, text="错误：Plex 暂停注册")
        return
    plex_email = text_parts[1]
    if "@" not in plex_email:
        await context.bot.send_message(chat_id=chat_id, text="错误: 请输入正确的邮箱")
        return
    code = text_parts[2]
    _db = DB()
    res = _db.verify_invitation_code_is_used(code)
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
    owner = res[1]
    _plex = Plex()
    # 检查该用户是否已经被邀请
    if plex_email in _plex.users_by_email:
        await context.bot.send_message(chat_id=chat_id, text="错误：该用户已被邀请")
        _db.close()
        return
    # 发送邀请
    if not _plex.invite_friend(plex_email):
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 邀请失败，请联系管理员"
        )
        _db.close()
        return
    # 更新邀请码状态
    res = _db.update_invitation_status(code=code, used_by=plex_email)
    if not res:
        await context.bot.send_message(
            chat_id=chat_id, text="错误：更新邀请码状态失败，请联系管理员"
        )
        _db.close()
        return
    _db.close()
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"信息：兑换邀请码成功，请登录 Plex 确认邀请，"
        f"确认邀请后, 可使用 `/bind_plex {plex_email}` 绑定机器人获取更多功能, "
        f"更多帮助请加入群组 https://t.me/+VCHVfOhRTAxmOGE9",
    )
    for admin in ADMIN_CHAT_ID:
        await context.bot.send_message(
            chat_id=admin,
            text=f"信息：{get_user_name_from_tg_id(owner)} 成功邀请 {plex_email}",
        )


async def redeem_emby(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    text = update.message.text
    text_parts = text.split()
    if len(text_parts) != 3:
        await context.bot.send_message(chat_id=chat_id, text="错误: 请按照格式填写")
        return
    if not EMBY_REGISTER:
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
        f"可使用 `/bind_emby {emby_username}`绑定机器人获取更多功能, 更多帮助请加入群组 https://t.me/+VCHVfOhRTAxmOGE9",
    )
    for admin in ADMIN_CHAT_ID:
        await context.bot.send_message(
            chat_id=admin,
            text=f"信息：{get_user_name_from_tg_id(code_owner)} 成功邀请 {emby_username}",
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
        await context.bot.send_message(
            chat_id=chat_id, text="错误：Plex/Emby 均未绑定，请先绑定任一"
        )
        return
    _credits, _donation = _stats_info[2], _stats_info[1]
    body_text = f"""
{'=' * 44}
<strong>可用积分: </strong>{_credits:.2f}
<strong>捐赠金额: </strong>{_donation}
<strong>可用邀请码：</strong>{"无" if not _codes else ", ".join(_codes)}
{'=' * 44}

"""
    if _plex_info:
        body_text += f"""
{'=' * 20} Plex {'=' * 20}
<strong>Plex 用户名：</strong>{_plex_info[4]}
<strong>总观看时长：</strong>{_plex_info[7]:.2f}h
<strong>当前权限：</strong>{"全部" if _plex_info[5] == 1 else "部分"}

"""
    if _emby_info:
        body_text += f"""
{'=' * 20} Emby {'=' * 20}
<strong>Emby 用户名: </strong>{_emby_info[0]}
<strong>总观看时长：</strong>{_emby_info[5]:.2f}h
<strong>当前权限：</strong>{"全部" if _emby_info[3] == 1 else "部分"}
"""
    await context.bot.send_message(chat_id=chat_id, text=body_text, parse_mode="HTML")


# 解锁 nsfw 库权限
async def unlock_nsfw_plex(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    _info = _db.get_plex_info_by_tg_id(chat_id)
    if not _info:
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 未查询到用户, 请先绑定"
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
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 您已拥有全部库权限, 无需解锁"
        )
        return
    if _credits < UNLOCK_CREDITS:
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 您的积分不足, 解锁失败"
        )
        _db.close()
        return
    _credits -= UNLOCK_CREDITS
    _plex = Plex()
    # 更新权限
    try:
        _plex.update_user_shared_libs(_plex_id, _plex.get_libraries())
    except:
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 更新权限失败, 请联系管理员"
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
    res = _db.update_all_lib_flag(all_lib=1, unlock_time=unlock_time, plex_id=_plex_id)
    if not res:
        _db.close()
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 数据库更新失败, 请联系管理员"
        )
        return
    _db.close()
    await context.bot.send_message(chat_id=chat_id, text="信息: 解锁成功, 请尽情享受")


# 锁定 NSFW 权限
async def lock_nsfw_plex(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    _info = _db.get_plex_info_by_tg_id(chat_id)
    if not _info:
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 未查询到用户, 请先绑定"
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
        await context.bot.send_message(chat_id=chat_id, text="错误: 您未解锁 NSFW 内容")
        return
    _credits_fund = caculate_credits_fund(_unlock_time, UNLOCK_CREDITS)
    _credits += _credits_fund
    _plex = Plex()
    # 更新权限
    sections = _plex.get_libraries()
    for section in NSFW_LIBS:
        sections.remove(section)
    try:
        _plex.update_user_shared_libs(_plex_id, sections)
    except:
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 更新权限失败, 请联系管理员"
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
    res = _db.update_all_lib_flag(all_lib=0, unlock_time=None, plex_id=_plex_id)
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
    if _credits < UNLOCK_CREDITS:
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 您的积分不足, 解锁失败"
        )
        _db.close()
        return
    _credits -= UNLOCK_CREDITS
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
    _credits_fund = caculate_credits_fund(_unlock_time, UNLOCK_CREDITS)
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


# 创建 overseerr 用户
async def create_overseerr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    text = update.message.text
    text_parts = text.split()
    if len(text_parts) != 3:
        await context.bot.send_message(chat_id=chat_id, text="错误: 请按照格式填写")
        return
    email, password = text_parts[1:]
    if len(password) < 8:
        await context.bot.send_message(chat_id=chat_id, text="错误：密码长度至少为 8")
        return
    db = DB()
    try:
        # 检查是否绑定了 Emby
        emby_info = db.get_emby_info_by_tg_id(tg_id=chat_id)
        plex_info = db.get_plex_info_by_tg_id(tg_id=chat_id)
        overseerr_info = db.get_overseerr_info_by_tg_id(tg_id=chat_id)
        overseerr_info_by_email = db.get_overseerr_info_by_email(email=email)
        if not emby_info:
            await context.bot.send_message(
                chat_id=chat_id, text="错误: 未绑定 Emby 帐号，不允许创建 Overseer 账户"
            )
            raise
        if plex_info:
            await context.bot.send_message(
                chat_id=chat_id,
                text="错误：您已绑定 Plex 账户，请使用 Plex 帐号登录 Overseer",
            )
            raise
        if overseerr_info:
            await context.bot.send_message(
                chat_id=chat_id, text="错误：您已创建过 Overseerr 账户，请勿重复创建"
            )
            raise
        if overseerr_info_by_email:
            await context.bot.send_message(
                chat_id=chat_id,
                text="错误：已存在该邮箱创建的 Overseerr 账户，请勿重复创建",
            )
            raise
        # 创建账户
        _overseerr = Overseerr()
        flag, msg = _overseerr.add_user(email, password)
        if not flag:
            logging.error(f"Failed to create overseerr user: {msg}")
            await context.bot.send_message(
                chat_id=chat_id, text="错误：创建账户失败，请联系管理员"
            )
            raise
        # 保存至数据库
        rslt = db.add_overseerr_user(user_id=msg, user_email=email, tg_id=chat_id)
        if not rslt:
            await context.bot.send_message(
                chat_id=chat_id, text="错误：数据库操作失败，请联系管理员"
            )
            raise
    except Exception as e:
        logging.error(e)
    finally:
        db.close()


# 积分榜
async def credits_rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    res = _db.get_credits_rank()
    rank = [
        f"{i}. {get_user_name_from_tg_id(info[0])}: {info[1]:.2f}"
        for i, info in enumerate(res, 1)
        if i <= 10
    ]

    body_text = """
<strong>积分榜</strong>
==================
{}
==================

⚠️只统计 TG 绑定用户
    """.format("\n".join(rank))
    logging.info(body_text)
    await context.bot.send_message(chat_id=chat_id, text=body_text, parse_mode="HTML")


# 捐赠榜
async def donation_rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    res = _db.get_donation_rank()
    rank = [
        f"{i}. {get_user_name_from_tg_id(info[0])}: {info[1]:.2f}"
        for i, info in enumerate(res, 1)
        if info[1] > 0
    ]

    body_text = """
<strong>捐赠榜</strong>
==================
{}
==================

衷心感谢各位的支持!
    """.format("\n".join(rank))
    logging.info(body_text)
    await context.bot.send_message(chat_id=chat_id, text=body_text, parse_mode="HTML")


# 观看时长榜
async def watched_time_rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    res = _db.get_plex_watched_time_rank()
    rank = [
        f"{i}. {info[2]}: {info[3]:.2f}" for i, info in enumerate(res, 1) if i <= 10
    ]
    emby_res = _db.get_emby_watched_time_rank()
    emby_rank = [
        f"{i}. {info[1]}: {info[2]:.2f}"
        for i, info in enumerate(emby_res, 1)
        if i <= 10
    ]
    body_text = """
<strong>观看时长榜 (Hour)</strong>
==================

------ Plex ------
{}

------ Emby ------
{}
    """.format("\n".join(rank), "\n".join(emby_rank))
    await context.bot.send_message(chat_id=chat_id, text=body_text, parse_mode="HTML")


# 获取当前注册状态
async def get_register_status(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    chat_id = update._effective_chat.id
    text = f"""
Plex: {"可注册" if PLEX_REGISTER else "注册关闭"}
Emby: {"可注册" if EMBY_REGISTER else "注册关闭"}
    """
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")


# 管理员命令: 设置捐赠信息
async def set_donation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    if chat_id not in ADMIN_CHAT_ID:
        await context.bot.send_message(chat_id=chat_id, text="错误：越权操作")
        return
    text = update.message.text
    text = text.split()
    if len(text) != 3:
        await context.bot.send_message(chat_id=chat_id, text="错误：请按照格式填写")
        return
    tg_id = int(text[1])
    donation = float(text[2])
    _db = DB()
    info = _db.get_stats_by_tg_id(tg_id)
    if not info:
        await context.bot.send_message(
            chat_id=chat_id, text=f"错误：用户 {tg_id} 不存在，请确认"
        )
        _db.close()
        return
    _credits = info[2]
    _donation = info[1]
    credits = _credits + donation * 2
    donate = _donation + donation
    res = _db.update_user_credits(credits, tg_id=tg_id)
    if not res:
        _db.close()
        await context.bot.send_message(
            chat_id=chat_id, text="错误：更新积分失败，请检查"
        )
        return
    res = _db.update_user_donation(donate, tg_id=tg_id)
    if not res:
        _db.close()
        await context.bot.send_message(
            chat_id=chat_id, text="错误：更新积分失败，请检查"
        )
        return
    _db.close()

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"信息：成功为 {get_user_name_from_tg_id(tg_id)} 设置捐赠金额 {donation}",
    )
    # 通知该用户
    await context.bot.send_message(
        chat_id=tg_id, text=f"通知：感谢您的捐赠，已为您增加积分 {donation * 2}"
    )


# 管理员命令：更新数据库
async def update_database(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    if chat_id not in ADMIN_CHAT_ID:
        await context.bot.send_message(chat_id=chat_id, text="错误：越权操作")
        return
    try:
        add_all_plex_user()
    except Exception as e:
        await context.bot.send_message(
            chat_id=chat_id, text="错误：更新数据库失败，请检查"
        )
        return

    await context.bot.send_message(chat_id=chat_id, text="信息：更新数据库成功")


# 管理员命令: 设置注册状态
async def set_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    if chat_id not in ADMIN_CHAT_ID:
        await context.bot.send_message(chat_id=chat_id, text="错误：越权操作")
        return
    text = update.message.text
    text = text.split()
    if len(text) != 3:
        await context.bot.send_message(chat_id=chat_id, text="错误：请按照格式填写")
        return
    server, flag = text[1:]
    if server.lower() not in {"plex", "emby"}:
        await context.bot.send_message(
            chat_id=chat_id, text="错误: 请指定正确的媒体服务器"
        )
        return
    global PLEX_REGISTER, EMBY_REGISTER
    if server.lower() == "plex":
        PLEX_REGISTER = True if flag != "0" else False
    elif server.lower() == "emby":
        EMBY_REGISTER = True if flag != "0" else False
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"信息: 设置 {server} 注册状态为 {'开启' if flag != '0' else '关闭'}",
    )


if __name__ == "__main__":
    application = ApplicationBuilder().token(TG_API_TOKEN).build()

    start_handler = CommandHandler("start", start)
    bind_plex_handler = CommandHandler("bind_plex", bind_plex)
    bind_emby_handler = CommandHandler("bind_emby", bind_emby)
    info_handler = CommandHandler("info", info)
    credits_rank_handler = CommandHandler("credits_rank", credits_rank)
    donation_rank_handler = CommandHandler("donation_rank", donation_rank)
    watched_time_rank_handler = CommandHandler("play_duration_rank", watched_time_rank)
    set_donation_handler = CommandHandler("set_donation", set_donation)
    unlock_nsfw_plex_handler = CommandHandler("unlock_nsfw_plex", unlock_nsfw_plex)
    lock_nsfw_plex_handler = CommandHandler("lock_nsfw_plex", lock_nsfw_plex)
    exchange_handler = CommandHandler("exchange", exchange)
    redeem_plex_handler = CommandHandler("redeem_plex", redeem_plex)
    redeem_emby_handler = CommandHandler("redeem_emby", redeem_emby)
    unlock_nsfw_emby_handler = CommandHandler("unlock_nsfw_emby", unlock_nsfw_emby)
    lock_nsfw_emby_handler = CommandHandler("lock_nsfw_emby", lock_nsfw_emby)
    create_overseerr_handler = CommandHandler("create_overseerr", create_overseerr)
    update_database_handler = CommandHandler("update_database", update_database)
    get_register_status_handler = CommandHandler("register_status", get_register_status)
    set_register_handler = CommandHandler("set_register", set_register)

    application.add_handler(start_handler)
    application.add_handler(bind_plex_handler)
    application.add_handler(bind_emby_handler)
    application.add_handler(info_handler)
    application.add_handler(credits_rank_handler)
    application.add_handler(donation_rank_handler)
    application.add_handler(watched_time_rank_handler)
    application.add_handler(set_donation_handler)
    application.add_handler(unlock_nsfw_plex_handler)
    application.add_handler(lock_nsfw_plex_handler)
    application.add_handler(exchange_handler)
    application.add_handler(redeem_plex_handler)
    application.add_handler(redeem_emby_handler)
    application.add_handler(unlock_nsfw_emby_handler)
    application.add_handler(lock_nsfw_emby_handler)
    application.add_handler(create_overseerr_handler)
    application.add_handler(update_database_handler)
    application.add_handler(get_register_status_handler)
    application.add_handler(set_register_handler)

    application.run_polling()
