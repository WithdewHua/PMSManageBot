"""Tests for Vaultwarden domain promotion (tasks 1.3 and 2.3).

Freezes behavior baseline (1.3) and verifies promoted architecture (2.3):
- Repository exclusively owns SQL
- Service orchestrates debit -> external account creation (asyncio.to_thread) -> record
- Compensating credit refund on account creation failure or constructor exception
- Error logging and admin notification when refund fails
- Robust username enrichment fallbacks on notification paths
- Isolated notification dispatch so notifier errors do not turn paid success into 500
- Report capability for redemption counts
- Exact declared HTTP contracts preserved
"""

from __future__ import annotations

import ast
import json
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.api.app import app
from app.core.config import settings
from app.core.db import get_session
from app.domains.credits import service as credits_service
from app.domains.identity.models import Statistics
from app.domains.vaultwarden import (
    notifications as vw_notifications,
)
from app.domains.vaultwarden import (
    repository as vw_repository,
)
from app.domains.vaultwarden import (
    service as vw_service,
)
from app.domains.vaultwarden.config import VAULTWARDEN_CONFIG
from app.domains.vaultwarden.models import VaultwardenRedeemRecords
from app.integrations.telegram import profiles as telegram_profiles
from app.integrations.telegram.init_data import MOCK_AUTH_HASH
from tests.conftest import next_id


def _assign_row_id(mapper, connection, target) -> None:
    if target.id is None:
        target.id = next_id()


@pytest.fixture(autouse=True)
def assign_vaultwarden_row_id():
    """Assign synthetic BIGINT primary keys for SQLite without schema alteration."""
    event.listen(VaultwardenRedeemRecords, "before_insert", _assign_row_id)
    yield
    event.remove(VaultwardenRedeemRecords, "before_insert", _assign_row_id)


@pytest.fixture
def mock_external_io(monkeypatch):
    """Mock all external network side effects (Telegram and Vaultwarden API)."""
    dispatched_messages = []

    async def fake_send_message_by_url(chat_id, text, parse_mode="HTML", **kwargs):
        dispatched_messages.append(
            {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        )
        return True

    monkeypatch.setattr(
        vw_notifications, "send_message_by_url", fake_send_message_by_url
    )
    return dispatched_messages


@pytest.fixture
def enable_vaultwarden():
    """Temporarily enable Vaultwarden redemption with 500 credits requirement."""
    VAULTWARDEN_CONFIG.invalidate()
    VAULTWARDEN_CONFIG.update(enabled=True, redeem_credits=500)
    yield
    VAULTWARDEN_CONFIG.invalidate()


@pytest.fixture
def disable_vaultwarden():
    """Temporarily disable Vaultwarden redemption."""
    VAULTWARDEN_CONFIG.invalidate()
    VAULTWARDEN_CONFIG.update(enabled=False, redeem_credits=500)
    yield
    VAULTWARDEN_CONFIG.invalidate()


def _seed_user(tg_id: int, credits: float = 1000.0, donation: float = 0.0) -> None:
    """Seed user statistics row in test database."""
    with get_session() as session:
        session.add(Statistics(tg_id=tg_id, credits=credits, donation=donation))
        session.commit()


def _get_user_credits(tg_id: int) -> float:
    """Read user credits from database."""
    with get_session() as session:
        stat = session.get(Statistics, tg_id)
        return float(stat.credits) if stat else 0.0


def _make_auth_client(tg_id: int = 42) -> TestClient:
    """Create TestClient with mock telegram authentication header."""
    user_payload = {"id": tg_id, "first_name": "TestUser", "username": "testuser"}
    init_data = (
        f"user={urllib.parse.quote(json.dumps(user_payload))}&hash={MOCK_AUTH_HASH}"
    )
    client = TestClient(app)
    client.headers.update({"X-Telegram-Init-Data": init_data})
    return client


# ============================================================================
# 1. Behavior Freeze Tests (Task 1.3): GET /api/vaultwarden/redeem-info
# ============================================================================


def test_redeem_info_when_disabled(session_env, disable_vaultwarden, monkeypatch):
    """When disabled, redeem-info returns 200 with enabled=False and error message."""
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)
    client = _make_auth_client(tg_id=42)

    response = client.get("/api/vaultwarden/redeem-info")
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False
    assert data["required_credits"] == 500
    assert data["current_credits"] == 0.0
    assert data["can_redeem"] is False
    assert data["error_message"] == "Vaultwarden 兑换功能未启用"


