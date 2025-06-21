# ruff: noqa: F403
import datetime
import threading
from copy import copy

from app.config import settings
from app.handlers.db import *

# from app.handlers.emby import *
# from app.handlers.plex import *
from app.handlers.rank import *
from app.handlers.start import *
from app.handlers.status import *
from app.handlers.user import *
from app.log import logger
from app.premium import check_premium_expiring_soon, check_premium_expiry
from app.scheduler import Scheduler
from app.update_db import finish_expired_auctions_job, update_credits, update_plex_info
from app.utils import refresh_emby_user_info, refresh_tg_user_info
from telegram.ext import ApplicationBuilder


def start_api_server():
    """启动 WebApp API 服务器"""
    import uvicorn
    from app.webapp import setup_static_files

    # 配置静态文件
    if not setup_static_files():
        logger.warning("WebApp 静态文件配置失败，仅 API 端点可用")

    # 启动 FastAPI 服务
    uvicorn.run(
        "app.webapp:app",
        host=settings.WEBAPP_HOST,
        port=settings.WEBAPP_PORT,
        reload=False,
        log_level="info",
        access_log=True,
        use_colors=True,
    )


def start_bot(application):
    """启动 Telegram Bot"""
    application.run_polling()


def add_init_scheduler_job():
    """添加调度任务"""
    scheduler = Scheduler()
    # 每天凌晨 12:00 更新 Plex/Emby 积分 (同步任务)
    scheduler.add_sync_job(
        func=update_credits,
        trigger="cron",
        id="update_credits",
        replace_existing=True,
        max_instances=1,
        day_of_week="*",
        hour=0,
        minute=0,
    )
    logger.info("添加定时任务：每天凌晨 12:00 更新积分 (Plex 和 Emby)")
    # 每天中午 12:00 更新 plex 用户信息 (同步任务)
    scheduler.add_sync_job(
        func=update_plex_info,
        trigger="cron",
        id="update_plex_info",
        replace_existing=True,
        max_instances=1,
        day_of_week="*",
        hour=12,
        minute=0,
    )
    logger.info("添加定时任务：每天中午 12:00 更新 Plex 用户信息")

    # 每天中午 12:10 更新 tg 用户信息 (异步任务)
    scheduler.add_async_job(
        func=refresh_tg_user_info,
        trigger="cron",
        id="refresh_user_info",
        replace_existing=True,
        max_instances=1,
        day_of_week="*",
        hour=12,
        minute=10,
        next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=30),
    )
    logger.info("添加定时任务：每天中午 12:10 更新 Telegram 用户信息")

    # 每天早上 7 点刷新 emby 用户信息 (同步任务)
    scheduler.add_sync_job(
        func=refresh_emby_user_info,
        trigger="cron",
        id="refresh_emby_user_info",
        replace_existing=True,
        max_instances=1,
        day_of_week="*",
        hour=7,
        minute=0,
        next_run_time=datetime.datetime.now() + datetime.timedelta(minutes=1),
    )
    logger.info("添加定时任务：每天早上 07:00 更新 Emby 用户信息")

    # 每小时检查并结束过期的竞拍活动 (同步任务)
    scheduler.add_async_job(
        func=finish_expired_auctions_job,
        trigger="cron",
        id="finish_expired_auctions",
        replace_existing=True,
        max_instances=1,
        minute=0,  # 每小时的第0分钟执行
    )
    logger.info("添加定时任务：每小时自动结束过期竞拍活动")

    # 每 5 分钟检查 Premium 会员过期状态 (异步任务)
    scheduler.add_async_job(
        func=check_premium_expiry,
        trigger="cron",
        id="check_premium_expiry",
        replace_existing=True,
        max_instances=1,
        minute="*/5",  # 每 5 分钟执行一次
    )
    logger.info("添加定时任务：每 5 分钟检查 Premium 会员过期状态")

    # 每天早上 9:00 检查即将过期的 Premium 用户 (异步任务)
    scheduler.add_async_job(
        func=check_premium_expiring_soon,
        trigger="cron",
        id="check_premium_expiring_soon",
        replace_existing=True,
        max_instances=1,
        day_of_week="*",
        hour=9,
        minute=0,
    )
    logger.info("添加定时任务：每天早上 09:00 检查即将过期的 Premium 用户")


if __name__ == "__main__":
    logger.info("启动 PMSManageBot 服务...")

    # 启动定时任务
    logger.info("启动调度器...")
    add_init_scheduler_job()

    # 初始化 Telegram Bot 应用
    application = ApplicationBuilder().token(settings.TG_API_TOKEN).build()

    # 注册处理程序
    local_vars = copy(locals())
    for var, val in local_vars.items():
        if var.endswith("_handler"):
            logger.info(f"Add handler: {var}")
            application.add_handler(val)

    # 根据配置决定是否启动 WebApp
    if settings.WEBAPP_ENABLE:
        # 启动 API 服务器（在单独的线程中）
        api_thread = threading.Thread(target=start_api_server)
        api_thread.daemon = True
        api_thread.start()
        logger.info(
            f"WebApp 服务已启动 - 监听在 {settings.WEBAPP_HOST}:{settings.WEBAPP_PORT}"
        )
    else:
        logger.info("WebApp 服务已禁用（在配置中设置 ENABLE_WEBAPP=True 可启用）")

    # 启动 Telegram Bot（在主线程中）
    logger.info("启动 Telegram Bot...")
    start_bot(application)
