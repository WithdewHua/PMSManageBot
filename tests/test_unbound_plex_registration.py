from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from app.core.config import settings
from app.core.db import get_session
from app.domains.accounts import service as accounts_service
from app.domains.accounts.config import ACCOUNTS_CONFIG
from app.domains.identity.models import PlexUser, Statistics
from app.domains.invitation import service as invitation_service
from app.domains.invitation.models import Invitation


class FakePlex:
    def __init__(self, *, plex_id: int = 0, username: str = "") -> None:
        self.users_by_email: dict[str, object] = {}
        self.plex_id = plex_id
        self.username = username

    def invite_friend(self, email: str, **kwargs) -> bool:
        return True

    def get_user_id_by_email(self, email: str) -> int:
        return self.plex_id

    def get_username_by_user_id(self, plex_id: int) -> str:
        return self.username

    def get_user_shared_libs_by_id(self, plex_id: int) -> list[str]:
        return []

    def get_libraries(self) -> list[str]:
        return []


def _seed_invitation(code: str = "code") -> None:
    with get_session() as session:
        session.add(Invitation(code=code, owner=999, is_used=0))


def test_unbound_registration_creates_pending_plex_row_and_schedules_resolution(
    session_env, monkeypatch
) -> None:
    ACCOUNTS_CONFIG.invalidate()
    ACCOUNTS_CONFIG.update(plex_register=True)
    _seed_invitation()
    scheduled: list[str] = []
    monkeypatch.setattr(
        invitation_service,
        "register_plex_id_resolution_task",
        lambda email: scheduled.append(email),
    )
    monkeypatch.setattr(
        invitation_service,
        "media_access_service",
        type("Media", (), {"get_nsfw_libs": staticmethod(list)}),
    )
    monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [])

    result = asyncio.run(
        invitation_service.register_plex(
            code="code",
            email="pending@example.com",
            bind_to_telegram=False,
            telegram_user_id=42,
            privileged=False,
            notify=Mock(),
            plex_factory=lambda: FakePlex(),
        )
    )

    assert result == (False, 999)
    assert scheduled == ["pending@example.com"]
    with get_session() as session:
        row = session.query(PlexUser).filter_by(plex_email="pending@example.com").one()
        assert row.tg_id is None
        assert row.plex_id is None


def test_bound_registration_sync_resolves_ids_and_removes_named_task(
    session_env, monkeypatch
) -> None:
    ACCOUNTS_CONFIG.invalidate()
    ACCOUNTS_CONFIG.update(plex_register=True)
    _seed_invitation("resolve")
    scheduled: list[str] = []
    monkeypatch.setattr(
        invitation_service,
        "register_plex_id_resolution_task",
        lambda email: scheduled.append(email),
    )
    monkeypatch.setattr(
        invitation_service,
        "media_access_service",
        type("Media", (), {"get_nsfw_libs": staticmethod(list)}),
    )
    monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [])

    result = asyncio.run(
        invitation_service.register_plex(
            code="resolve",
            email="resolve@example.com",
            bind_to_telegram=True,
            telegram_user_id=42,
            privileged=False,
            notify=Mock(),
            plex_factory=lambda: FakePlex(),
        )
    )
    assert result == (True, 999)
    assert scheduled == ["resolve@example.com"]

    monkeypatch.setattr(
        accounts_service,
        "Plex",
        lambda: FakePlex(plex_id=456, username="resolved-user"),
    )
    removed: list[tuple[str, str]] = []
    fake_scheduler = SimpleNamespace(
        scheduler=SimpleNamespace(
            get_job=lambda job_id, jobstore: (
                object()
                if job_id == "update_plex_info_for_resolve@example.com"
                else None
            )
        ),
        remove_job=lambda job_id, jobstore: removed.append((job_id, jobstore)),
    )
    monkeypatch.setattr("app.core.scheduler.Scheduler", lambda: fake_scheduler)

    assert invitation_service.resolve_plex_id_job("resolve@example.com") is True
    assert removed == [("update_plex_info_for_resolve@example.com", "default")]
    with get_session() as session:
        row = session.query(PlexUser).filter_by(tg_id=42).one()
        invite = session.query(Invitation).filter_by(code="resolve").one()
        assert row.plex_id == 456
        assert row.plex_username == "resolved-user"
        assert invite.plex_id == 456


def test_unresolved_plex_task_stays_scheduled_for_retry(
    session_env, monkeypatch
) -> None:
    with get_session() as session:
        session.add(PlexUser(plex_email="later@example.com", plex_id=None))
    monkeypatch.setattr(accounts_service, "Plex", lambda: FakePlex())
    removed: list[str] = []
    fake_scheduler = SimpleNamespace(
        scheduler=SimpleNamespace(get_job=lambda *_args, **_kwargs: object()),
        remove_job=lambda job_id, **_kwargs: removed.append(job_id),
    )
    monkeypatch.setattr("app.core.scheduler.Scheduler", lambda: fake_scheduler)

    assert invitation_service.resolve_plex_id_job("later@example.com") is False
    assert removed == []


def test_pending_plex_binding_moves_accumulated_credits_and_resolves_invitation(
    session_env, monkeypatch
) -> None:
    with get_session() as session:
        session.add(Statistics(tg_id=42, credits=0, donation=0))
        session.add(
            PlexUser(
                plex_email="Pending@Example.com",
                tg_id=None,
                plex_id=None,
                credits=7,
            )
        )
        session.add(
            Invitation(
                code="used-bind",
                owner=999,
                is_used=1,
                used_by="Pending@Example.com",
                service="plex",
            )
        )
    monkeypatch.setattr(
        accounts_service,
        "Plex",
        lambda: FakePlex(plex_id=123, username="pending-user"),
    )
    monkeypatch.setattr(
        "app.domains.credits.repository._register_cache_invalidation",
        lambda *args, **kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(
        "app.domains.credits.repository._register_cache_invalidation_tx",
        lambda *args, **kwargs: None,
        raising=False,
    )

    assert accounts_service.bind_plex(42, "pending@example.com") == (
        True,
        "绑定 Plex 账户 pending@example.com 成功！",
    )

    with get_session() as session:
        row = session.query(PlexUser).filter_by(plex_id=123).one()
        stats = session.query(Statistics).filter_by(tg_id=42).one()
        invite = session.query(Invitation).filter_by(code="used-bind").one()
        assert row.tg_id == 42
        assert row.credits == 0
        assert stats.credits == 7
        assert invite.plex_id == 123


def test_existing_telegram_plex_binding_degrades_registration_to_pending_row(
    session_env, monkeypatch
) -> None:
    ACCOUNTS_CONFIG.invalidate()
    ACCOUNTS_CONFIG.update(plex_register=True)
    _seed_invitation("degrade")
    with get_session() as session:
        session.add(PlexUser(plex_id=1, tg_id=42, plex_email="existing@example.com"))
    scheduled: list[str] = []
    monkeypatch.setattr(
        invitation_service,
        "register_plex_id_resolution_task",
        lambda email: scheduled.append(email),
    )
    monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [])

    result = asyncio.run(
        invitation_service.register_plex(
            code="degrade",
            email="new-pending@example.com",
            bind_to_telegram=True,
            telegram_user_id=42,
            privileged=False,
            notify=Mock(),
            plex_factory=lambda: FakePlex(),
        )
    )

    assert result[0] is False
    assert scheduled == ["new-pending@example.com"]
    with get_session() as session:
        row = (
            session.query(PlexUser)
            .filter_by(plex_email="new-pending@example.com")
            .one()
        )
        assert row.tg_id is None