def test_redeem_info_user_not_bound(session_env, enable_vaultwarden, monkeypatch):
    """When user has no Plex/Emby bound (no statistics row), return 404."""
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)
    client = _make_auth_client(tg_id=999)  # User does not exist

    response = client.get("/api/vaultwarden/redeem-info")
    assert response.status_code == 404
    assert response.json()["detail"] == "用户未绑定 Plex/Emby 账户"


def test_redeem_info_insufficient_credits(session_env, enable_vaultwarden, monkeypatch):
    """When user credits < required_credits, return can_redeem=False with message."""
    _seed_user(tg_id=42, credits=200.0)
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)
    client = _make_auth_client(tg_id=42)

    response = client.get("/api/vaultwarden/redeem-info")
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    assert data["required_credits"] == 500
    assert data["current_credits"] == 200.0
    assert data["can_redeem"] is False
    assert data["error_message"] == "积分不足，无法兑换 Vaultwarden 账户"


def test_redeem_info_can_redeem(session_env, enable_vaultwarden, monkeypatch):
    """When user credits >= required_credits, return can_redeem=True."""
    _seed_user(tg_id=42, credits=1000.0)
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)
    client = _make_auth_client(tg_id=42)

    response = client.get("/api/vaultwarden/redeem-info")
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    assert data["required_credits"] == 500
    assert data["current_credits"] == 1000.0
    assert data["can_redeem"] is True
    assert data["error_message"] is None


# ============================================================================
# 2. Behavior Freeze Tests (Task 1.3): POST /api/vaultwarden/redeem Rejections
# ============================================================================


