import logging
import time

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from plex import Plex
from db import DB
from tautulli import Tautulli
from settings import TG_API_TOKEN, ADMIN_CHAT_ID, UNLOCK_CREDITS
from utils import get_user_total_duration, caculate_credits_fund


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
/credits\_rank - 查看积分榜
/donation\_rank - 查看捐赠榜

管理员命令：
/set\_donation - 设置捐赠金额
    """.format(UNLOCK_CREDITS)
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
    plex_username = _plex.get_username_by_user_id(plex_id)
    plex_cur_libs = _plex.get_user_shared_libs_by_id(plex_id)
    plex_all_lib = 1 if not set(_plex.get_libraries()).difference(set(plex_cur_libs)) else 0
    # 初始化积分
    try:
        user_total_duration = get_user_total_duration(Tautulli().get_home_stats(365, "duration", len(_plex.users_by_id), stat_id="top_users"))
    except Exception as e:
        _db.close()
        logging.error("Error: ", e)
        await context.bot.send_message(chat_id=chat_id, text="错误：获取用户观看时长失败，请联系管理员 @WithdewHua")
        return
    credits = user_total_duration.get(plex_id, 0)
    # 写入数据库
    rslt = _db.add_user(plex_id, chat_id, email, plex_username, credits=credits, all_lib=plex_all_lib)
    _db.close()
    if not rslt:
        await context.bot.send_message(chat_id=chat_id, text="错误：数据库错误，请联系管理员 @WithdewHua")
        return
    await context.bot.send_message(chat_id=chat_id, text=f"信息： 绑定用户 {plex_id} 成功")

# 查看个人信息
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    _info = _db.get_info_by_tg_id(chat_id)
    _db.close()
    if _info is None:
        await context.bot.send_message(chat_id=chat_id, text="错误：未绑定 Plex，请先绑定")
        return
    credits = _info[2]
    donate = _info[3]
    all_lib = _info[6]
    body_text = f"""
<strong>Plex 用户名：</strong>{_info[5]}
<strong>可用积分：</strong>{credits:.2f}
<strong>捐赠金额：</strong>{donate:.2f}
<strong>当前权限：</strong>{"全部" if all_lib == 1 else "部分"}
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
    for section in ["NSFW", "NC17-Movies"]:
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


if __name__ == '__main__':
    application = ApplicationBuilder().token(TG_API_TOKEN).build()

    start_handler = CommandHandler('start', start)
    bind_handler = CommandHandler("bind", bind)
    info_handler = CommandHandler("info", info)
    credits_rank_handler = CommandHandler("credits_rank", credits_rank)
    donation_rank_handler = CommandHandler("donation_rank", donation_rank)
    set_donation_handler = CommandHandler("set_donation", set_donation)
    unlock_handler = CommandHandler("unlock", unlock)
    lock_handler = CommandHandler("lock", lock)
    application.add_handler(start_handler)
    application.add_handler(bind_handler)
    application.add_handler(info_handler)
    application.add_handler(credits_rank_handler)
    application.add_handler(donation_rank_handler)
    application.add_handler(set_donation_handler)
    application.add_handler(unlock_handler)
    application.add_handler(lock_handler)

    application.run_polling()

