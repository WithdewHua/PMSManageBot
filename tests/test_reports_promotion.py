"""Tests for Reports domain promotion (tasks 1.3, 3.1, 3.4).

Freezes behavior baseline (1.3), verifies read-model boundaries (3.1, 3.4):
- Traffic classification freeze: line.lower() in catalog_url.lower() in normal+premium order
- CustomLine.status == 'approved' check moved to custom_lines domain
- Plain counts/sums of wide-table columns stay in reports repository
- Vaultwarden stats query vaultwarden.service.count_redemptions()
- Router and entrypoints have zero direct SQL, zero get_session, zero ORM models
- Reports repository is strictly read-only: no writes, no mutations, no model instantiations
- System stats, system status, admin settings overview, traffic overview, weekly report, and bot status
"""

from __future__ import annotations

import ast
import json
import urllib.parse
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.api.app import app
from app.core.config import settings
from app.core.db import get_session
from app.domains.custom_lines import (
    service as custom_lines_service,
)
from app.domains.custom_lines.models import CustomLine
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
from app.domains.lines import (
    catalog as line_catalog,
)
from app.domains.lines import (
    service as lines_service,
)
from app.domains.reports import (
    bot as reports_bot,
)
from app.domains.reports import (
    jobs as reports_jobs,
)
from app.domains.reports import (
    service as reports_service,
)
from app.domains.traffic.models import LineTrafficStats
from app.domains.vaultwarden import (
    repository as vaultwarden_repository,
)
from app.domains.vaultwarden.models import VaultwardenRedeemRecords
from app.integrations.telegram.init_data import MOCK_AUTH_HASH
from tests.conftest import next_id


def _assign_row_id(mapper, connection, target) -> None:
    if target.id is None:
        target.id = next_id()


@pytest.fixture(autouse=True)
def assign_row_ids():
    """Assign synthetic BIGINT primary keys on SQLite test databases."""
    event.listen(VaultwardenRedeemRecords, "before_insert", _assign_row_id)
    event.listen(CustomLine, "before_insert", _assign_row_id)
    event.listen(LineTrafficStats, "before_insert", _assign_row_id)
    yield
    event.remove(VaultwardenRedeemRecords, "before_insert", _assign_row_id)
    event.remove(CustomLine, "before_insert", _assign_row_id)
    event.remove(LineTrafficStats, "before_insert", _assign_row_id)


def _make_auth_client(tg_id: int = 42) -> TestClient:
    """Create TestClient with mock telegram authentication header."""
    user_payload = {"id": tg_id, "first_name": "TestAdmin", "username": "testadmin"}
    init_data = (
        f"user={urllib.parse.quote(json.dumps(user_payload))}&hash={MOCK_AUTH_HASH}"
    )
    client = TestClient(app)
    client.headers.update({"X-Telegram-Init-Data": init_data})
    return client


# ============================================================================
# 1. Traffic Classification Freeze & Fixture Comparison (Task 1.3 / 3.1)
# ============================================================================