def test_redeem_when_disabled(session_env, disable_vaultwarden, monkeypatch):
    """When disabled, redeem returns 200 with success=False."""
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)
    client = _make_auth_client(tg_id=42)

    response = client.post(
        "/api/vaultwarden/redeem", json={"email": "user@example.com"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["message"] == "Vaultwarden 兑换功能未启用"


def test_redeem_user_not_bound(session_env, enable_vaultwarden, monkeypatch):
    """When user not bound, redeem returns 404."""
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)
    client = _make_auth_client(tg_id=999)

    response = client.post(
        "/api/vaultwarden/redeem", json={"email": "user@example.com"}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "用户未绑定 Plex/Emby 账户"


def test_redeem_insufficient_credits(session_env, enable_vaultwarden, monkeypatch):
    """When credits are insufficient, return failure with exact balance prompt."""
    _seed_user(tg_id=42, credits=150.0)
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)
    client = _make_auth_client(tg_id=42)

    response = client.post(
        "/api/vaultwarden/redeem", json={"email": "user@example.com"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert (
        "积分不足，您当前积分 150.0，需要 500 积分才能兑换 Vaultwarden 账户"
        in data["message"]
    )
    # Balance must remain unchanged
    assert _get_user_credits(42) == 150.0
    assert vw_repository.count_redemptions() == 0


@pytest.mark.asyncio
async def test_redeem_invalid_email(session_env, enable_vaultwarden):
    """Invalid email string is rejected before balance deduction."""
    _seed_user(tg_id=42, credits=1000.0)
    result = await vw_service.redeem(tg_id=42, email="notanemail")
    assert result.success is False
    assert result.message == "请输入有效的邮箱地址"
    assert _get_user_credits(42) == 1000.0


# ============================================================================
# 3. Promotion Workflow Tests (Task 2.3): Debit -> External Creation -> Record
# ============================================================================


@pytest.mark.asyncio
async def test_redeem_success_workflow(
    session_env, enable_vaultwarden, mock_external_io, monkeypatch
):
    """Successful redemption:
    1. Debits credits (1000 -> 500)
    2. Calls external invite_user via asyncio.to_thread
    3. Records redemption in repository
    4. Dispatches admin notification
    5. Returns success response with deduction and remaining credits
    """
    _seed_user(tg_id=42, credits=1000.0)
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)

    fake_vw = MagicMock()
    fake_vw.invite_user.return_value = True

    result = await vw_service.redeem(
        tg_id=42,
        email="test@example.com",
        vaultwarden_client=fake_vw,
    )

    assert result.success is True
    assert "兑换成功！邀请邮件已发送至 test@example.com" in result.message
    assert result.credits_deducted == 500.0
    assert result.remaining_credits == 500.0

    # Verify balance was debited
    assert _get_user_credits(42) == 500.0

    # Verify invite_user was called with correct email
    fake_vw.invite_user.assert_called_once_with("test@example.com")

    # Verify redemption record was persisted in database
    records = vw_repository.list_records_by_tg_id(42)
    assert len(records) == 1
    assert records[0].email == "test@example.com"
    assert records[0].credits_cost == 500.0
    assert vw_repository.count_redemptions() == 1

    # Verify admin notification was sent
    assert len(mock_external_io) >= 1
    notification_text = mock_external_io[0]["text"]
    assert "Vaultwarden 兑换通知" in notification_text
    assert "test@example.com" in notification_text
    assert "500" in notification_text


@pytest.mark.asyncio
async def test_redeem_external_failure_compensating_refund(
    session_env, enable_vaultwarden, mock_external_io, monkeypatch
):
    """When external account creation fails:
    1. Credits are initially debited
    2. Account creation fails (invite_user returns False)
    3. Compensating refund is executed (credits restored to original)
    4. Returns failure message
    5. No redemption record is created
    """
    _seed_user(tg_id=42, credits=1000.0)
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)

    fake_vw = MagicMock()
    fake_vw.invite_user.return_value = False  # Creation fails

    result = await vw_service.redeem(
        tg_id=42,
        email="failed@example.com",
        vaultwarden_client=fake_vw,
    )

    assert result.success is False
    assert "发送邀请失败，邮箱可能已被注册或服务出现错误" in result.message

    # Verify credits were restored via compensating refund
    assert _get_user_credits(42) == 1000.0

    # Verify NO redemption record was created
    assert vw_repository.count_redemptions() == 0

    # Verify NO notification was queued
    assert len(mock_external_io) == 0


@pytest.mark.asyncio
async def test_redeem_constructor_failure_compensating_refund(
    session_env, enable_vaultwarden, mock_external_io, monkeypatch
):
    """When Vaultwarden constructor raises an exception after debit:
    1. Debit executes first
    2. Client constructor raises
    3. Compensating refund restores balance
    4. User receives friendly error message
    """
    _seed_user(tg_id=42, credits=1000.0)
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)

    def failing_constructor():
        raise RuntimeError("failed to initialize client connection")

    result = await vw_service.redeem(
        tg_id=42,
        email="ctor_fail@example.com",
        vaultwarden_client=failing_constructor,
    )

    assert result.success is False
    assert "发送邀请失败，邮箱可能已被注册或服务出现错误" in result.message
    # Verify balance restored
    assert _get_user_credits(42) == 1000.0
    assert vw_repository.count_redemptions() == 0


