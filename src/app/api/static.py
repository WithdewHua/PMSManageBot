"""Static WebApp file mounting."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.log import logger


def setup_static_files(app: FastAPI) -> bool:
    """Mount profile pictures and the compiled WebApp on *app*."""
    static_dir = Path(settings.WEBAPP_STATIC_DIR).absolute()
    if not static_dir.exists():
        logger.warning(f"WebApp 静态文件目录不存在: {static_dir}")
        return False

    try:
        app.mount(
            "/pics",
            StaticFiles(directory=str(settings.TG_USER_PROFILE_CACHE_PATH.absolute())),
            name="pics",
        )
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="webapp")
        return True
    except Exception as e:
        logger.error(f"挂载 WebApp 静态文件失败: {e}")
        return False
