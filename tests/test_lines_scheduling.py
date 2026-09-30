from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.core.db import get_session
from app.domains.identity.models import PlexUser, Statistics
from app.domains.lines import repository, service
from app.domains.lines.models import LineSchedule


def _seed_plex_user(tg_id: int = 1, line: str = "old") -> None:
    with get_session() as session:
        session.add(Statistics(tg_id=tg_id, donation=0, credits=0))
        session.add(
            PlexUser(
                id=tg_id,
                plex_id=tg_id + 100,
                tg_id=tg_id,
                plex_username=f"user-{tg_id}",
                plex_email=f"{tg_id}@example.com",
                plex_line=line,
                line_schedule_unlocked=1,
            )
        )


def _add_schedule(
    *,
    schedule_id: int,
    tg_id: int,
    line: str,
    days: str,
    start: str,
    end: str,
    priority: int = 0,
    created_at: int = 1,
) -> None:
    with get_session() as session:
        session.add(
            LineSchedule(
                id=schedule_id,
                tg_id=tg_id,
                service="plex",
                line=line,
                days_of_week=days,
                start_time=start,
                end_time=end,
                priority=priority,
                is_enabled=1,
                created_at=created_at,
                updated_at=created_at,
            )
        )


def test_active_schedule_is_deterministic_and_handles_previous_day(session_env):
    _seed_plex_user()
    _add_schedule(
        schedule_id=10,
        tg_id=1,
        line="overnight",
        days="6",
        start="23:00",
        end="01:00",
        priority=1,
        created_at=2,
    )
    _add_schedule(
        schedule_id=11,
        tg_id=1,
        line="same-priority-tie",
        days="0",
        start="00:00",
        end="02:00",
        priority=1,
        created_at=2,
    )

    with get_session() as session:
        active = repository.get_current_active_schedule_tx(
            session,
            1,
            "plex",
            now=datetime(2024, 1, 1, 0, 30, tzinfo=UTC),  # Monday, active from Sunday.
        )

    # Both schedules are active; created_at then id is the stable tie-break.
    assert active is not None
    assert active["id"] == 10
    assert active["line"] == "overnight"


def test_auto_switch_reads_then_commits_and_auto_is_a_noop(session_env):
    _seed_plex_user()
    _add_schedule(
        schedule_id=20,
        tg_id=1,
        line="auto",
        days="0,1,2,3,4,5,6",
        start="00:00",
        end="23:59",
    )

    result = repository.apply_active_schedule(1, "plex")
    assert result is None
    with get_session() as session:
        user = session.get(PlexUser, 1)
        assert user is not None
        assert user.plex_line == "old"


def test_service_switch_writes_cache_only_after_commit(session_env, monkeypatch):
    events: list[str] = []

    class FakeCache:
        def get(self, key):
            events.append(f"get:{key}")
            return "previous"

        def put(self, key, value):
            events.append(f"put:{key}:{value}")

    class FakeRepository:
        @staticmethod
        def get_auto_switch_candidates(tg_id, service):
            events.append("read-candidates")
            return [{"tg_id": 1, "service": "plex"}]

        @staticmethod
        def apply_active_schedule(tg_id, service):
            events.append("commit")
            return {
                "service": service,
                "username": "User",
                "old_line": "old",
                "line": "new",
            }

    monkeypatch.setattr(service, "lines_repository", FakeRepository)
    monkeypatch.setattr(service, "plex_user_defined_line_cache", FakeCache())
    monkeypatch.setattr(service, "plex_last_user_defined_line_cache", FakeCache())
    monkeypatch.setattr(service, "get_user_name_from_tg_id", lambda tg_id: "user")

    asyncio.run(service.auto_switch_user_lines(tg_id=1, service="plex"))

    assert events == [
        "read-candidates",
        "commit",
        "get:user",
        "put:user:previous",
        "put:user:new",
    ]


def test_schedule_crud_updates_in_place_and_deletes_by_owner(session_env):
    _seed_plex_user()
    created_id = service.create_line_schedule(
        1, "plex", "created", [0], "08:00", "09:00", 1
    )
    assert created_id is not None
    _add_schedule(
        schedule_id=30,
        tg_id=1,
        line="old",
        days="0",
        start="10:00",
        end="11:00",
    )

    assert service.update_line_schedule(30, 1, line="new", priority=4)
    schedules = service.get_user_line_schedules(1, "plex")
    updated = next(schedule for schedule in schedules if schedule["id"] == 30)
    assert updated["line"] == "new"
    assert updated["priority"] == 4
    assert created_id in {schedule["id"] for schedule in schedules}

    assert service.delete_line_schedule(30, 1)
    remaining = service.get_user_line_schedules(1, "plex")
    assert all(schedule["id"] != 30 for schedule in remaining)