@pytest.mark.asyncio
async def test_redeem_refund_failure_logs_and_notifies_admin(
    session_env, enable_vaultwarden, mock_external_io, monkeypatch
):
    """When external account creation fails AND compensating refund also fails:
    1. invite_user fails
    2. credits_service.add raises an exception
    3. logger.error is called
    4. Admin warning notification is dispatched
    5. User receives failure message
    """
    _seed_user(tg_id=42, credits=1000.0)
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)

    fake_vw = MagicMock()
    fake_vw.invite_user.return_value = False

    # Force refund to fail
    def fail_add(*args, **kwargs):
        raise RuntimeError("database error during refund")

    monkeypatch.setattr(credits_service, "add", fail_add)

    with patch.object(vw_service.logger, "error") as mock_logger_error:
        result = await vw_service.redeem(
            tg_id=42,
            email="disaster@example.com",
            vaultwarden_client=fake_vw,
        )

        assert result.success is False
        assert "发送邀请失败，邮箱可能已被注册或服务出现错误" in result.message

        # Verify error was logged
        mock_logger_error.assert_called()
        log_messages = [str(call) for call in mock_logger_error.call_args_list]
        assert any("Vaultwarden 开号失败后退还积分失败" in msg for msg in log_messages)

    # Verify admin notification about refund failure was sent
    assert len(mock_external_io) >= 1
    admin_alert = mock_external_io[0]["text"]
    assert "Vaultwarden 积分退还失败警告" in admin_alert
    assert "disaster@example.com" in admin_alert
    assert "42" in admin_alert


@pytest.mark.asyncio
async def test_redeem_refund_failure_with_profile_lookup_and_notifier_exceptions(
    session_env, enable_vaultwarden, monkeypatch
):
    """Username enrichment failure falls back to str(tg_id) and notifier errors are isolated."""
    _seed_user(tg_id=42, credits=1000.0)

    fake_vw = MagicMock()
    fake_vw.invite_user.return_value = False

    # Force refund failure
    monkeypatch.setattr(
        credits_service, "add", MagicMock(side_effect=RuntimeError("refund down"))
    )

    # Force username enrichment failure
    monkeypatch.setattr(
        telegram_profiles,
        "get_user_name_from_tg_id",
        MagicMock(side_effect=RuntimeError("cache disk error")),
    )

    # Force admin notifier failure
    notifier_called = []

    async def failing_notify(**kwargs):
        notifier_called.append(kwargs)
        raise RuntimeError("telegram network timeout")

    monkeypatch.setattr(
        vw_notifications, "notify_admins_vaultwarden_refund_failed", failing_notify
    )

    # Must complete safely without raising
    result = await vw_service.redeem(
        tg_id=42,
        email="fallback@example.com",
        vaultwarden_client=fake_vw,
    )
    assert result.success is False
    assert len(notifier_called) == 1
    # Fallback to string of tg_id
    assert notifier_called[0]["user_name"] == "42"


@pytest.mark.asyncio
async def test_redeem_success_with_profile_and_notifier_failures(
    session_env, enable_vaultwarden, monkeypatch
):
    """Profile lookup failure or notifier error after commit must NEVER turn success into 500."""
    _seed_user(tg_id=42, credits=1000.0)

    fake_vw = MagicMock()
    fake_vw.invite_user.return_value = True

    # Force username lookup to throw
    monkeypatch.setattr(
        telegram_profiles,
        "get_user_name_from_tg_id",
        MagicMock(side_effect=RuntimeError("profile db down")),
    )

    # Force admin notification to throw
    async def failing_notify(**kwargs):
        raise RuntimeError("telegram API error")

    monkeypatch.setattr(
        vw_notifications, "notify_admins_vaultwarden_redeem", failing_notify
    )

    result = await vw_service.redeem(
        tg_id=42,
        email="robust@example.com",
        vaultwarden_client=fake_vw,
    )

    # Paid success remains intact!
    assert result.success is True
    assert "兑换成功！" in result.message
    assert result.credits_deducted == 500.0
    assert result.remaining_credits == 500.0
    assert _get_user_credits(42) == 500.0
    assert vw_repository.count_redemptions() == 1


# ============================================================================
# 4. Reports Capability and Repository Exclusivity Tests
# ============================================================================


