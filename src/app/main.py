# ruff: noqa: F403
import threading
from copy import copy

from app.config import settings
from app.handlers.db import *
from app.handlers.emby import *
from app.handlers.plex import *
from app.handlers.rank import *
from app.handlers.start import *
from app.handlers.status import *
from app.handlers.user import *
from app.handlers.webapp import *  # 导入新的 WebApp 处理程序
from app.log import logger
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


if __name__ == "__main__":
    logger.info("启动 PMSManageBot 服务...")

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
