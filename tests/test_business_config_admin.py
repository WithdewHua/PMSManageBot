from __future__ import annotations

import pytest
from starlette.requests import Request

from app.domains.crypto_donation import admin_router as crypto_admin
from app.domains.donation import admin_router as donation_admin
from app.domains.media_access import admin_router as media_admin
from app.domains.premium import admin_router as premium_admin
from app.domains.vaultwarden import admin_router as vault_admin
from app.transport.http.schemas import TelegramUser


def _request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/admin/settings",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
            "client": ("test", 1),
        }
    )
    request.state.telegram_data = {"id": 123456789}
    return request


CASES = (
    (premium_admin.set_credits_cost_per_10gb, "credits", 7, True),
    (media_admin.set_nsfw_libs, "libs", ["Private"], [""]),
    (donation_admin.set_donation_multiplier, "multiplier", 7, True),
    (crypto_admin.set_upay_crypto_types, "crypto_types", ["USDT-BSC"], [""]),
    (vault_admin.set_vaultwarden_enabled, "enabled", True, "yes"),
    (vault_admin.set_vaultwarden_redeem_credits, "credits", 700, True),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("handler,key,value,invalid", CASES)
async def test_business_config_admin_endpoints_validate_and_succeed(
    monkeypatch, handler, key, value, invalid
) -> None:
    calls = []
    target = handler.__module__
    module = __import__(target, fromlist=["*"])
    setter_names = {
        "set_credits_cost_per_10gb": "set_credits_cost_per_10gb",
        "set_nsfw_libs": "set_nsfw_libs",
        "set_donation_multiplier": "set_donation_multiplier",
        "set_upay_crypto_types": "set_supported_crypto_types",
        "set_vaultwarden_enabled": "set_enabled",
        "set_vaultwarden_redeem_credits": "set_redeem_credits",
    }
    service = next(
        value
        for name, value in vars(module).items()
        if name.endswith("_service") and hasattr(value, setter_names[handler.__name__])
    )
    setter = setter_names[handler.__name__]
    getter_names = {
        "set_credits_cost_per_10gb": "get_credits_cost_per_10gb",
        "set_nsfw_libs": "get_nsfw_libs",
        "set_donation_multiplier": "get_donation_multiplier",
        "set_upay_crypto_types": "get_supported_crypto_types",
        "set_vaultwarden_enabled": "is_enabled",
        "set_vaultwarden_redeem_credits": "get_redeem_credits",
    }
    monkeypatch.setattr(service, setter, lambda value: calls.append(value))
    monkeypatch.setattr(
        service,
        getter_names[handler.__name__],
        lambda: value,
    )

    success = await handler.__wrapped__(
        request=_request(),
        data={key: value},
        user=TelegramUser(id=123456789, first_name="Admin"),
    )
    assert success.success is True
    assert calls == [value]

    invalid_response = await handler.__wrapped__(
        request=_request(),
        data={key: invalid},
        user=TelegramUser(id=123456789, first_name="Admin"),
    )
    assert invalid_response.success is False

    def fail(_value):
        raise RuntimeError("write failed")

    monkeypatch.setattr(service, setter, fail)
    failed = await handler.__wrapped__(
        request=_request(),
        data={key: value},
        user=TelegramUser(id=123456789, first_name="Admin"),
    )
    assert failed.success is False
