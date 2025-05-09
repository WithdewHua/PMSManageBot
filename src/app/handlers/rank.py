from app.config import settings
from app.db import DB
from app.emby import Emby
from app.log import logger
from app.utils import get_user_name_from_tg_id, send_message
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes


# 积分榜
async def credits_rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    res = _db.get_credits_rank()
    rank = [
        f"{i}. {get_user_name_from_tg_id(info[0])}: {info[1]:.2f}"
        for i, info in enumerate(res, 1)
        if i <= 30
    ]

    body_text = """
<strong>积分榜</strong>
==================
{}
==================

⚠️只统计 TG 绑定用户
    """.format("\n".join(rank))
    logger.info(body_text)
    await send_message(
        chat_id=chat_id, text=body_text, parse_mode="HTML", context=context
    )


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
    logger.debug(body_text)
    await send_message(
        chat_id=chat_id, text=body_text, parse_mode="HTML", context=context
    )


# 观看时长榜
async def watched_time_rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _db = DB()
    res = _db.get_plex_watched_time_rank()
    rank = [
        f"{i}. {info[2]}: {info[3]:.2f}" for i, info in enumerate(res, 1) if i <= 15
    ]
    emby_res = _db.get_emby_watched_time_rank()
    emby_rank = [
        f"{i}. {info[1]}: {info[2]:.2f}"
        for i, info in enumerate(emby_res, 1)
        if i <= 15
    ]
    body_text = """
<strong>观看时长榜 (Hour)</strong>
==================

------ Plex ------
{}

------ Emby ------
{}
    """.format("\n".join(rank), "\n".join(emby_rank))
    await send_message(
        chat_id=chat_id, text=body_text, parse_mode="HTML", context=context
    )


# 设备榜
async def device_rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    if chat_id not in settings.ADMIN_CHAT_ID:
        await send_message(chat_id=chat_id, text="错误：越权操作", context=context)
        return
    emby = Emby()
    devices_data = sorted(
        emby.get_devices_per_user(), key=lambda x: len(x["devices"]), reverse=True
    )
    rank = [
        f"{i}. {user_devices.get('user_name')}: 设备 {len(user_devices.get('devices'))}, 客户端 {len(user_devices.get('clients'))}, IP {len(user_devices.get('ip'))}"
        for i, user_devices in enumerate(devices_data[:30], 1)
    ]

    body_text = """
<strong>设备榜</strong>
==================
{}
==================
""".format("\n".join(rank))
    logger.debug(body_text)
    await send_message(
        chat_id=chat_id, text=body_text, parse_mode="HTML", context=context
    )


credits_rank_handler = CommandHandler("credits_rank", credits_rank)
donation_rank_handler = CommandHandler("donation_rank", donation_rank)
watched_time_rank_handler = CommandHandler("play_duration_rank", watched_time_rank)
device_rank_handler = CommandHandler("device_rank", device_rank)

__all__ = [
    "credits_rank_handler",
    "donation_rank_handler",
    "watched_time_rank_handler",
    "device_rank_handler",
]
