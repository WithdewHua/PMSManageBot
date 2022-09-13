import logging

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from plex import Plex
from db import DB
from tautulli import Tautulli
from settings import TG_API_TOKEN, ADMIN_CHAT_ID
from utils import get_user_total_duration


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
/credits_rank - 查看积分榜

管理员命令：
/set_donation - 设置捐赠金额
    """
    await context.bot.send_message(chat_id=update.effective_chat.id, text=body_text, parse_mode="markdown")
    
async def bind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text
    try:
        email = text.split()[1]
    except Exception as e:
        logging.error("Error: ", e)
        await context.bot.send_message(chat_id=chat_id, text="错误：请按照格式填写")
        return
    
    _db = DB()
    _info = _db.get_info_by_tg_id(chat_id)
    if _info:
        _db.close()
        await context.bot.send_message(chat_id=chat_id, text="信息：已绑定 Plex 账户，请勿重复操作")
        return
    
    _plex = Plex()
    plex_id = _plex.get_user_id_by_email(email)
    plex_username = _plex.get_username_by_user_id(plex_id)
    # 用户不存在
    if plex_id == 0:
        _db.close()
        await context.bot.send_message(chat_id=chat_id, text="错误：该用户不是 @WithdewHua 好友，请检查输入的邮箱")
        return
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
    rslt = _db.add_user(plex_id, chat_id, email, plex_username, credits=credits)
    _db.close()
    if not rslt:
        await context.bot.send_message(chat_id=chat_id, text="错误：数据库错误，请联系管理员 @WithdewHua")
        return
    await context.bot.send_message(chat_id=chat_id, text=f"信息： 绑定用户 {plex_id} 成功")

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    _info = _db.get_info_by_tg_id(chat_id)
    _db.close()
    if _info is None:
        await context.bot.send_message(chat_id=chat_id, text="错误：未绑定 Plex，请先绑定")
        return
    plex_id = _info[0]
    credits = _info[2]
    donate = _info[3]
    _plex = Plex()
    body_text = f"""
<strong>Plex 用户名：</strong>{_info[5]}
<strong>可用积分：</strong>{credits}
<strong>捐赠金额：</strong>{donate}
<strong>当前权限：</strong>{"全部" if _plex.verify_all_libraries(plex_id) else "部分"}
"""
    await context.bot.send_message(chat_id=chat_id, text=body_text, parse_mode="HTML")
    
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


if __name__ == '__main__':
    application = ApplicationBuilder().token(TG_API_TOKEN).build()

    start_handler = CommandHandler('start', start)
    bind_handler = CommandHandler("bind", bind)
    info_handler = CommandHandler("info", info)
    credits_rank_handler = CommandHandler("credits_rank", credits_rank)
    set_donation_handler = CommandHandler("set_donation", set_donation)
    application.add_handler(start_handler)
    application.add_handler(bind_handler)
    application.add_handler(info_handler)
    application.add_handler(credits_rank_handler)
    application.add_handler(set_donation_handler)

    application.run_polling()

