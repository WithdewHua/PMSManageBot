"""Tests for donation domain promotion (tasks 1.2 and 2.1).

Covers registration, query, confirmation, admin recording, bot commands,
atomic transactions, rollback on failure, event publishing, and notification decoupling.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import event
from starlette.requests import Request

from app.core import events
from app.core.db import get_session
from app.domains.credits import repository as credits_repository
from app.domains.donation import (
    admin_router,
)
from app.domains.donation import (
    exceptions as donation_exceptions,
)
from app.domains.donation import (
    notifications as donation_notifications,
)
from app.domains.donation import (
    repository as donation_repository,
)
from app.domains.donation import (
    router as donation_router,
)
from app.domains.donation.bot import set_donation
from app.domains.donation.events import DonationApproved
from app.domains.donation.models import DonationRegistrations
from app.domains.donation.schemas import (
    DonationRegistrationCreate,
    DonationRegistrationUpdate,
    PaymentMethod,
)
from app.domains.identity import repository as identity_repository
from app.domains.identity.models import Statistics
from app.transport.http.schemas import TelegramUser
from tests.conftest import next_id

ADMIN = TelegramUser(id=123456789, first_name="admin", username="admin")
USER = TelegramUser(id=1001, first_name="donor", username="donor1001")


def _assign_row_id(mapper, connection, target) -> None:
    if target.id is None:
        target.id = next_id()


event.listen(DonationRegistrations, "before_insert", _assign_row_id)


def _request() -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/api", "headers": []})
    request.state.telegram_data = {}
    return request


@pytest.fixture
def dispatched_events(monkeypatch):
    dispatched: list[events.DomainEvent] = []
    monkeypatch.setattr(events, "_dispatch", lambda items: dispatched.extend(items))
    return dispatched


@pytest.fixture
def mock_notifications(monkeypatch):
    admin_notif = AsyncMock()
    user_notif = AsyncMock()
    confirm_notif = AsyncMock()
    bot_credit_notif = AsyncMock()
    send_msg = AsyncMock()

    monkeypatch.setattr(
        donation_notifications, "notify_admins_of_registration", admin_notif
    )
    monkeypatch.setattr(
        donation_notifications, "send_donation_received_notification", user_notif
    )
    monkeypatch.setattr(
        donation_notifications, "send_confirmation_notifications", confirm_notif
    )
    monkeypatch.setattr(
        donation_notifications,
        "send_bot_donation_credit_notification",
        bot_credit_notif,
    )
    monkeypatch.setattr("app.domains.donation.bot.send_message", send_msg)

    return {
        "admin_notif": admin_notif,
        "user_notif": user_notif,
        "confirm_notif": confirm_notif,
        "bot_credit_notif": bot_credit_notif,
        "send_msg": send_msg,
    }


def _get_user_stats(tg_id: int) -> tuple[float, float]:
    with get_session() as session:
        stats = session.get(Statistics, int(tg_id))
        assert stats is not None
        return float(stats.donation or 0), float(stats.credits or 0)


# ============================================================================
# Task 1.2: Registration tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_donation_registration_normal(session_env, mock_notifications):
    """User registers a normal donation; Statistics row is ensured via identity."""
    data = DonationRegistrationCreate(
        payment_method=PaymentMethod.WECHAT,
        amount=100.0,
        note="test donation",
        is_donation_registration=False,
    )

    response = await donation_router.create_donation_registration(
        request=_request(),
        background_tasks=BackgroundTasks(),
        registration_data=data,
        user=USER,
    )

    assert response.success is True
    assert response.data.user_id == USER.id
    assert response.data.amount == 100.0
    assert response.data.payment_method == PaymentMethod.WECHAT
    assert response.data.status.value == "pending"
    assert response.data.is_donation_registration is False

    # Check Statistics was ensured
    with get_session() as session:
        stats = session.get(Statistics, USER.id)
        assert stats is not None

    mock_notifications["admin_notif"].assert_awaited_once()


@pytest.mark.asyncio
async def test_create_donation_registration_account_open(
    session_env, mock_notifications
):
    """User registers an account-opening donation."""
    data = DonationRegistrationCreate(
        payment_method=PaymentMethod.ALIPAY,
        amount=50.0,
        note="open account",
        is_donation_registration=True,
    )

    response = await donation_router.create_donation_registration(
        request=_request(),
        background_tasks=BackgroundTasks(),
        registration_data=data,
        user=USER,
    )

    assert response.success is True
    assert response.data.is_donation_registration is True


# ============================================================================
# Task 1.2: Query tests
# ============================================================================


@pytest.mark.asyncio
async def test_query_registrations(session_env):
    """Query user registrations, pending registrations, and details."""
    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, USER.id)
        reg = donation_repository.create_donation_registration_tx(
            session,
            user_id=USER.id,
            payment_method="wechat",
            amount=30.0,
            note="query test",
        )
        reg_id = int(reg.id)

    # 1. User gets own registrations
    user_list = await donation_router.get_user_donation_registrations(
        request=_request(), user=USER
    )
    assert user_list.success is True
    assert len(user_list.data) == 1
    assert user_list.data[0].id == reg_id

    # 2. Admin gets pending registrations
    pending_list = await donation_router.get_pending_donation_registrations(
        request=_request(), user=ADMIN
    )
    assert pending_list.success is True
    assert any(r.id == reg_id for r in pending_list.data)

    # 3. User views own detail
    detail = await donation_router.get_donation_registration_detail(
        registration_id=reg_id, request=_request(), user=USER
    )
    assert detail.success is True
    assert detail.data.id == reg_id

    # 4. Another non-admin user views detail -> 403 Forbidden
    other_user = TelegramUser(id=9999, first_name="other", username="other")
    with pytest.raises(HTTPException) as exc_info:
        await donation_router.get_donation_registration_detail(
            registration_id=reg_id, request=_request(), user=other_user
        )
    assert exc_info.value.status_code == 403

    # 5. Non-existent detail -> 404
    with pytest.raises(HTTPException) as exc_info:
        await donation_router.get_donation_registration_detail(
            registration_id=999999, request=_request(), user=ADMIN
        )
    assert exc_info.value.status_code == 404


# ============================================================================
# Task 1.2 & 2.1: Confirmation tests
# ============================================================================


@pytest.mark.asyncio
async def test_confirm_registration_approved_normal(
    session_env, mock_notifications, dispatched_events
):
    """Admin approves normal donation: single tx updates status, donation, credits, publishes event."""
    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, USER.id)
        reg = donation_repository.create_donation_registration_tx(
            session,
            user_id=USER.id,
            payment_method="wechat",
            amount=50.0,
            is_donation_registration=False,
        )
        reg_id = int(reg.id)

    response = await donation_router.confirm_donation_registration(
        registration_id=reg_id,
        request=_request(),
        background_tasks=BackgroundTasks(),
        confirm_data=DonationRegistrationUpdate(approved=True, admin_note="ok"),
        user=ADMIN,
    )

    assert response.success is True
    assert response.data.status.value == "approved"
    assert response.data.admin_note == "ok"

    # Multiplier is 5 by default: 50 * 5 = 250 credits
    donation_amount, credits_amount = _get_user_stats(USER.id)
    assert donation_amount == 50.0
    assert credits_amount == 250.0

    # Event DonationApproved was published post-commit exactly once
    assert len(dispatched_events) == 1
    assert isinstance(dispatched_events[0], DonationApproved)
    assert dispatched_events[0].tg_id == USER.id

    mock_notifications["confirm_notif"].assert_awaited_once()


@pytest.mark.asyncio
async def test_confirm_registration_approved_for_account(
    session_env, mock_notifications, dispatched_events, monkeypatch
):
    """Admin approves account donation: generates invite code, records donation, NO credits."""
    mock_generate_codes = MagicMock()
    monkeypatch.setattr(
        "app.domains.invitation.service.generate_codes", mock_generate_codes
    )

    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, USER.id)
        reg = donation_repository.create_donation_registration_tx(
            session,
            user_id=USER.id,
            payment_method="alipay",
            amount=50.0,
            is_donation_registration=True,
        )
        reg_id = int(reg.id)

    response = await donation_router.confirm_donation_registration(
        registration_id=reg_id,
        request=_request(),
        background_tasks=BackgroundTasks(),
        confirm_data=DonationRegistrationUpdate(approved=True),
        user=ADMIN,
    )

    assert response.success is True
    donation_amount, credits_amount = _get_user_stats(USER.id)
    assert donation_amount == 50.0
    assert credits_amount == 0.0  # Account donation does NOT give credits

    mock_generate_codes.assert_called_once_with(
        owner_tg_id=USER.id, count=1, charge=0, privileged=False
    )
    assert len(dispatched_events) == 1
    assert isinstance(dispatched_events[0], DonationApproved)


@pytest.mark.asyncio
async def test_confirm_registration_rejected(
    session_env, mock_notifications, dispatched_events
):
    """Admin rejects registration: status updated, donation & credits untouched, no badge event."""
    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, USER.id)
        reg = donation_repository.create_donation_registration_tx(
            session,
            user_id=USER.id,
            payment_method="wechat",
            amount=50.0,
        )
        reg_id = int(reg.id)

    response = await donation_router.confirm_donation_registration(
        registration_id=reg_id,
        request=_request(),
        background_tasks=BackgroundTasks(),
        confirm_data=DonationRegistrationUpdate(
            approved=False, admin_note="fake proof"
        ),
        user=ADMIN,
    )

    assert response.success is True
    assert response.data.status.value == "rejected"
    assert response.data.admin_note == "fake proof"

    donation_amount, credits_amount = _get_user_stats(USER.id)
    assert donation_amount == 0.0
    assert credits_amount == 0.0
    assert len(dispatched_events) == 0


@pytest.mark.asyncio
async def test_confirm_registration_not_pending_fails(session_env):
    """Confirming a registration that is not pending raises 400."""
    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, USER.id)
        reg = donation_repository.create_donation_registration_tx(
            session,
            user_id=USER.id,
            payment_method="wechat",
            amount=50.0,
        )
        reg_id = int(reg.id)

    # First approve succeeds
    await donation_router.confirm_donation_registration(
        registration_id=reg_id,
        request=_request(),
        background_tasks=BackgroundTasks(),
        confirm_data=DonationRegistrationUpdate(approved=True),
        user=ADMIN,
    )

    # Second approve fails with 400
    with pytest.raises(HTTPException) as exc_info:
        await donation_router.confirm_donation_registration(
            registration_id=reg_id,
            request=_request(),
            background_tasks=BackgroundTasks(),
            confirm_data=DonationRegistrationUpdate(approved=True),
            user=ADMIN,
        )
    assert exc_info.value.status_code == 400
    assert "无法处理" in exc_info.value.detail


# ============================================================================
# Task 2.1: Atomic Rollback on Failure & Concurrency
# ============================================================================


@pytest.mark.asyncio
async def test_confirm_registration_rollback_on_credit_failure(
    session_env, monkeypatch, dispatched_events
):
    """Injected credit write failure rolls back status, donation delta, and credits together."""
    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, USER.id)
        reg = donation_repository.create_donation_registration_tx(
            session,
            user_id=USER.id,
            payment_method="wechat",
            amount=50.0,
        )
        reg_id = int(reg.id)

    def fail_add_tx(*args, **kwargs):
        raise RuntimeError("injected credits failure")

    monkeypatch.setattr(credits_repository, "add_tx", fail_add_tx)

    with pytest.raises(HTTPException) as exc_info:
        await donation_router.confirm_donation_registration(
            registration_id=reg_id,
            request=_request(),
            background_tasks=BackgroundTasks(),
            confirm_data=DonationRegistrationUpdate(approved=True),
            user=ADMIN,
        )
    assert exc_info.value.status_code == 500

    # Verify rollback: status is still pending, donation is still 0, credits is still 0
    with get_session() as session:
        row = session.get(DonationRegistrations, reg_id)
        assert row.status == "pending"
        stats = session.get(Statistics, USER.id)
        assert stats.donation == 0
        assert stats.credits == 0

    assert len(dispatched_events) == 0


def test_concurrent_confirm_only_succeeds_once(session_env):
    """Atomic claim ensures only one worker can process a pending registration."""
    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, USER.id)
        reg = donation_repository.create_donation_registration_tx(
            session,
            user_id=USER.id,
            payment_method="wechat",
            amount=50.0,
        )
        reg_id = int(reg.id)

    # Worker 1 confirms
    with get_session() as session1:
        res1 = donation_repository.confirm_registration_tx(
            session1,
            registration_id=reg_id,
            admin_id=ADMIN.id,
            approved=True,
            multiplier=5,
        )
        assert res1["status"] == "approved"

    # Worker 2 attempts same confirmation
    with (
        get_session() as session2,
        pytest.raises(donation_exceptions.DonationRegistrationNotPending),
    ):
        donation_repository.confirm_registration_tx(
            session2,
            registration_id=reg_id,
            admin_id=ADMIN.id,
            approved=True,
            multiplier=5,
        )
    donation_amount, credits_amount = _get_user_stats(USER.id)
    assert donation_amount == 50.0
    assert credits_amount == 250.0


# ============================================================================
# Post-commit enrichment and notification failure tolerance
# ============================================================================


@pytest.mark.asyncio
async def test_confirm_registration_tolerates_telegram_lookup_failure_post_commit(
    session_env, monkeypatch, dispatched_events
):
    """Telegram profile lookup failure post-commit falls back to numeric name and does NOT 500."""
    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, USER.id)
        reg = donation_repository.create_donation_registration_tx(
            session,
            user_id=USER.id,
            payment_method="wechat",
            amount=40.0,
        )
        reg_id = int(reg.id)

    def fail_lookup(tg_id: int):
        raise RuntimeError("Telegram network unreachable")

    monkeypatch.setattr(
        "app.integrations.telegram.profiles.get_user_name_from_tg_id",
        fail_lookup,
    )
    mock_confirm_notif = AsyncMock()
    monkeypatch.setattr(
        donation_notifications,
        "send_confirmation_notifications",
        mock_confirm_notif,
    )

    response = await donation_router.confirm_donation_registration(
        registration_id=reg_id,
        request=_request(),
        background_tasks=BackgroundTasks(),
        confirm_data=DonationRegistrationUpdate(approved=True),
        user=ADMIN,
    )

    assert response.success is True
    # Username falls back to string numeric id
    assert response.data.username == str(USER.id)

    donation_amount, credits_amount = _get_user_stats(USER.id)
    assert donation_amount == 40.0
    assert credits_amount == 200.0

    # Event dispatched exactly once
    assert len(dispatched_events) == 1
    assert dispatched_events[0].tg_id == USER.id
    mock_confirm_notif.assert_awaited_once()


@pytest.mark.asyncio
async def test_confirm_registration_tolerates_notification_failure_post_commit(
    session_env, monkeypatch, dispatched_events
):
    """Notification failure post-commit is logged as warning and does NOT turn 200 into 500."""
    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, USER.id)
        reg = donation_repository.create_donation_registration_tx(
            session,
            user_id=USER.id,
            payment_method="wechat",
            amount=40.0,
        )
        reg_id = int(reg.id)

    async def fail_notif(*args, **kwargs):
        raise RuntimeError("Bot connection timed out")

    monkeypatch.setattr(
        donation_notifications, "send_confirmation_notifications", fail_notif
    )

    response = await donation_router.confirm_donation_registration(
        registration_id=reg_id,
        request=_request(),
        background_tasks=BackgroundTasks(),
        confirm_data=DonationRegistrationUpdate(approved=True),
        user=ADMIN,
    )

    assert response.success is True
    donation_amount, credits_amount = _get_user_stats(USER.id)
    assert donation_amount == 40.0
    assert credits_amount == 200.0
    assert len(dispatched_events) == 1


@pytest.mark.asyncio
async def test_admin_record_donation_tolerates_lookup_and_notification_failure(
    session_env, monkeypatch, dispatched_events
):
    """Admin record post-commit lookup/notification failure falls back to numeric name and succeeds."""
    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, USER.id)

    def fail_lookup(tg_id: int):
        raise RuntimeError("Telegram network down")

    async def fail_notif(*args, **kwargs):
        raise RuntimeError("Telegram notification delivery failed")

    monkeypatch.setattr(
        "app.integrations.telegram.profiles.get_user_name_from_tg_id",
        fail_lookup,
    )
    monkeypatch.setattr(
        donation_notifications,
        "send_donation_received_notification",
        fail_notif,
    )

    resp = await admin_router.submit_donation_record(
        request=_request(),
        data={"tg_id": USER.id, "amount": 75.0},
        user=ADMIN,
    )

    assert resp.success is True
    assert str(USER.id) in resp.message

    donation_amount, credits_amount = _get_user_stats(USER.id)
    assert donation_amount == 75.0
    assert credits_amount == 375.0  # 75 * 5
    assert len(dispatched_events) == 1


# ============================================================================
# Task 1.2 & 2.1: Admin record donation
# ============================================================================


@pytest.mark.asyncio
async def test_admin_record_donation(
    session_env, mock_notifications, dispatched_events
):
    """Admin records donation directly in a single transaction."""
    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, USER.id)

    resp = await admin_router.submit_donation_record(
        request=_request(),
        data={"tg_id": USER.id, "amount": 80.0, "note": "direct record"},
        user=ADMIN,
    )

    assert resp.success is True
    donation_amount, credits_amount = _get_user_stats(USER.id)
    assert donation_amount == 80.0
    assert credits_amount == 400.0  # 80 * 5

    assert len(dispatched_events) == 1
    assert isinstance(dispatched_events[0], DonationApproved)
    mock_notifications["user_notif"].assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_record_donation_user_not_found(session_env):
    """Admin record for non-existent user returns failure."""
    resp = await admin_router.submit_donation_record(
        request=_request(),
        data={"tg_id": 999999, "amount": 50.0},
        user=ADMIN,
    )
    assert resp.success is False
    assert resp.message == "用户不存在"


@pytest.mark.asyncio
async def test_admin_record_donation_rollback_on_failure(
    session_env, monkeypatch, dispatched_events
):
    """Injected failure during admin record rolls back both donation and credits."""
    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, USER.id)

    def fail_add_tx(*args, **kwargs):
        raise RuntimeError("injected credits failure")

    monkeypatch.setattr(credits_repository, "add_tx", fail_add_tx)

    resp = await admin_router.submit_donation_record(
        request=_request(),
        data={"tg_id": USER.id, "amount": 50.0},
        user=ADMIN,
    )
    assert resp.success is False
    donation_amount, credits_amount = _get_user_stats(USER.id)
    assert donation_amount == 0.0
    assert credits_amount == 0.0
    assert len(dispatched_events) == 0


# ============================================================================
# Task 1.2 & 2.1: Bot /set_donation command
# ============================================================================


@pytest.mark.asyncio
async def test_bot_set_donation_with_credits(
    session_env, mock_notifications, dispatched_events
):
    """Bot /set_donation <tg_id> <amount> adds donation and credits; DOES NOT emit badge event."""
    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, USER.id)

    update = MagicMock()
    update._effective_chat.id = ADMIN.id
    update.message.text = f"/set_donation {USER.id} 60.0"
    context = MagicMock()

    await set_donation(update, context)

    donation_amount, credits_amount = _get_user_stats(USER.id)
    assert donation_amount == 60.0
    assert credits_amount == 300.0  # 60 * 5

    # CRUCIAL: Bot manual path must NOT emit badge event
    assert len(dispatched_events) == 0

    mock_notifications["bot_credit_notif"].assert_awaited_once_with(
        tg_id=USER.id,
        delta=300.0,
        context=context,
    )


@pytest.mark.asyncio
async def test_bot_set_donation_without_credits(
    session_env, mock_notifications, dispatched_events
):
    """Bot /set_donation <tg_id> <amount> false sets donation without credits."""
    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, USER.id)

    update = MagicMock()
    update._effective_chat.id = ADMIN.id
    update.message.text = f"/set_donation {USER.id} 60.0 false"
    context = MagicMock()

    await set_donation(update, context)

    donation_amount, credits_amount = _get_user_stats(USER.id)
    assert donation_amount == 60.0
    assert credits_amount == 0.0

    assert len(dispatched_events) == 0
    mock_notifications["bot_credit_notif"].assert_not_called()


@pytest.mark.asyncio
async def test_bot_set_donation_user_not_found(session_env, mock_notifications):
    """Bot /set_donation for non-existent user reports user not found."""
    update = MagicMock()
    update._effective_chat.id = ADMIN.id
    update.message.text = "/set_donation 999999 50.0"
    context = MagicMock()

    await set_donation(update, context)

    mock_notifications["send_msg"].assert_awaited_once_with(
        chat_id=ADMIN.id,
        text="错误：用户 999999 不存在，请确认",
        context=context,
    )


@pytest.mark.asyncio
async def test_bot_set_donation_unauthorized(session_env, mock_notifications):
    """Bot /set_donation by non-admin is rejected."""
    update = MagicMock()
    update._effective_chat.id = USER.id  # Not an admin
    update.message.text = f"/set_donation {USER.id} 50.0"
    context = MagicMock()

    await set_donation(update, context)

    mock_notifications["send_msg"].assert_awaited_once_with(
        chat_id=USER.id,
        text="错误：越权操作",
        context=context,
    )


# ============================================================================
# Task 2.1: Module-level API and deletion of update_user_donation
# ============================================================================


def test_add_donation_tx_creates_statistics_if_missing(session_env):
    """add_donation_tx ensures Statistics via identity helper and returns cumulative donation."""
    with get_session() as session:
        cumulative = donation_repository.add_donation_tx(session, 8888, 25.5)
        assert cumulative == 25.5

    with get_session() as session:
        stats = session.get(Statistics, 8888)
        assert stats is not None
        assert stats.donation == 25.5

    with get_session() as session:
        cumulative2 = donation_repository.add_donation_tx(session, 8888, 10.0)
        assert cumulative2 == 35.5


def test_add_donation_tx_validates_before_rounding_and_preserves_tiny_amounts(
    session_env,
):
    """A valid tiny positive amount (e.g. 0.001) is not rejected before rounding."""
    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, 7777)

    # 1. 0.004 accumulates under frozen cumulative rounding semantics
    with get_session() as session:
        cumulative = donation_repository.add_donation_tx(session, 7777, 0.004)
        assert cumulative == 0.0  # round(0.0 + 0.004, 2) is 0.0

    with get_session() as session:
        # Add another 0.004 -> round(0.0 + 0.004, 2)
        cumulative = donation_repository.add_donation_tx(session, 7777, 0.006)
        assert cumulative == 0.01  # round(0.0 + 0.006, 2) is 0.01


def test_add_donation_tx_rollback_on_subsequent_failure(session_env):
    """add_donation_tx is undone if caller transaction fails."""
    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, 6666)

    try:
        with get_session() as session:
            donation_repository.add_donation_tx(session, 6666, 50.0)
            raise RuntimeError("caller transaction failed")
    except RuntimeError:
        pass

    with get_session() as session:
        stats = session.get(Statistics, 6666)
        assert stats.donation == 0.0


def test_add_donation_tx_rejects_non_positive_amount(session_env):
    with get_session() as session:
        with pytest.raises(ValueError, match="positive"):
            donation_repository.add_donation_tx(session, 8888, 0)
        with pytest.raises(ValueError, match="positive"):
            donation_repository.add_donation_tx(session, 8888, -10)


def test_update_user_donation_deleted_from_final_api():
    """update_user_donation is deleted in the final API."""
    assert not hasattr(donation_repository, "update_user_donation")
    assert not hasattr(donation_repository, "DonationRepository")
