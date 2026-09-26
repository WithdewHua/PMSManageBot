"""FastAPI lifespan assembly."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.http import cleanup_http_resources
from app.core.log import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        logger.info("Application startup")
        yield
    finally:
        await cleanup_http_resources()
        logger.info("Application shutdown")
