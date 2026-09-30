from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.core.config import settings
from app.core.log import logger
from app.domains.rankings import service as rankings_service
from app.integrations.telegram.messaging import send_message


# 积分榜
async def credits_rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    try:
        res = rankings_service.get_credits_rank(limit=30, exclude_admins=False)
        rank = [
            f"{i}. {item['name']}: {item['credits']:.2f}"
            for i, item in enumerate(res, 1)
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
    except Exception:
        logger.exception("获取积分榜失败")
        await send_message(
            chat_id=chat_id, text="获取失败，请稍后再试", context=context
        )


# 捐赠榜
async def donation_rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    try:
        res = rankings_service.get_donation_rank(
            exclude_admins=False, include_zero=False
        )
        rank = [
            f"{i}. {item['name']}: {item['donation']:.2f}"
            for i, item in enumerate(res, 1)
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
    except Exception:
        logger.exception("获取捐赠榜失败")
        await send_message(
            chat_id=chat_id, text="获取失败，请稍后再试", context=context
        )


# 观看时长榜
async def watched_time_rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    try:
        plex_res = rankings_service.get_watch_time_rank(
            "plex", limit=15, include_zero=True, with_avatar=False
        )
        rank = [
            f"{i}. {item['name']}: {item['watched_time']:.2f}"
            for i, item in enumerate(plex_res, 1)
        ]
        emby_res = rankings_service.get_watch_time_rank(
            "emby", limit=15, include_zero=True, with_avatar=False
        )
        emby_rank = [
            f"{i}. {item['name']}: {item['watched_time']:.2f}"
            for i, item in enumerate(emby_res, 1)
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
    except Exception:
        logger.exception("获取观看时长榜失败")
        await send_message(
            chat_id=chat_id, text="获取失败，请稍后再试", context=context
        )


# 设备榜
async def device_rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    if chat_id not in settings.TG_ADMIN_CHAT_ID:
        await send_message(chat_id=chat_id, text="错误：越权操作", context=context)
        return
    devices_data = rankings_service.get_device_rank(limit=30)
    rank = [
        f"{i}. {user_devices.get('user_name')}: 设备 {user_devices.get('device_count')}, 客户端 {user_devices.get('client_count')}, IP {user_devices.get('ip_count')}"
        for i, user_devices in enumerate(devices_data, 1)
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


async def rank_24h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    body_text = rankings_service.render_recent_media_rankings()
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=body_text, parse_mode="HTML"
    )


credits_rank_handler = CommandHandler("credits_rank", credits_rank)
donation_rank_handler = CommandHandler("donation_rank", donation_rank)
watched_time_rank_handler = CommandHandler("play_duration_rank", watched_time_rank)
device_rank_handler = CommandHandler("device_rank", device_rank)
rank_24h_handler = CommandHandler("rank_24h", rank_24h)

__all__ = [
    "credits_rank_handler",
    "device_rank_handler",
    "donation_rank_handler",
    "rank_24h_handler",
    "watched_time_rank_handler",
]
