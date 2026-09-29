"""HTTP authentication adapters for Telegram WebApp requests."""

from __future__ import annotations

import json
from functools import wraps

from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.integrations.telegram import init_data
from app.transport.http.schemas import TelegramUser


def verify_telegram_data(data: dict):
    """Validate initData using the active deployment configuration."""
    return init_data.verify_telegram_data(
        data,
        settings.TG_API_TOKEN,
        settings.WEBAPP_INIT_DATA_MAX_AGE,
    )


def mock_auth_enabled() -> bool:
    """Return whether explicitly configured local mock authentication is enabled."""
    return bool(settings.WEBAPP_DEV_MOCK_AUTH)


def get_telegram_user(request: Request) -> TelegramUser:
    """Parse the user payload already validated by the authentication middleware."""
    try:
        user_data = getattr(request.state, "telegram_data", {}).get("user")
        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="缺少 Telegram 用户数据",
            )
        return TelegramUser(**json.loads(user_data))
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"获取用户数据失败: {error!s}",
        ) from error


def require_telegram_auth(func):
    """Require Telegram authentication for a route handler."""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        request = next((arg for arg in args if isinstance(arg, Request)), None)
        if request is None:
            request = kwargs.get("request")

        if request is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="无法获取请求对象"
            )
        if not hasattr(request.state, "telegram_data"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="需要 Telegram 认证"
            )
        return await func(*args, **kwargs)

    return wrapper


def check_admin_permission(user: TelegramUser) -> bool:
    """Check whether a validated Telegram user is in the configured admin list."""
    if user.id not in settings.TG_ADMIN_CHAT_ID:
        raise HTTPException(status_code=403, detail="权限不足，需要管理员权限")
    return True
