"""Payment claim and ledger changes share a transaction; external I/O is stubbed."""

import pytest
from sqlalchemy import select

from app.core import events
from app.core.db import get_session
from app.domains.credits import repository as credits_repository
from app.domains.crypto_donation import exceptions, repository
from app.domains.crypto_donation.models import CryptoDonationOrders
from app.domains.identity.models import Statistics


@pytest.fixture
def payment(session_env, monkeypatch):
    dispatched = []
    monkeypatch.setattr(events, "_dispatch", lambda items: dispatched.extend(items))
    with get_session() as session:
        session.add(Statistics(tg_id=42, credits=100, donation=5))
        session.flush()
        session.add(
            CryptoDonationOrders(
                id=1,
                user_id=42,
                order_id="order-1",
                trade_id="trade-1",
                crypto_type="USDT-ERC20",
                amount=10,
                status=1,
                created_at="2030-01-01T00:00:00+00:00",
            )
        )
    return dispatched


def settle():
    return repository.settle_payment(
        trade_id="trade-1",
        callback_amount=10.004,
        actual_amount=9.5,
        block_transaction_id="chain-transaction",
        multiplier=2,
    )


def state():
    with get_session() as session:
        order = session.execute(select(CryptoDonationOrders)).scalar_one()
        stats = session.get(Statistics, 42)
        return order.status, float(stats.donation), float(stats.credits)


def test_callback_duplicate_does_not_double_credit(payment):
    result = settle()
    assert result["credits_reward"] == 20
    assert result["new_donation"] == 15
    assert result["new_credits"] == 120
    assert state() == (2, 15, 120)
    assert len(payment) == 1
    assert settle() is None
    assert state() == (2, 15, 120)
    assert len(payment) == 1


def test_callback_ledger_failure_rolls_back_and_retry_succeeds(payment, monkeypatch):
    original = credits_repository.add_tx

    def fail(*args, **kwargs):
        raise RuntimeError("injected credit failure")

    monkeypatch.setattr(credits_repository, "add_tx", fail)
    with pytest.raises(RuntimeError, match="injected"):
        settle()
    assert state() == (1, 5, 100)
    assert payment == []
    monkeypatch.setattr(credits_repository, "add_tx", original)
    assert settle()["new_credits"] == 120
    assert len(payment) == 1


def test_expired_order_is_not_silently_acknowledged(payment):
    with get_session() as session:
        session.get(CryptoDonationOrders, 1).status = 3
    with pytest.raises(exceptions.PaymentStateRejected):
        settle()
    assert state() == (3, 5, 100)
    assert payment == []


def test_expiration_claim_returns_only_transitioned_orders(payment):
    with get_session() as session:
        session.get(CryptoDonationOrders, 1).expiration_time = 100
    assert len(repository.expire_orders(100)) == 1
    assert repository.expire_orders(100) == []
    assert state() == (3, 5, 100)


def test_failed_order_cleanup_never_deletes_a_paid_receipt(payment):
    settle()
    assert repository.delete_unpaid_order("order-1") is False
    assert state() == (2, 15, 120)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_result, writeback", [(None, True), ({"trade_id": "t"}, False)]
)
async def test_order_creation_failure_removes_local_order(
    monkeypatch, provider_result, writeback
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from app.domains.crypto_donation import service
    from app.domains.crypto_donation.types import NewOrder

    provider = SimpleNamespace(
        generate_order_id=lambda: "new-order",
        create_order=AsyncMock(return_value=provider_result),
    )
    monkeypatch.setattr(service, "_is_bound", lambda _: True)
    monkeypatch.setattr(service.upay, "UPayService", lambda: provider)
    monkeypatch.setattr(service.upay, "upay_secret_configured", lambda: True)
    monkeypatch.setattr(repository, "create_crypto_donation_order", lambda **kw: True)
    monkeypatch.setattr(
        repository, "update_crypto_donation_order_upay_info", lambda **kw: writeback
    )
    cleanup = Mock(return_value=True)
    monkeypatch.setattr(repository, "delete_unpaid_order", cleanup)
    order = NewOrder(crypto_type="USDT", amount=10.0, note=None)
    with pytest.raises(exceptions.CryptoDonationError) as rejection:
        await service.create_order(42, order)
    assert rejection.value.status_code == 500
    assert str(rejection.value) == "创建支付订单失败，请稍后重试"
    cleanup.assert_called_once_with("new-order")


@pytest.mark.asyncio
async def test_callback_ledger_failure_returns_non_ok_and_allows_retry(
    payment, monkeypatch
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.domains.crypto_donation import router, service

    payload = {
        "trade_id": "trade-1",
        "order_id": "order-1",
        "amount": 10,
        "actual_amount": 9.5,
        "status": 2,
        "block_transaction_id": "tx",
        "signature": "signature",
        "token": "payment-address",
    }
    monkeypatch.setattr(
        service.upay,
        "UPayService",
        lambda: SimpleNamespace(verify_callback_signature=lambda _: True),
    )
    monkeypatch.setattr(service.notifications, "notify_payment", AsyncMock())
    monkeypatch.setattr(service.donation_service, "get_donation_multiplier", lambda: 2)
    original = credits_repository.add_tx

    def fail(*args, **kwargs):
        raise RuntimeError("injected")

    monkeypatch.setattr(credits_repository, "add_tx", fail)
    request = SimpleNamespace(json=AsyncMock(return_value=payload))
    response = await router.upay_payment_callback(request)
    assert response.status_code == 500
    assert state() == (1, 5, 100)
    monkeypatch.setattr(credits_repository, "add_tx", original)
    response = await router.upay_payment_callback(request)
    assert response.status_code == 200 and response.body == b"ok"
    assert state() == (2, 15, 120)


def test_order_lists_preserve_user_isolation_pagination_and_status(payment):
    from app.domains.crypto_donation import service

    with get_session() as session:
        session.add(Statistics(tg_id=50, donation=0, credits=0))
        session.add_all(
            [
                CryptoDonationOrders(
                    id=2,
                    user_id=50,
                    order_id="foreign",
                    trade_id="foreign",
                    crypto_type="USDT",
                    amount=10,
                    status=1,
                    created_at="2030-01-03",
                ),
                CryptoDonationOrders(
                    id=3,
                    user_id=42,
                    order_id="paid",
                    trade_id="paid",
                    crypto_type="USDT",
                    amount=10,
                    status=2,
                    created_at="2030-01-02",
                ),
            ]
        )
        session.get(CryptoDonationOrders, 1).created_at = "2030-01-01"
    # The former leftover `self` shifted user_id to limit=50, leaking that user's orders.
    assert [row["order_id"] for row in service.get_user_orders(42, 50)] == [
        "paid",
        "order-1",
    ]
    assert [row["order_id"] for row in service.get_user_orders(50, 1)] == ["foreign"]
    assert [row["order_id"] for row in service.get_all_orders(1, 1, "1")] == ["order-1"]
    assert [row["order_id"] for row in service.get_all_orders(20, 0, "2")] == ["paid"]
