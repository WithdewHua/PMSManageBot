from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from app.domains.crypto_donation import router as crypto_router
from app.domains.crypto_donation import service as crypto_service
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

    monkeypatch.setattr(crypto_service.upay, "UPayService", InvalidUPay)
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

    monkeypatch.setattr(crypto_service.upay, "UPayService", ValidUPay)
    monkeypatch.setattr(
        crypto_service.repository,
        "get_crypto_donation_order_by_trade_id",
        lambda _: order,
    )
    monkeypatch.setattr(crypto_service.repository, "settle_payment", complete)
    monkeypatch.setattr(crypto_service.notifications, "notify_admins", notify)

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
    committed = {
        "order": order,
        "credits_reward": 10.0,
        "new_donation": 12.0,
        "new_credits": 112.0,
    }
    settle = Mock(return_value=committed)
    notify = AsyncMock()

    class ValidUPay:
        def verify_callback_signature(self, data: dict) -> bool:
            return True

    monkeypatch.setattr(crypto_service.upay, "UPayService", ValidUPay)
    monkeypatch.setattr(
        crypto_service.repository,
        "get_crypto_donation_order_by_trade_id",
        lambda _: order,
    )
    monkeypatch.setattr(crypto_service.repository, "settle_payment", settle)
    monkeypatch.setattr(
        crypto_service.donation_service, "get_donation_multiplier", lambda: 1.0
    )
    monkeypatch.setattr(crypto_service.notifications, "notify_payment", notify)
    response = await crypto_router.upay_payment_callback(JsonRequest(payload))
    assert response.status_code == 200
    settle.assert_called_once_with(
        trade_id="trade-valid",
        callback_amount=10.004,
        actual_amount=9.5,
        block_transaction_id="tx",
        multiplier=1.0,
    )
    notify.assert_awaited_once()
    assert notify.call_args.args[1] == committed