def test_traffic_classification_freeze_and_equivalence(session_env, monkeypatch):
    """Freeze and verify exact traffic classification behavior against historical logic.

    Historical rules:
    - Known lines: line.lower() in _line.lower() for _line in (normal_lines + premium_lines)
    - Custom lines: not known line AND line in approved_custom_lines (status == 'approved')
    - Other lines: ignored
    """
    now = datetime.now(settings.TZ)
    current_time_str = now.isoformat()

    # 1. Seed custom lines with different statuses
    with get_session() as session:
        session.add(
            CustomLine(
                tg_id=101,
                domain="custom-approved.org",
                network_info="direct",
                price_monthly=10,
                price_yearly=100,
                traffic_limit=500,
                traffic_type="one_way",
                valid_days=30,
                is_permanent=False,
                status="approved",
                created_at=int(now.timestamp()),
                updated_at=int(now.timestamp()),
            )
        )
        session.add(
            CustomLine(
                tg_id=102,
                domain="custom-pending.org",
                network_info="direct",
                price_monthly=10,
                price_yearly=100,
                traffic_limit=500,
                traffic_type="one_way",
                valid_days=30,
                is_permanent=False,
                status="pending",
                created_at=int(now.timestamp()),
                updated_at=int(now.timestamp()),
            )
        )
        session.commit()

    # 2. Mock line catalog
    monkeypatch.setattr(
        line_catalog, "normal_lines", lambda: ["https://hk1.example.com:8096"]
    )
    monkeypatch.setattr(
        line_catalog, "premium_lines", lambda: ["https://vip1.example.com"]
    )

    # 3. Seed traffic data
    with get_session() as session:
        # Catalog normal line (substring match)
        session.add(
            LineTrafficStats(
                service="emby",
                line="hk1.example.com",
                username="user1",
                event_hash="hash1",
                send_bytes=1000,
                timestamp=current_time_str,
            )
        )
        # Catalog premium line (case-insensitive substring match)
        session.add(
            LineTrafficStats(
                service="plex",
                line="VIP1.EXAMPLE.COM",
                username="user2",
                event_hash="hash2",
                send_bytes=2000,
                timestamp=current_time_str,
            )
        )
        # Approved custom line
        session.add(
            LineTrafficStats(
                service="emby",
                line="custom-approved.org",
                username="user3",
                event_hash="hash3",
                send_bytes=3000,
                timestamp=current_time_str,
            )
        )
        # Pending custom line (should NOT be classified as custom_line)
        session.add(
            LineTrafficStats(
                service="emby",
                line="custom-pending.org",
                username="user4",
                event_hash="hash4",
                send_bytes=4000,
                timestamp=current_time_str,
            )
        )
        # Completely unknown line
        session.add(
            LineTrafficStats(
                service="plex",
                line="unknown-server.net",
                username="user5",
                event_hash="hash5",
                send_bytes=5000,
                timestamp=current_time_str,
            )
        )
        session.commit()
    # Verify owning capabilities
    assert custom_lines_service.list_approved_domains() == ["custom-approved.org"]
    assert lines_service.is_known_catalog_line("hk1.example.com") is True
    assert lines_service.is_known_catalog_line("vip1.example.com") is True
    assert lines_service.is_known_catalog_line("custom-approved.org") is False

    # Execute service traffic statistics
    stats = reports_service.get_traffic_statistics()
    today_data = stats["today"]

    # Total send_bytes across all lines: 1000 + 2000 + 3000 + 4000 + 5000 = 15000
    assert today_data["total"] == 15000
    # Emby: 1000 + 3000 + 4000 = 8000
    assert today_data["emby"] == 8000
    # Plex: 2000 + 5000 = 7000
    assert today_data["plex"] == 7000

    # Classified catalog lines (hk1 + vip1)
    catalog_lines_reported = {
        item["line"]: item["traffic"] for item in today_data["lines"]
    }
    assert "hk1.example.com" in catalog_lines_reported
    assert catalog_lines_reported["hk1.example.com"] == 1000
    assert "VIP1.EXAMPLE.COM" in catalog_lines_reported
    assert catalog_lines_reported["VIP1.EXAMPLE.COM"] == 2000

    # Classified approved custom lines
    custom_lines_reported = {
        item["line"]: (item["traffic"], item["is_custom"])
        for item in today_data["custom_lines"]
    }
    assert "custom-approved.org" in custom_lines_reported
    assert custom_lines_reported["custom-approved.org"] == (3000, True)

    # Neither pending nor unknown line is in lines or custom_lines
    all_categorized_lines = set(catalog_lines_reported.keys()) | set(
        custom_lines_reported.keys()
    )
    assert "custom-pending.org" not in all_categorized_lines
    assert "unknown-server.net" not in all_categorized_lines


# ============================================================================
# 2. System Stats Endpoint & Service (Task 1.3 / 3.1)
# ============================================================================