def test_reports_redemption_count_capability(session_env):
    """Verify service exposes count_redemptions for reports consumption."""
    assert vw_service.count_redemptions() == 0

    # Add redemptions via repository
    _seed_user(tg_id=1, credits=1000.0)
    _seed_user(tg_id=2, credits=1000.0)

    vw_repository.record_redemption(tg_id=1, email="u1@example.com", credits_cost=500.0)
    vw_repository.record_redemption(tg_id=2, email="u2@example.com", credits_cost=500.0)

    assert vw_service.count_redemptions() == 2


def test_repository_caller_owned_tx(session_env):
    """Verify repository functions support caller-owned transactions."""
    _seed_user(tg_id=10, credits=1000.0)

    with get_session() as session:
        record = vw_repository.record_redemption_tx(
            session,
            tg_id=10,
            email="tx@example.com",
            credits_cost=500.0,
            redeem_date="2026-10-01 12:00:00",
            created_at=1790856000,
        )
        assert record.id is None
        session.commit()

    assert vw_repository.count_redemptions() == 1
    records = vw_repository.list_records_by_tg_id(10)
    assert len(records) == 1
    assert records[0].email == "tx@example.com"


def test_router_and_service_have_no_direct_sql_boundary():
    """Verify router and service do not import get_session or write SQL."""
    router_file = Path("src/app/domains/vaultwarden/router.py").read_text(
        encoding="utf-8"
    )
    service_file = Path("src/app/domains/vaultwarden/service.py").read_text(
        encoding="utf-8"
    )

    router_tree = ast.parse(router_file)
    service_tree = ast.parse(service_file)

    for tree, name in [(router_tree, "router.py"), (service_tree, "service.py")]:
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "app.core.db" or "get_session" not in [
                    alias.name for alias in node.names
                ], f"{name} must not import get_session"
                assert node.module != "sqlalchemy", f"{name} must not import sqlalchemy"


def test_redeem_via_test_client_success(
    session_env, enable_vaultwarden, mock_external_io, monkeypatch
):
    """End-to-end TestClient verification of successful redemption."""
    _seed_user(tg_id=42, credits=1000.0)
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)

    with patch(
        "app.integrations.vaultwarden.Vaultwarden.invite_user", return_value=True
    ):
        client = _make_auth_client(tg_id=42)
        response = client.post(
            "/api/vaultwarden/redeem", json={"email": "client_success@example.com"}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "兑换成功！" in data["message"]
    assert data["credits_deducted"] == 500.0
    assert data["remaining_credits"] == 500.0
    assert _get_user_credits(42) == 500.0
    assert vw_repository.count_redemptions() == 1


def test_redeem_via_test_client_creation_failure(
    session_env, enable_vaultwarden, mock_external_io, monkeypatch
):
    """End-to-end TestClient verification of creation failure and refund."""
    _seed_user(tg_id=42, credits=1000.0)
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)

    with patch(
        "app.integrations.vaultwarden.Vaultwarden.invite_user", return_value=False
    ):
        client = _make_auth_client(tg_id=42)
        response = client.post(
            "/api/vaultwarden/redeem", json={"email": "client_fail@example.com"}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "发送邀请失败" in data["message"]
    # Compensating refund restored balance
    assert _get_user_credits(42) == 1000.0
    assert vw_repository.count_redemptions() == 0


def test_admin_settings_endpoints(session_env, monkeypatch):
    """Verify admin endpoints for setting enabled and redeem credits."""
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)
    monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [42])
    client = _make_auth_client(tg_id=42)

    # Set enabled
    res = client.post("/api/admin/settings/vaultwarden-enabled", json={"enabled": True})
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert vw_service.is_enabled() is True

    # Set credits
    res = client.post(
        "/api/admin/settings/vaultwarden-redeem-credits", json={"credits": 800}
    )
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert vw_service.get_redeem_credits() == 800
