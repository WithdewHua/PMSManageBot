import asyncio
import threading

from telegram.ext import ApplicationBuilder

from app.bot.app import register_handlers, set_bot_commands
from app.core import events
from app.core.config import settings
from app.core.log import logger
from app.core.scheduler import Scheduler
from app.model_registry import init_db


async def post_init_services(application):
    """在 Telegram 事件循环就绪后初始化服务"""
    events.bind_main_loop(asyncio.get_running_loop())
    await set_bot_commands(application)

    try:
        scheduler = Scheduler()
        from app.schedule import migrate_persisted_jobs, register_all

        register_all(scheduler)
        migrate_persisted_jobs(scheduler)
        scheduler.start()
        logger.info("调度器初始化完成")
    except Exception as e:
        logger.error(f"初始化调度器失败: {e}")


def start_api_server():
    """启动 WebApp API 服务器"""
    import uvicorn

    # Static files are mounted by app.api.app after all API routes.

    # 启动 FastAPI 服务
    uvicorn.run(
        "app.api.app:app",
        host=settings.WEBAPP_HOST,
        port=settings.WEBAPP_PORT,
        reload=False,
        log_level="info",
        access_log=True,
        use_colors=True,
        proxy_headers=True,  # 启用代理头解析，默认 True
        forwarded_allow_ips="*",  # 允许所有代理 IP 或指定 IP，以保证在使用反向代理（如 Nginx）时能正确获取客户端 IP 地址
    )


def start_bot(application):
    """启动 Telegram Bot"""
    application.run_polling()


if __name__ == "__main__":
    logger.info("启动 PMSManageBot 服务...")

    # 初始化数据库
    init_db()

    from app.business_config import seed_all

    seed_all()

    from app.domains.invitation import service as invitation_service
    from app.domains.lines import catalog as line_catalog

    invitation_service.import_legacy_privileged_codes()
    line_catalog.import_legacy_line_catalog_if_needed()

    from app.subscriptions import register_all

    register_all()

    # 初始化 Telegram Bot 应用
    application = ApplicationBuilder().token(settings.TG_API_TOKEN).build()

    # 注册处理程序（显式列表，顺序由 bot/app.py 固定）
    register_handlers(application)

    # 在应用启动后（事件循环就绪）初始化命令与调度器
    application.post_init = post_init_services

    # Make named one-shot jobs resolvable before the API handles requests.
    # Recurring registration, jobstore migration and scheduler.start stay in
    # post_init_services, where the Telegram event loop is ready.
    from app.schedule import register_tasks

    register_tasks()

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
