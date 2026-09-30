from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.domains.crypto_donation import router as crypto_router
from app.integrations import upay


class JsonRequest:
    def __init__(self, payload: dict):
        self.payload = payload

    async def json(self) -> dict:
        return self.payload


@pytest.fixture
def upay_secret(monkeypatch):
    monkeypatch.setattr(upay.settings, "UPAY_SECRET_KEY", "test-secret")
    return "test-secret"


def test_upay_signature_logging_never_contains_secret_or_signature(upay_secret, caplog):
    service = upay.UPayService()
    params = {"type": "USDT-ERC20", "order_id": "order-1", "amount": 10.0}

    with caplog.at_level("INFO"):
        signature = service.generate_signature(params)

    assert signature
    assert upay_secret not in caplog.text
    assert signature not in caplog.text


def test_upay_callback_signature_uses_constant_time_compare(monkeypatch, upay_secret):
    service = upay.UPayService()
    params = {"trade_id": "trade-1", "amount": "10", "actual_amount": "9.5"}
    signature = service.generate_signature(params)
    calls: list[tuple[str, str]] = []

    def compare_digest(received: str, expected: str) -> bool:
        calls.append((received, expected))
        return received == expected

    monkeypatch.setattr(upay.hmac, "compare_digest", compare_digest)

    assert service.verify_callback_signature({**params, "signature": signature})
    assert calls == [(signature, signature)]


@pytest.mark.asyncio
async def test_missing_upay_secret_rejects_order_and_callback(monkeypatch):
    monkeypatch.setattr(upay.settings, "UPAY_SECRET_KEY", "")
    service = upay.UPayService()

    assert await service.create_order("USDT-ERC20", 10.0) is None
    assert not service.verify_callback_signature({"signature": "known"})


def test_missing_upay_secret_logs_startup_warning(monkeypatch, caplog):
    monkeypatch.setattr(upay.settings, "UPAY_SECRET_KEY", "")

    with caplog.at_level("WARNING"):
        upay.warn_if_secret_missing()

    assert "UPAY_SECRET_KEY is not configured" in caplog.text


@pytest.mark.asyncio
async def test_callback_logs_no_payload_or_signature(monkeypatch, caplog):
    payload = {
        "trade_id": "trade-log-check",
        "order_id": "order-log-check",
        "amount": 10.0,
        "actual_amount": 9.5,
        "token": "wallet",
        "status": 2,
        "signature": "sensitive-signature-marker",
    }

    class InvalidUPay:
        def verify_callback_signature(self, data: dict) -> bool:
            return False

    monkeypatch.setattr(crypto_router, "UPayService", InvalidUPay)
    with caplog.at_level("INFO"):
        response = await crypto_router.upay_payment_callback(JsonRequest(payload))

    assert response.status_code == 400
    assert "sensitive-signature-marker" not in caplog.text
    assert "token" not in caplog.text


@pytest.mark.asyncio
async def test_callback_amount_mismatch_does_not_complete_order(monkeypatch):
    payload = {
        "trade_id": "trade-mismatch",
        "order_id": "order-mismatch",
        "amount": 11.0,
        "actual_amount": 9.5,
        "token": "wallet",
        "block_transaction_id": "tx",
        "status": 2,
        "signature": "signature",
    }
    order = {"order_id": "order-mismatch", "trade_id": "trade-mismatch", "amount": 10.0}
    complete = AsyncMock()
    notify = AsyncMock()

    class ValidUPay:
        def verify_callback_signature(self, data: dict) -> bool:
            return True

    monkeypatch.setattr(crypto_router, "UPayService", ValidUPay)
    monkeypatch.setattr(
        crypto_router.db, "get_crypto_donation_order_by_trade_id", lambda _: order
    )
    monkeypatch.setattr(crypto_router.db, "complete_crypto_donation_order", complete)
    monkeypatch.setattr(crypto_router, "_notify_upay_admins", notify)

    response = await crypto_router.upay_payment_callback(JsonRequest(payload))

    assert response.status_code == 400
    assert response.body == b'{"error":"amount mismatch"}'
    complete.assert_not_awaited()
    notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_callback_credits_local_order_amount(monkeypatch):
    payload = {
        "trade_id": "trade-valid",
        "order_id": "order-valid",
        "amount": 10.004,
        "actual_amount": 9.5,
        "token": "wallet",
        "block_transaction_id": "tx",
        "status": 2,
        "signature": "signature",
    }
    order = {
        "order_id": "order-valid",
        "trade_id": "trade-valid",
        "amount": 10.0,
        "user_id": 7,
        "status": 1,
        "crypto_type": "USDT-ERC20",
    }
    update_donation = Mock()
    add_credits = Mock(return_value=SimpleNamespace(after=112.0))

    class ValidUPay:
        def verify_callback_signature(self, data: dict) -> bool:
            return True

    monkeypatch.setattr(crypto_router, "UPayService", ValidUPay)
    monkeypatch.setattr(
        crypto_router.db, "get_crypto_donation_order_by_trade_id", lambda _: order
    )
    monkeypatch.setattr(
        crypto_router.db, "complete_crypto_donation_order", lambda **_: True
    )
    monkeypatch.setattr(
        crypto_router.db, "get_stats_by_tg_id", lambda _: (7, 2.0, 102.0)
    )
    monkeypatch.setattr(crypto_router.db, "update_user_donation", update_donation)
    monkeypatch.setattr(crypto_router.credits_service, "add", add_credits)
    monkeypatch.setattr(
        crypto_router.donation_service, "get_donation_multiplier", lambda: 1.0
    )
    monkeypatch.setattr(crypto_router, "get_user_name_from_tg_id", lambda _: "user")
    monkeypatch.setattr(crypto_router, "send_message_by_url", AsyncMock())
    from app.core import events

    emit = Mock()
    monkeypatch.setattr(events, "emit", emit)

    response = await crypto_router.upay_payment_callback(JsonRequest(payload))

    assert response.status_code == 200
    update_donation.assert_called_once_with(12.0, 7)
    add_credits.assert_called_once()
    assert add_credits.call_args.args[1] == 10.0
    assert emit.call_count == 1
    assert emit.call_args.args[0].tg_id == 7
