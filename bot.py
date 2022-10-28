import logging
from time import time

from uuid import uuid3, NAMESPACE_URL

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from plex import Plex
from db import DB
from tautulli import Tautulli
from settings import (
    TG_API_TOKEN, ADMIN_CHAT_ID, UNLOCK_CREDITS, INVITATION_CREDITS,
    NSFW_LIBS
)
from utils import get_user_total_duration, caculate_credits_fund
from update_db import add_all_plex_user


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    body_text = """
欢迎来到 FunMedia 小助手

普通命令：
/info - 查看个人信息
/bind - 绑定 Plex 用户，格式为 `/bind 邮箱` (注意空格)
/unlock - 解锁全部库权限, 消耗 {} 积分
/lock - 关闭 NSFW 权限, 积分返还规则：一天内返还 90%, 7 天内 70%, 一月内 50%，超出一个月 0
/exchange - 生成邀请码，消耗 {} 积分
/redeem - 兑换邀请码，格式为 `/redeem 邮箱 邀请码` (注意空格)
/credits\_rank - 查看积分榜
/donation\_rank - 查看捐赠榜
/play\_duration\_rank - 查看观看时长榜

管理员命令：
/set\_donation - 设置捐赠金额
/update\_database - 更新数据库

群组：https://t.me/+VCHVfOhRTAxmOGE9
    """.format(UNLOCK_CREDITS, INVITATION_CREDITS)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=body_text, parse_mode="markdown")

# 绑定账户
async def bind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text
    text = text.split()
    if len(text) != 2:
        await context.bot.send_message(chat_id=chat_id, text="错误：请按照格式填写")
        return
    email = text[1]
    _db = DB()
    _info = _db.get_info_by_tg_id(chat_id)
    if _info:
        _db.close()
        await context.bot.send_message(chat_id=chat_id, text="信息：已绑定 Plex 账户，请勿重复操作")
        return
    
    _plex = Plex()
    plex_id = _plex.get_user_id_by_email(email)
    # 用户不存在
    if plex_id == 0:
        _db.close()
        await context.bot.send_message(chat_id=chat_id, text="错误：该用户不是 @WithdewHua 好友，请检查输入的邮箱")
        return
    # 检查数据库中是否存在该 plex_id，如存在直接更新 tg_id
    if _db.get_info_by_plex_id(plex_id):
        rslt = _db.update_user(plex_id, chat_id)
        _db.close()
        if not rslt:
            await context.bot.send_message(chat_id=chat_id, text="错误：数据库错误，请联系管理员 @WithdewHua")
            return
    else:
        plex_username = _plex.get_username_by_user_id(plex_id)
        plex_cur_libs = _plex.get_user_shared_libs_by_id(plex_id)
        plex_all_lib = 1 if not set(_plex.get_libraries()).difference(set(plex_cur_libs)) else 0
        # 初始化积分
        try:
            user_total_duration = get_user_total_duration(Tautulli().get_home_stats(1365, "duration", len(_plex.users_by_id), stat_id="top_users"))
        except Exception as e:
            _db.close()
            logging.error("Error: ", e)
            await context.bot.send_message(chat_id=chat_id, text="错误：获取用户观看时长失败，请联系管理员 @WithdewHua")
            return
        credits = user_total_duration.get(plex_id, 0)
        # 写入数据库
        rslt = _db.add_user(plex_id, chat_id, email, plex_username, credits=credits, all_lib=plex_all_lib, watched_time=credits)
        _db.close()
        if not rslt:
            await context.bot.send_message(chat_id=chat_id, text="错误：数据库错误，请联系管理员 @WithdewHua")
            return
    await context.bot.send_message(chat_id=chat_id, text=f"信息： 绑定用户 {plex_id} 成功，请加入群组 https://t.me/+VCHVfOhRTAxmOGE9 并仔细阅读群置顶")