def test_system_stats_assembly_and_endpoint(session_env, monkeypatch):
    """Test system statistics assembly across wide tables and Vaultwarden service."""
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)

    # Seed wide-table data in identity models
    with get_session() as session:
        # Bound user on both Plex and Emby (tg_id=100)
        session.add(
            PlexUser(
                id=1,
                tg_id=100,
                plex_id=11,
                plex_username="plex_user1",
                all_lib=1,  # nsfw unlocked
                line_schedule_unlocked=1,  # line schedule unlocked
                sync_unlocked=0,
            )
        )
        session.add(
            EmbyUser(
                tg_id=100,
                emby_username="emby_user1",
                emby_is_unlock=1,  # nsfw unlocked
                line_schedule_unlocked=0,
                download_unlocked=1,  # download unlocked
            )
        )
        # Unbound user on Plex (tg_id is None)
        session.add(
            PlexUser(
                id=2,
                tg_id=None,
                plex_id=12,
                plex_username="plex_user2",
                all_lib=0,
                line_schedule_unlocked=0,
                sync_unlocked=0,
            )
        )
        # Unbound user on Emby (tg_id is None)
        session.add(
            EmbyUser(
                tg_id=None,
                emby_username="emby_user2",
                emby_is_unlock=0,
                line_schedule_unlocked=1,  # line schedule unlocked
                download_unlocked=0,
            )
        )
        # User with statistics row for Vaultwarden foreign key
        session.add(Statistics(tg_id=100, credits=1000.0, donation=0.0))
        session.commit()
    # Record 2 Vaultwarden redemptions via repository
    vaultwarden_repository.record_redemption(
        tg_id=100, email="vw1@example.com", credits_cost=500.0
    )
    vaultwarden_repository.record_redemption(
        tg_id=100, email="vw2@example.com", credits_cost=500.0
    )

    # 1. Test direct service assembly
    stats = reports_service.get_system_stats()
    assert stats["plex_users"] == 2
    assert stats["emby_users"] == 2
    # Unique tg_id (1) + unbound plex (1) + unbound emby (1) = 3 total users
    assert stats["total_users"] == 3
    assert stats["nsfw_unlocked_users"] == 2  # 1 plex + 1 emby
    assert stats["line_schedule_unlocked_users"] == 2  # 1 plex + 1 emby
    assert stats["download_unlocked_users"] == 1  # 0 plex + 1 emby
    assert stats["vaultwarden_redeemed_count"] == 2

    # 2. Test HTTP endpoint GET /api/system/stats
    client = _make_auth_client(tg_id=42)
    response = client.get("/api/system/stats")
    assert response.status_code == 200
    res_data = response.json()
    assert res_data == stats


# ============================================================================
# 3. System Status and Traffic Overview Endpoints (Task 1.3)
# ============================================================================


def test_system_status_endpoint(session_env):
    """Test public GET /api/system/status does not require authentication."""
    client = TestClient(app)
    response = client.get("/api/system/status")
    assert response.status_code == 200
    data = response.json()
    assert "site_name" in data
    assert "plex_register" in data
    assert "emby_register" in data
    assert "community_links" in data


def test_traffic_overview_endpoint(session_env, monkeypatch):
    """Test authenticated GET /api/system/traffic-overview endpoint."""
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)
    client = _make_auth_client(tg_id=42)

    response = client.get("/api/system/traffic-overview")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "today" in data["data"]
    assert "week" in data["data"]
    assert "month" in data["data"]


# ============================================================================
# 4. Admin Settings Overview Endpoint (Task 1.3)
# ============================================================================


def test_admin_settings_endpoint(session_env, monkeypatch):
    """Test GET /api/admin/settings permissions and payload assembly."""
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", True)
    monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [99])

    # 1. Non-admin is rejected with 403
    client_non_admin = _make_auth_client(tg_id=42)
    res_forbidden = client_non_admin.get("/api/admin/settings")
    assert res_forbidden.status_code == 403

    # 2. Admin receives complete configuration and line catalogs
    client_admin = _make_auth_client(tg_id=99)
    res_admin = client_admin.get("/api/admin/settings")
    assert res_admin.status_code == 200
    admin_data = res_admin.json()
    assert "lines" in admin_data
    assert "premium_lines" in admin_data
    assert "free_premium_lines" in admin_data
    assert "invitation_credits" in admin_data
    assert "vaultwarden_enabled" in admin_data
    assert "vaultwarden_redeem_credits" in admin_data


# ============================================================================
# 5. Weekly Report and Telegram Bot Status (Task 1.3)
# ============================================================================


