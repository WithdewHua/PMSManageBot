"""HTTP middleware for Telegram WebApp authentication."""

from __future__ import annotations

import json
import urllib.parse

from fastapi import Request
from fastapi.security import HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.log import logger
from app.integrations.telegram import init_data
from app.transport.http import auth as http_auth

security = HTTPBearer()


def _user_id_for_log(data: dict) -> int | None:
    try:
        user = json.loads(data.get("user", "{}"))
        return int(user["id"]) if user.get("id") is not None else None
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None


def _auth_failure_response(detail: str) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": detail})


class TelegramAuthMiddleware(BaseHTTPMiddleware):
    """Validate Telegram initData without leaking authentication material."""

    async def dispatch(self, request: Request, call_next):
        init_data_header = request.headers.get("X-Telegram-Init-Data")
        if not init_data_header:
            return await call_next(request)

        try:
            data_dict = dict(
                urllib.parse.parse_qsl(init_data_header, keep_blank_values=True)
            )
        except (TypeError, ValueError) as error:
            logger.warning(
                "Unable to parse Telegram initData: %s", type(error).__name__
            )
            return _auth_failure_response("无法处理 Telegram 认证数据")

        if (
            data_dict.get("hash") == init_data.MOCK_AUTH_HASH
            and http_auth.mock_auth_enabled()
        ):
            logger.warning(
                "Telegram mock authentication accepted for user_id=%s",
                _user_id_for_log(data_dict),
            )
            request.state.telegram_data = data_dict
            return await call_next(request)

        result = init_data.verify_telegram_data(
            data_dict,
            settings.TG_API_TOKEN,
            settings.WEBAPP_INIT_DATA_MAX_AGE,
        )
        if not result:
            reason = result.reason
            user_id = _user_id_for_log(data_dict)
            if reason == "expired":
                detail = "Telegram 认证数据已过期，请重新打开应用"
            else:
                detail = "无效的 Telegram 认证数据"
            logger.warning(
                "Telegram authentication failed: reason=%s auth_date=%s user_id=%s",
                reason,
                data_dict.get("auth_date"),
                user_id,
            )
            return _auth_failure_response(detail)

        request.state.telegram_data = data_dict
        return await call_next(request)
