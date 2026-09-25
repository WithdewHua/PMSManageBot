from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.log import logger
from app.utils.utils import cleanup_http_resources


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        logger.info("Application startup")
        yield
    finally:
        # 清理全局 HTTP 资源
        await cleanup_http_resources()
        logger.info("Application shutdown")
