"""FastAPI lifespan assembly."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.http import cleanup_http_resources
from app.core.log import logger
from app.integrations.upay import warn_if_secret_missing


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        logger.info("Application startup")
        from app.transport.http.auth import mock_auth_enabled

        if mock_auth_enabled():
            logger.warning(
                "WEBAPP_DEV_MOCK_AUTH is enabled; Telegram authentication is being bypassed for local development"
            )
        warn_if_secret_missing()
        yield
    finally:
        await cleanup_http_resources()
        logger.info("Application shutdown")
