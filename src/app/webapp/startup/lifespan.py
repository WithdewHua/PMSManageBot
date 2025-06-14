from contextlib import asynccontextmanager

from app.log import logger
from app.utils import cleanup_http_resources
from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        logger.info("Application startup")
        yield
    finally:
        # 清理全局 HTTP 资源
        await cleanup_http_resources()
        logger.info("Application shutdown")
