"""Security regressions for Telegram WebApp authentication and admin parsing."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
from urllib.parse import urlencode

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from app.api.lifespan import lifespan
from app.core.config import Settings, parse_admin_chat_ids, settings
from app.integrations.telegram import init_data
from app.transport.http.auth import (
    check_admin_permission,
    get_telegram_user,
    verify_telegram_data,
)
from app.transport.http.middleware import TelegramAuthMiddleware
from app.transport.http.schemas import TelegramUser
from app.transport.telegram import admin as telegram_admin

NOW = 1_700_000_000
TOKEN = "test-bot-token"
USER = {"id": 1001, "first_name": "Test", "username": "tester"}


def _signed_data(*, auth_date: int = NOW, user: dict = USER) -> dict[str, str]:
    data = {
        "auth_date": str(auth_date),
        "user": json.dumps(user, separators=(",", ":")),
    }
    check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), digestmod=hashlib.sha256).digest()
    data["hash"] = hmac.new(
        secret, check_string.encode(), digestmod=hashlib.sha256
    ).hexdigest()
    return data


def _init_data(data: dict[str, str]) -> str:
    return urlencode(data)


def _auth_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TelegramAuthMiddleware)

    @app.get("/public")
    async def public() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/protected")
    async def protected(
        request: Request,
        user: TelegramUser = Depends(get_telegram_user),
    ) -> dict[str, object]:
        return {"id": user.id, "authenticated": hasattr(request.state, "telegram_data")}

    return app


@pytest.fixture(autouse=True)
def _auth_settings(monkeypatch):
    monkeypatch.setattr(settings, "TG_API_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "WEBAPP_INIT_DATA_MAX_AGE", 86400)
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", False)
    monkeypatch.setattr(init_data, "current_time", lambda: NOW)


def test_verify_telegram_data_uses_signature_and_time_boundaries():
    valid = verify_telegram_data(_signed_data())
    assert valid.valid is True
    assert valid.reason is None

    tampered = _signed_data()
    tampered["user"] = json.dumps({**USER, "id": 2002}, separators=(",", ":"))
    assert verify_telegram_data(tampered) == (False, "invalid_signature")

    missing_hash = _signed_data()
    del missing_hash["hash"]
    assert verify_telegram_data(missing_hash) == (False, "missing_hash")

    missing_auth_date = {"user": json.dumps(USER), "hash": "not-a-real-hash"}
    assert verify_telegram_data(missing_auth_date) == (False, "missing_auth_date")

    assert verify_telegram_data(_signed_data(auth_date=NOW - 86400))
    assert verify_telegram_data(_signed_data(auth_date=NOW + 300))
    assert verify_telegram_data(_signed_data(auth_date=NOW - 86401)) == (
        False,
        "expired",
    )
    assert verify_telegram_data(_signed_data(auth_date=NOW + 301)) == (
        False,
        "future_auth_date",
    )


def test_middleware_returns_401_without_logging_init_data(caplog):
    app = _auth_app()
    marker = "sensitive-init-data-marker"
    data = _signed_data(user={**USER, "username": marker})
    data["hash"] = "invalid-signature"

    with caplog.at_level("DEBUG"):
        response = TestClient(app).get(
            "/protected", headers={"X-Telegram-Init-Data": _init_data(data)}
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "无效的 Telegram 认证数据"}
    assert marker not in caplog.text
    assert "invalid-signature" not in caplog.text


def test_middleware_rejects_mock_hash_when_disabled_and_accepts_when_enabled(
    monkeypatch,
):
    data = _signed_data()
    data["hash"] = init_data.MOCK_AUTH_HASH

    response = TestClient(_auth_app()).get(
        "/protected", headers={"X-Telegram-Init-Data": _init_data(data)}
    )
    assert response.status_code == 401

    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)
    response = TestClient(_auth_app()).get(
        "/protected", headers={"X-Telegram-Init-Data": _init_data(data)}
    )
    assert response.status_code == 200
    assert response.json() == {"id": USER["id"], "authenticated": True}


def test_public_request_without_init_data_is_unchanged():
    client = TestClient(_auth_app())
    assert client.get("/public").status_code == 200
    assert client.get("/protected").status_code == 401


def test_admin_parser_preserves_negative_ids_and_warns_for_invalid(caplog):
    with caplog.at_level("WARNING"):
        assert parse_admin_chat_ids("1001,-1002003004,abc") == [1001, -1002003004]
    assert "abc" in caplog.text
    assert parse_admin_chat_ids('["1001"]') == [1001]

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [1001])
        with pytest.raises(Exception, match="权限不足"):
            check_admin_permission(TelegramUser(id=123456789, first_name="mock"))
        assert check_admin_permission(TelegramUser(id=1001, first_name="admin")) is True
    finally:
        monkeypatch.undo()


def test_settings_defaults_and_env_parser(tmp_path, caplog):
    env_file = tmp_path / ".env"
    env_file.write_text("TG_ADMIN_CHAT_ID=1001,-1002003004,abc\n", encoding="utf-8")
    with caplog.at_level("WARNING"):
        configured = Settings(
            _env_file=None,
            DATA_DIR=str(tmp_path),
            TG_ADMIN_CHAT_ID="1001,-1002003004,abc",
        )
    assert configured.WEBAPP_DEV_MOCK_AUTH is False
    assert configured.WEBAPP_INIT_DATA_MAX_AGE == 86400
    assert configured.TG_ADMIN_CHAT_ID == [1001, -1002003004]
    assert "abc" in caplog.text


@pytest.mark.asyncio
async def test_admin_notifications_keep_negative_group_ids(monkeypatch):
    recipients = []

    async def send_message_by_url(*, chat_id, text, **kwargs):
        recipients.append((chat_id, text))
        return True

    monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [1001, -1002003004])
    monkeypatch.setattr(telegram_admin, "send_message_by_url", send_message_by_url)
    await telegram_admin.notify_admins_by_url("alert")
    assert recipients == [(1001, "alert"), (-1002003004, "alert")]


def test_session_secret_resolution_uses_config_or_ephemeral_warning(
    monkeypatch, caplog
):
    app_module = importlib.import_module("app.api.app")
    monkeypatch.setattr(app_module.settings, "SESSION_SECRET_KEY", "configured")
    assert app_module._resolve_session_secret_key() == "configured"

    monkeypatch.setattr(app_module.settings, "SESSION_SECRET_KEY", "")
    monkeypatch.setattr(app_module.secrets, "token_urlsafe", lambda _: "generated")
    with caplog.at_level("WARNING"):
        assert app_module._resolve_session_secret_key() == "generated"
    assert "SESSION_SECRET_KEY" in caplog.text


@pytest.mark.asyncio
async def test_lifespan_warns_when_mock_auth_is_enabled(monkeypatch, caplog):
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)
    with caplog.at_level("WARNING"):
        async with lifespan(FastAPI()):
            pass
    assert "WEBAPP_DEV_MOCK_AUTH" in caplog.text
