import secrets
from pathlib import Path

from app.config import settings
from app.log import logger
from app.webapp.middlewares import TelegramAuthMiddleware
from app.webapp.routers import rankings_router, user_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

# 创建 FastAPI 应用
app = FastAPI(title="PMSManageBot API", description="API for PMSManageBot WebApp")

# 配置 SessionMiddleware
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.WEBAPP_SESSION_SECRET_KEY
    if hasattr(settings, "WEBAPP_SESSION_SECRET_KEY")
    else secrets.token_urlsafe(32),
    session_cookie="pmsmanagebot_session",
    max_age=86400,  # 1天过期
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中，应该设置为特定的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加 Telegram 认证中间件
app.add_middleware(TelegramAuthMiddleware)

# 注册路由
app.include_router(user_router)
app.include_router(rankings_router)


def setup_static_files():
    """配置静态文件服务"""
    static_dir = Path(settings.WEBAPP_STATIC_DIR).absolute()
    if not static_dir.exists():
        logger.warning(f"WebApp 静态文件目录不存在: {static_dir}")
        return False

    try:
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="webapp")
        return True
    except Exception as e:
        logger.error(f"挂载 WebApp 静态文件失败: {e}")
        return False
