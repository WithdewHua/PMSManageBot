"""Explicit Telegram handler and command-menu assembly."""

from telegram import BotCommand

from app.bot.start import start_handler
from app.core.config import settings
from app.core.log import logger
from app.domains.accounts import bot as accounts_bot
from app.domains.donation import bot as donation_bot
from app.domains.invitation import bot as invitation_bot
from app.domains.profile import bot as profile_bot
from app.domains.rankings import bot as rankings_bot
from app.domains.reports import bot as reports_bot

HANDLERS = (
    rankings_bot.credits_rank_handler,
    rankings_bot.donation_rank_handler,
    rankings_bot.watched_time_rank_handler,
    rankings_bot.device_rank_handler,
    rankings_bot.rank_24h_handler,
    start_handler,
    accounts_bot.get_register_status_handler,
    accounts_bot.set_register_handler,
    reports_bot.get_server_status_handler,
    profile_bot.info_handler,
    donation_bot.set_donation_handler,
    invitation_bot.exchange_handler,
    accounts_bot.create_overseerr_handler,
)


async def set_bot_commands(application):
    """设置机器人命令列表."""
    commands = [
        BotCommand("start", "开始使用机器人"),
        BotCommand("info", "查看个人信息"),
        BotCommand("server_status", "查看服务器在线人数/状态"),
        BotCommand("rank_24h", "查看24小时观看时长榜"),
        BotCommand("exchange", f"生成邀请码(消耗 {settings.INVITATION_CREDITS} 积分)"),
        BotCommand("credits_rank", "查看积分榜"),
        BotCommand("donation_rank", "查看捐赠榜"),
        BotCommand("play_duration_rank", "查看观看时长榜"),
        BotCommand("device_rank", "查看设备榜"),
        BotCommand("register_status", "查看 Plex/Emby 是否可注册"),
        BotCommand("create_overseerr", "创建 Overseerr 账户"),
        BotCommand("set_donation", "设置捐赠金额 (管理员)"),
        BotCommand("update_database", "更新数据库 (管理员)"),
        BotCommand("set_register", "设置可注册状态 (管理员)"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("机器人命令列表设置成功")
    except Exception as e:
        logger.error(f"设置机器人命令列表失败: {e}")


def register_handlers(application) -> None:
    """Register handlers in the legacy discovery order."""
    for handler in HANDLERS:
        logger.info(f"Add handler: {handler}")
        application.add_handler(handler)