# 生成邀请码
async def exchange(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    _info = _db.get_info_by_tg_id(chat_id)
    if _info is None:
        _db.close()
        await context.bot.send_message(chat_id=chat_id, text="错误：未绑定 Plex，请先绑定")
        return
    _credits = _info[2] 
    _plex_id = _info[0]
    # 检查剩余积分
    if _credits < INVITATION_CREDITS:
        _db.close()
        await context.bot.send_message(chat_id=chat_id, text="错误：您的积分不足，无法兑换邀请码")
        return
    _credits -= INVITATION_CREDITS
    # 生成邀请码
    _code = uuid3(NAMESPACE_URL, str(_plex_id + time())).hex
    # 更新数据库
    # > 先更新邀请码
    res = _db.add_invitation_code(code=_code, owner=chat_id)
    if not res:
        _db.close()
        await context.bot.send_message(chat_id=chat_id, text="错误: 更新邀请码失败, 请联系管理员")
        return
    # > 再更新积分情况
    res = _db.update_user_credits(_credits, plex_id=_plex_id)
    if not res:
        _db.close()
        await context.bot.send_message(chat_id=chat_id, text="错误: 更新积分失败, 请联系管理员")
        return
    _db.close()
    await context.bot.send_message(chat_id=chat_id, text="""信息: 生成邀请码成功，邀请码为 `{}`""".format(_code), parse_mode="markdown")

# 用户兑换邀请码
async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    text = update.message.text
    text_parts = text.split()
    if len(text_parts) != 3:
        await context.bot.send_message(chat_id=chat_id, text="错误：请按照格式填写")
        return
    plex_email = text_parts[1]
    code = text_parts[2]
    _db = DB()
    res = _db.verify_invitation_code_is_used(code)
    if not res:
        await context.bot.send_message(chat_id=chat_id, text="错误：您输入的邀请码无效")
        _db.close()
        return
    if res[0]:
        await context.bot.send_message(chat_id=chat_id, text="错误：您输入的邀请码已被使用")
        _db.close()
        return
    _plex = Plex()
    # 检查该用户是否已经被邀请
    if plex_email in _plex.users_by_email:
        await context.bot.send_message(chat_id=chat_id, text="错误：该用户已被邀请")
        _db.close()
        return
    # 发送邀请
    _plex.invite_friend(plex_email)
    # 更新邀请码状态
    res = _db.update_invitation_status(code=code, used_by=plex_email)
    if not res:
        await context.bot.send_message(chat_id=chat_id, text="错误：更新邀请码状态失败，请联系管理员")
        _db.close()
        return
    _db.close()
    await context.bot.send_message(chat_id=chat_id, text="信息：兑换邀请码成功，请登录 Plex 确认邀请，更多帮助请加入群组 https://t.me/+VCHVfOhRTAxmOGE9")


# 查看个人信息
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    _info = _db.get_info_by_tg_id(chat_id)
    _codes = _db.get_invitation_code_by_owner(chat_id)
    _db.close()
    if _info is None:
        await context.bot.send_message(chat_id=chat_id, text="错误：未绑定 Plex，请先绑定")
        return
    credits = _info[2]
    donate = _info[3]
    all_lib = _info[6]
    watched_time = _info[8]
    body_text = f"""
<strong>Plex 用户名：</strong>{_info[5]}
<strong>可用积分：</strong>{credits:.2f}
<strong>捐赠金额：</strong>{donate:.2f}
<strong>总观看时长：</strong>{watched_time:.2f}h
<strong>当前权限：</strong>{"全部" if all_lib == 1 else "部分"}
<strong>可用邀请码：</strong>{"无" if not _codes else ", ".join(_codes)}
"""
    await context.bot.send_message(chat_id=chat_id, text=body_text, parse_mode="HTML")

# 解锁所有库权限
async def unlock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    _info = _db.get_info_by_tg_id(chat_id)
    if not _info:
        await context.bot.send_message(chat_id=chat_id, text="错误: 未查询到用户, 请先绑定")
        _db.close()
        return
    _plex_id = _info[0]
    _credits = _info[2]
    _all_lib = _info[6]
    if _all_lib == 1:
        _db.close()
        await context.bot.send_message(chat_id=chat_id, text="错误: 您已拥有全部库权限, 无需解锁")
        return
    if _credits < UNLOCK_CREDITS:
        await context.bot.send_message(chat_id=chat_id, text="错误: 您的积分不足, 解锁失败")
        _db.close()
        return
    _credits -= UNLOCK_CREDITS
    _plex = Plex()
    # 更新权限
    try:
        _plex.update_user_shared_libs(_plex_id, _plex.get_libraries())
    except:
        await context.bot.send_message(chat_id=chat_id, text="错误: 更新权限失败, 请联系管理员")
        _db.close()
        return
    # 解锁权限的时间
    unlock_time = time.time()
    # 更新数据库
    res = _db.update_user_credits(_credits, plex_id=_plex_id)
    if not res:
        _db.close()
        await context.bot.send_message(chat_id=chat_id, text="错误: 数据库更新失败, 请联系管理员")
        return
    res = _db.update_all_lib_flag(all_lib=1, unlock_time=unlock_time, plex_id=_plex_id)
    if not res:
        _db.close()
        await context.bot.send_message(chat_id=chat_id, text="错误: 数据库更新失败, 请联系管理员")
        return
    _db.close()
    await context.bot.send_message(chat_id=chat_id, text="信息: 解锁成功, 请尽情享受")

 # 锁定 NSFW 权限
async def lock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    _info = _db.get_info_by_tg_id(chat_id)
    if not _info:
        await context.bot.send_message(chat_id=chat_id, text="错误: 未查询到用户, 请先绑定")
        _db.close()
        return
    _plex_id = _info[0]
    _credits = _info[2]
    _all_lib = _info[6]
    _unlock_time = _info[7]
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
        await context.bot.send_message(chat_id=chat_id, text="错误: 更新权限失败, 请联系管理员")
        _db.close()
        return
    # 更新数据库
    res = _db.update_user_credits(_credits, plex_id=_plex_id)
    if not res:
        _db.close()
        await context.bot.send_message(chat_id=chat_id, text="错误: 数据库更新失败, 请联系管理员")
        return
    res = _db.update_all_lib_flag(all_lib=0, unlock_time=None, plex_id=_plex_id)
    if not res:
        _db.close()
        await context.bot.send_message(chat_id=chat_id, text="错误: 数据库更新失败, 请联系管理员")
        return
    _db.close()
    await context.bot.send_message(chat_id=chat_id, text=f"信息: 成功关闭 NSFW 内容, 退回积分 {_credits_fund}")

   
# 积分榜
async def credits_rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    res = _db.get_credits_rank()
    rank = [f"{i}. {info[2]}: {info[3]:.2f}" for i, info in enumerate(res, 1) if i <= 10]
    body_text = """
<strong>积分榜</strong>
==================
{}
    """.format("\n".join(rank))        
    await context.bot.send_message(chat_id=chat_id, text=body_text, parse_mode="HTML")

# 捐赠榜
async def donation_rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    res = _db.get_donation_rank()
    rank = [f"{i}. {info[2]}: {info[3]:.2f}" for i, info in enumerate(res, 1) if info[3] > 0]
    body_text = """
<strong>捐赠榜</strong>
==================
{}
==================

衷心感谢各位的支持!
    """.format("\n".join(rank))        
    await context.bot.send_message(chat_id=chat_id, text=body_text, parse_mode="HTML")


# 观看时长榜
async def watched_time_rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    res = _db.get_watched_time_rank()
    rank = [f"{i}. {info[2]}: {info[3]:.2f}" for i, info in enumerate(res, 1) if i <= 10]
    body_text = """
<strong>观看时长榜 (Hour)</strong>
==================
{}
    """.format("\n".join(rank))        
    await context.bot.send_message(chat_id=chat_id, text=body_text, parse_mode="HTML")



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
    info = _db.get_info_by_tg_id(tg_id)
    if not info:
        await context.bot.send_message(chat_id=chat_id, text=f"错误：用户 {tg_id} 非好友，请确认")
        _db.close()
        return
    _credits = info[2]
    _donation = info[3]
    credits = _credits + donation * 2
    donate = _donation + donation
    res = _db.update_user_credits(credits, tg_id=tg_id)
    if not res:
        _db.close()
        await context.bot.send_message(chat_id=chat_id, text="错误：更新积分失败，请检查")
        return
    res = _db.update_user_donation(donate, tg_id=tg_id)
    if not res:
        _db.close()
        await context.bot.send_message(chat_id=chat_id, text="错误：更新积分失败，请检查")
        return
    _db.close()
    await context.bot.send_message(chat_id=chat_id, text=f"信息：成功为 {tg_id} 设置捐赠金额 {donation}")
    # 通知该用户
    await context.bot.send_message(chat_id=tg_id, text=f"通知：感谢您的捐赠，已为您增加积分 {donation * 2}")

# 管理员命令：更新数据库
async def update_database(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    if chat_id not in ADMIN_CHAT_ID:
        await context.bot.send_message(chat_id=chat_id, text="错误：越权操作")
        return
    try:
        add_all_plex_user()
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text="错误：更新数据库失败，请检查")
        return
    
    await context.bot.send_message(chat_id=chat_id, text=f"信息：更新数据库成功")


if __name__ == '__main__':
    application = ApplicationBuilder().token(TG_API_TOKEN).build()

    start_handler = CommandHandler('start', start)
    bind_handler = CommandHandler("bind", bind)
    info_handler = CommandHandler("info", info)
    credits_rank_handler = CommandHandler("credits_rank", credits_rank)
    donation_rank_handler = CommandHandler("donation_rank", donation_rank)
    watched_time_rank_handler = CommandHandler("play_duration_rank", watched_time_rank)
    set_donation_handler = CommandHandler("set_donation", set_donation)
    unlock_handler = CommandHandler("unlock", unlock)
    lock_handler = CommandHandler("lock", lock)
    exchange_handler = CommandHandler("exchange", exchange)
    redeem_handler = CommandHandler("redeem", redeem)
    update_database_handler = CommandHandler("update_database", update_database)
    application.add_handler(start_handler)
    application.add_handler(bind_handler)
    application.add_handler(info_handler)
    application.add_handler(credits_rank_handler)
    application.add_handler(donation_rank_handler)
    application.add_handler(watched_time_rank_handler)
    application.add_handler(set_donation_handler)
    application.add_handler(unlock_handler)
    application.add_handler(lock_handler)
    application.add_handler(exchange_handler)
    application.add_handler(redeem_handler)
    application.add_handler(update_database_handler)

    application.run_polling()