@pytest.mark.asyncio
async def test_send_weekly_report_workflow(monkeypatch):
    """Test weekly report service and scheduled job with mocked externals."""
    dispatched = []

    async def fake_send_message_by_url(chat_id, text, parse_mode="HTML", **kwargs):
        dispatched.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})
        return True

    monkeypatch.setattr(
        reports_service, "send_message_by_url", fake_send_message_by_url
    )
    monkeypatch.setattr(
        reports_service,
        "stats_report",
        lambda **kwargs: "<b>Weekly Stats Report Content</b>",
    )

    # Test service method
    report = await reports_service.send_weekly_report(channel_id="test_channel_123")
    assert "Weekly Stats Report Content" in report
    assert len(dispatched) == 1
    assert dispatched[0]["chat_id"] == "test_channel_123"

    # Test job entry point
    await reports_jobs.send_weekly_report(channel_id="test_channel_456")
    assert len(dispatched) == 2
    assert dispatched[1]["chat_id"] == "test_channel_456"


@pytest.mark.asyncio
async def test_bot_server_status_command(monkeypatch):
    """Test bot /server_status command formats playing users accurately."""
    monkeypatch.setattr(reports_service, "get_current_playing_users", lambda: (7, 12))

    sent_messages = []
    fake_update = MagicMock()
    fake_update.effective_chat.id = 12345
    fake_context = MagicMock()

    async def fake_bot_send_message(chat_id, text, parse_mode):
        sent_messages.append({"chat_id": chat_id, "text": text})

    fake_context.bot.send_message = fake_bot_send_message

    await reports_bot.get_server_status(fake_update, fake_context)
    assert len(sent_messages) == 1
    msg_text = sent_messages[0]["text"]
    assert "<strong>Plex</strong>: 7" in msg_text
    assert "<strong>Emby</strong>: 12" in msg_text


# ============================================================================
# 6. Read-Only Repository and AST Architecture Guardrails (Task 3.4)
# ============================================================================


def test_reports_repository_is_strictly_read_only():
    """Verify reports/repository.py contains NO write operations and NO model instantiations."""
    repo_path = Path("src/app/domains/reports/repository.py")
    tree = ast.parse(repo_path.read_text(encoding="utf-8"))

    prohibited_write_methods = {"add", "delete", "merge", "commit", "rollback"}
    prohibited_model_names = {
        "PlexUser",
        "EmbyUser",
        "CustomLine",
        "VaultwardenRedeemRecords",
        "LineTrafficStats",
    }

    for node in ast.walk(tree):
        # Check method calls on session: session.add(), session.delete(), etc.
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in prohibited_write_methods
            ):
                pytest.fail(
                    f"Write operation '{node.func.attr}' found in read-only reports repository"
                )
            # Check model instantiation: PlexUser(...), etc.
            if (
                isinstance(node.func, ast.Name)
                and node.func.id in prohibited_model_names
            ):
                pytest.fail(
                    f"Model instantiation '{node.func.id}(...)' found in read-only reports repository"
                )


def test_reports_entrypoints_have_no_sql_or_db_facade():
    """Verify entrypoints (router, admin_router, jobs, bot) have zero SQL or db facade imports."""
    files_to_check = [
        "src/app/domains/reports/router.py",
        "src/app/domains/reports/admin_router.py",
        "src/app/domains/reports/jobs.py",
        "src/app/domains/reports/bot.py",
    ]

    for file_str in files_to_check:
        path = Path(file_str)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "app.core.db" or "get_session" not in [
                    alias.name for alias in node.names
                ], f"{file_str} must not import get_session"
                assert node.module != "sqlalchemy", (
                    f"{file_str} must not import sqlalchemy"
                )
                assert node.module != "app.databases", (
                    f"{file_str} must not import app.databases facade"
                )


@pytest.mark.asyncio
async def test_weekly_job_preserves_none_return(monkeypatch):
    from unittest.mock import AsyncMock

    from app.domains.reports import jobs

    send = AsyncMock(return_value="rendered report")
    monkeypatch.setattr(jobs.reports_service, "send_weekly_report", send)
    assert await jobs.send_weekly_report(channel_id="channel") is None
    send.assert_awaited_once_with(channel_id="channel")
