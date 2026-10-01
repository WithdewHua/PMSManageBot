"""Compare profile responses against frozen pre-promotion handlers with fake I/O."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.db import get_session
from app.domains.identity import types
from app.domains.identity.models import Statistics
from app.domains.profile import schemas, service


@pytest.fixture
def profile_environment(monkeypatch):
    monkeypatch.setattr(service.settings, "TG_ADMIN_CHAT_ID", [42])
    monkeypatch.setattr(
        service.identity_service,
        "find_plex_by_tg",
        lambda _: types.PlexAccount(
            plex_id=9,
            tg_id=42,
            plex_email="p@example.test",
            plex_username="plex-user",
            watched_time=12.5,
            all_lib=1,
            is_premium=1,
            plex_line="premium",
            last_viewed_at=100,
        ),
    )
    monkeypatch.setattr(
        service.identity_service,
        "find_emby_by_tg",
        lambda _: types.EmbyAccount(
            emby_id="e1",
            tg_id=42,
            emby_username="emby-user",
            emby_watched_time=21,
            emby_is_unlock=1,
            emby_line="normal",
            last_viewed_at=200,
        ),
    )
    monkeypatch.setattr(
        service.identity_service,
        "get_statistics",
        lambda _: types.UserStatistics(42, 5, 120),
    )
    monkeypatch.setattr(
        service.identity_service,
        "find_overseerr_by_tg",
        lambda _: types.OverseerrAccount(7, "o@example.test", 42),
    )
    monkeypatch.setattr(
        service.invitation_service, "get_invitee_count_by_owner", lambda _: 3
    )
    monkeypatch.setattr(
        service.invitation_service,
        "get_invitation_code_by_owner",
        lambda _: ["code-a", "code-b"],
    )
    monkeypatch.setattr(
        service.media_access_service,
        "check_download_unlock",
        lambda *a: {"is_unlocked": True, "unlock_time": 123},
    )
    quota = {"current_debt": 30, "daily_limit": 100, "remaining_free": 70}
    monkeypatch.setattr(
        service.premium_service, "get_plex_premium_quota_status", lambda _: quota
    )
    monkeypatch.setattr(
        service.premium_service, "get_emby_premium_quota_status", lambda _: quota
    )
    monkeypatch.setattr(
        service.traffic_service,
        "daily_usage",
        lambda **kw: 240 if kw.get("premium_only") else 500,
    )
    monkeypatch.setattr(
        service.emby_integration,
        "Emby",
        lambda: SimpleNamespace(
            get_user_info_from_username=lambda _: {
                "date_created": "2025-01-02T10:20:00"
            }
        ),
    )
    monkeypatch.setattr(
        service.telegram_profiles, "get_user_name_from_tg_id", lambda _: "Profile"
    )
    monkeypatch.setattr(
        service.telegram_profiles,
        "get_user_info_from_tg_id",
        lambda _: {"first_name": "Profile", "photo_url": "avatar"},
    )


def legacy_namespace():
    def converted(function, converter):
        def query(tg_id):
            value = function(tg_id)
            return converter(value) if value is not None else None

        return query

    namespace = {
        "Update": object,
        "ContextTypes": SimpleNamespace(DEFAULT_TYPE=object),
        "Request": object,
        "BackgroundTasks": object,
        "TelegramUser": object,
        "Depends": lambda _: None,
        "get_telegram_user": lambda: None,
        "refresh_tg_user_info": service.refresh_tg_user_info,
        "UserInfo": schemas.UserInfo,
        "HTTPException": HTTPException,
        "get_session": get_session,
        "select": select,
        "Statistics": Statistics,
        "settings": service.settings,
        "logger": Mock(),
        "traffic_service": service.traffic_service,
        "Emby": service.emby_integration.Emby,
        "get_user_name_from_tg_id": service.telegram_profiles.get_user_name_from_tg_id,
        "get_user_info_from_tg_id": service.telegram_profiles.get_user_info_from_tg_id,
        "db": SimpleNamespace(
            get_plex_info_by_tg_id=converted(
                service.identity_service.find_plex_by_tg, types.plex_legacy_tuple
            ),
            get_emby_info_by_tg_id=converted(
                service.identity_service.find_emby_by_tg, types.emby_legacy_tuple
            ),
            get_stats_by_tg_id=converted(
                service.identity_service.get_statistics, types.statistics_legacy_tuple
            ),
            get_overseerr_info_by_tg_id=converted(
                service.identity_service.find_overseerr_by_tg,
                types.overseerr_legacy_tuple,
            ),
            check_download_unlock=service.media_access_service.check_download_unlock,
            get_plex_premium_quota_status=service.premium_service.get_plex_premium_quota_status,
            get_emby_premium_quota_status=service.premium_service.get_emby_premium_quota_status,
            get_invitee_count_by_owner=service.invitation_service.get_invitee_count_by_owner,
            get_invitation_code_by_owner=service.invitation_service.get_invitation_code_by_owner,
        ),
    }
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/profile_legacy_routes.json").read_text()
    )
    for source in fixture["functions"].values():
        exec(compile(source, fixture["source_ref"], "exec"), namespace)  # noqa: S102 -- versioned test fixture only
    return namespace


@pytest.mark.asyncio
async def test_profile_matches_frozen_handler(profile_environment):
    user = SimpleNamespace(id=42, username="Profile", first_name="First")
    old = await legacy_namespace()["get_user_info"](None, Mock(), user)
    current = service.get_user_profile(42, "Profile")
    assert current.model_dump() == old.model_dump()
    assert current.emby_info["created_at"] == "2025-01-02"
    assert current.plex_info["daily_premium_projected_debt"] == 170


@pytest.mark.asyncio
async def test_profile_section_failure_keeps_other_sections(
    profile_environment, monkeypatch
):
    def fail(*args, **kwargs):
        raise RuntimeError("isolated media failure")

    monkeypatch.setattr(service.identity_service, "find_plex_by_tg", fail)
    old = await legacy_namespace()["get_user_info"](
        None, Mock(), SimpleNamespace(id=42, username="Profile", first_name="First")
    )
    current = service.get_user_profile(42, "Profile")
    assert current.model_dump() == old.model_dump()
    assert current.plex_info is None
    assert current.emby_info is not None
    assert current.credits == 120


@pytest.mark.asyncio
async def test_user_selection_matches_frozen_query(session_env, profile_environment):
    with get_session() as session:
        session.add_all(
            [
                Statistics(tg_id=42, donation=5, credits=120),
                Statistics(tg_id=99, donation=0, credits=0),
            ]
        )
    old = await legacy_namespace()["get_all_users"](None, SimpleNamespace(id=99))
    assert service.list_users_for_selection() == old
    assert len(old) == 2  # Includes administrators; no new private filtering.


def test_bot_missing_statistics_renders_zero(profile_environment, monkeypatch):
    monkeypatch.setattr(service.identity_service, "get_statistics", lambda _: None)
    text = service.get_info_message(42)
    assert "<strong>可用积分: </strong>0.00" in text
    assert "<strong>捐赠金额: </strong>0\n" in text
    assert "code-a\ncode-b" in text
    assert "12.50h" in text and "21.00h" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("has_statistics", [True, False])
async def test_bot_output_matches_frozen_handler(
    profile_environment, monkeypatch, has_statistics
):
    from unittest.mock import AsyncMock

    from app.domains.profile import bot

    if not has_statistics:
        monkeypatch.setattr(service.identity_service, "get_statistics", lambda _: None)
    old = legacy_namespace()
    original_send = AsyncMock()
    new_send = AsyncMock()
    old["send_message"] = original_send
    monkeypatch.setattr(bot.messaging, "send_message", new_send)
    update = SimpleNamespace(_effective_chat=SimpleNamespace(id=42))
    context = object()
    await old["info"](update, context)
    await bot.info(update, context)
    assert new_send.await_args_list == original_send.await_args_list
