"""锦标赛 tick 工作流的运行时行为：提交后副作用失败不回滚、单场失败不影响其余。"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from app.domains.blackjack import repository as blackjack_repository
from app.domains.blackjack import service as blackjack_service
from app.domains.blackjack.config import (
    BLACKJACK_CONFIG,
    ENTRY_ELIMINATED,
    ENTRY_FINISHED,
    ENTRY_PLAYING,
    TOURNAMENT_REGISTERING,
    TOURNAMENT_RUNNING,
    TOURNAMENT_SETTLED,
)
from tests.conftest import add_entry, add_tournament, add_user, get_stats

NOW_MS = int(time.time() * 1000)


def _row(tournament: dict) -> dict:
    return {
        "id": tournament["id"],
        "play_deadline_ms": tournament["play_deadline_ms"],
        "register_deadline_ms": tournament["register_deadline_ms"],
        "entrant_count": tournament["entrant_count"],
        "min_entrants": tournament["min_entrants"],
        "title": tournament["title"],
        "buy_in_credits": tournament["buy_in_credits"],
    }


def _status(tournament_id: int) -> int:
    return int(blackjack_repository.get_blackjack_tournament(tournament_id)["status"])


def _boom(*args, **kwargs):
    raise RuntimeError("telegram down")


def _settle_ready_tournament(orm) -> dict:
    t = add_tournament(orm)
    add_user(orm, 1, credits=0.0)
    add_user(orm, 2, credits=0.0)
    add_entry(orm, t["id"], 1, status=ENTRY_FINISHED, chips=1200, registered_at_ms=1)
    add_entry(orm, t["id"], 2, status=ENTRY_ELIMINATED, chips=800, registered_at_ms=2)
    return t


@pytest.mark.asyncio
async def test_settlement_commits_even_when_notifications_fail(orm, monkeypatch):
    """派奖先提交；赛果通知失败只记日志，不回滚赛事状态与积分。"""

    t = _settle_ready_tournament(orm)
    monkeypatch.setattr(blackjack_service, "_notify_enabled", lambda: True)
    monkeypatch.setattr(
        blackjack_service, "award_blackjack_champion_badge", AsyncMock()
    )
    monkeypatch.setattr(blackjack_service, "_send_many", _boom)

    await blackjack_service._tick_play_deadlines(NOW_MS, [_row(t)])

    assert _status(t["id"]) == TOURNAMENT_SETTLED
    assert get_stats(1)["credits"] > 0.0


@pytest.mark.asyncio
async def test_start_notification_failure_leaves_the_tournament_running(
    orm, monkeypatch
):
    t = add_tournament(
        orm,
        status=TOURNAMENT_REGISTERING,
        register_deadline_ms=NOW_MS - 1000,
        entrant_count=2,
    )
    monkeypatch.setattr(blackjack_service, "notify_tournament_started", _boom)

    await blackjack_service._tick_registration_deadlines(NOW_MS, [_row(t)])

    assert _status(t["id"]) == TOURNAMENT_RUNNING


@pytest.mark.asyncio
async def test_one_failing_tournament_does_not_stop_the_others(orm, monkeypatch):
    first = add_tournament(
        orm,
        status=TOURNAMENT_REGISTERING,
        register_deadline_ms=NOW_MS - 1000,
        title="will fail",
    )
    second = add_tournament(
        orm,
        status=TOURNAMENT_REGISTERING,
        register_deadline_ms=NOW_MS - 1000,
        title="will start",
    )
    real_start = blackjack_service.start_blackjack_tournament

    def _flaky(tournament_id: int, *args, **kwargs):
        if int(tournament_id) == int(first["id"]):
            raise RuntimeError("boom")
        return real_start(tournament_id, *args, **kwargs)

    monkeypatch.setattr(blackjack_service, "start_blackjack_tournament", _flaky)
    monkeypatch.setattr(blackjack_service, "notify_tournament_started", AsyncMock())

    await blackjack_service._tick_registration_deadlines(
        NOW_MS, [_row(first), _row(second)]
    )

    assert _status(first["id"]) == TOURNAMENT_REGISTERING
    assert _status(second["id"]) == TOURNAMENT_RUNNING


@pytest.mark.asyncio
async def test_reminders_advance_the_dedupe_cursor_without_sending(orm, monkeypatch):
    """通知关闭时仍推进 reminder_sent_at，避免重新打开后倾泻积压提醒。"""

    t = add_tournament(
        orm,
        status=TOURNAMENT_RUNNING,
        play_deadline_ms=NOW_MS + 3600 * 1000,
        register_deadline_ms=NOW_MS - 2 * 3600 * 1000,
    )
    add_user(orm, 1)
    add_entry(orm, t["id"], 1, status=ENTRY_PLAYING, hands_played=0)

    BLACKJACK_CONFIG.update(tournament_remind_lead_hours=6)
    monkeypatch.setattr(blackjack_service, "_notify_enabled", lambda: False)
    send = AsyncMock()
    monkeypatch.setattr(blackjack_service, "_send_many", send)

    claimed: list[dict] = []
    real_claim = blackjack_service.claim_tournament_reminder

    def _spy(tournament_id: int):
        result = real_claim(tournament_id)
        claimed.append(result)
        return result

    monkeypatch.setattr(blackjack_service, "claim_tournament_reminder", _spy)

    await blackjack_service._tick_completion_reminders(NOW_MS, [_row(t)])
    await blackjack_service._tick_completion_reminders(NOW_MS, [_row(t)])

    send.assert_not_awaited()
    assert [bool(item.get("claimed")) for item in claimed] == [True, False]


@pytest.mark.asyncio
async def test_tick_swallows_list_failures(monkeypatch):
    """拉列表失败只记日志：调度任务不得抛出异常。"""

    monkeypatch.setattr(blackjack_service, "list_blackjack_tournaments", _boom)
    phases = []
    for name in (
        "_tick_registration_deadlines",
        "_tick_completion_reminders",
        "_tick_play_deadlines",
    ):
        mock = AsyncMock()
        phases.append(mock)
        monkeypatch.setattr(blackjack_service, name, mock)

    await blackjack_service.tick_tournaments()

    for mock in phases:
        mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_tick_runs_every_phase_for_the_fetched_status_lists(orm, monkeypatch):
    """每轮 tick 按状态各查一次列表，并依次跑三个阶段。"""

    calls: list[tuple[str, tuple, dict]] = []

    def _list(statuses, limit):
        calls.append(("list", statuses, {"limit": limit}))
        return []

    monkeypatch.setattr(blackjack_service, "list_blackjack_tournaments", _list)
    phases = {}
    for name in (
        "_tick_registration_deadlines",
        "_tick_completion_reminders",
        "_tick_play_deadlines",
    ):
        mock = AsyncMock()
        phases[name] = mock
        monkeypatch.setattr(blackjack_service, name, mock)

    await blackjack_service.tick_tournaments()

    assert [call[1] for call in calls] == [
        (TOURNAMENT_REGISTERING,),
        (TOURNAMENT_RUNNING,),
    ]
    assert [mock.await_count for mock in phases.values()] == [1, 1, 1]
