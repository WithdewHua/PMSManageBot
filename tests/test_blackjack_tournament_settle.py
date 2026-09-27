"""21 点锦标赛完赛闸门与发牌/结算写锁。"""

from __future__ import annotations

import importlib
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.blackjack import repository as blackjack_repository
from app.domains.blackjack import service as blackjack_service
from app.domains.blackjack.config import (
    ENTRY_ELIMINATED,
    ENTRY_FINISHED,
    ENTRY_PLAYING,
    TOURNAMENT_RUNNING,
    TOURNAMENT_SETTLED,
)
from tests.conftest import add_entry, add_pending_hand, add_tournament, add_user

# Patch the actual defining module without coupling tests to a chunk filename.
_db_mod = importlib.import_module(
    blackjack_repository._repository.list_blackjack_tournaments_with_playing_entries.__func__.__module__
)


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


def test_empty_id_list_does_not_hit_db(orm, monkeypatch):
    monkeypatch.setattr(
        _db_mod,
        "get_session",
        lambda: (_ for _ in ()).throw(
            AssertionError("empty list must not open a session")
        ),
    )
    assert (
        blackjack_repository.list_blackjack_tournaments_with_playing_entries([])
        == set()
    )


def test_playing_query_returns_only_playing_ids(orm):
    t_playing = add_tournament(orm, title="still playing")
    t_done = add_tournament(orm, title="all terminal")
    add_user(orm, 101)
    add_user(orm, 102)
    add_user(orm, 201)
    add_entry(orm, t_playing["id"], 101, status=ENTRY_FINISHED)
    add_entry(orm, t_playing["id"], 102, status=ENTRY_PLAYING)
    add_entry(orm, t_done["id"], 201, status=ENTRY_ELIMINATED)

    found = blackjack_repository.list_blackjack_tournaments_with_playing_entries(
        [t_playing["id"], t_done["id"], 999]
    )
    assert found == {t_playing["id"]}


def test_playing_query_failure_returns_none(orm, monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(_db_mod, "get_session", _boom)
    assert (
        blackjack_repository.list_blackjack_tournaments_with_playing_entries([1])
        is None
    )


def test_settle_all_terminal_before_deadline(orm):
    t = add_tournament(orm)
    add_user(orm, 1, credits=0)
    add_user(orm, 2, credits=0)
    add_entry(orm, t["id"], 1, status=ENTRY_FINISHED, chips=1200, registered_at_ms=1)
    add_entry(orm, t["id"], 2, status=ENTRY_ELIMINATED, chips=800, registered_at_ms=2)

    result = blackjack_repository.settle_blackjack_tournament(t["id"])
    assert result["settled"] is True
    assert result["champion_tg_id"] == 1
    assert result["tournament"]["status"] == TOURNAMENT_SETTLED
    assert [row["tg_id"] for row in result["standings"] if row["final_rank"]] == [1, 2]


def test_settle_skips_ineligible_playing_entry(orm):
    t = add_tournament(orm, play_deadline_ms=int(time.time() * 1000) - 1000)
    add_user(orm, 1, credits=0)
    add_user(orm, 2, credits=0)
    add_entry(orm, t["id"], 1, status=ENTRY_FINISHED, chips=1200, registered_at_ms=1)
    add_entry(orm, t["id"], 2, status=ENTRY_PLAYING, chips=2000, registered_at_ms=2)

    result = blackjack_repository.settle_blackjack_tournament(t["id"])
    assert result["settled"] is True
    ranked = [row for row in result["standings"] if row["final_rank"] is not None]
    assert [row["tg_id"] for row in ranked] == [1]
    sitting = next(row for row in result["standings"] if row["tg_id"] == 2)
    assert sitting["final_rank"] is None
    assert sitting["prize_credits"] == 0.0


def test_settle_is_idempotent(orm):
    t = add_tournament(orm)
    add_user(orm, 1)
    add_entry(orm, t["id"], 1, status=ENTRY_FINISHED, chips=1000)
    first = blackjack_repository.settle_blackjack_tournament(t["id"])
    second = blackjack_repository.settle_blackjack_tournament(t["id"])
    assert first["settled"] is True
    assert second["settled"] is False
    assert second["standings"] == []
    assert second["tournament"]["status"] == TOURNAMENT_SETTLED


def test_settle_aborts_when_pending_hand_exists(orm):
    t = add_tournament(orm)
    add_user(orm, 1)
    add_entry(orm, t["id"], 1, status=ENTRY_PLAYING, chips=990)
    add_pending_hand(orm, t["id"], 1)

    result = blackjack_repository.settle_blackjack_tournament(t["id"])
    assert result["settled"] is False
    again = blackjack_repository.get_blackjack_tournament(t["id"])
    assert again["status"] == TOURNAMENT_RUNNING


def test_deal_rejects_after_settled(orm):
    t = add_tournament(orm)
    add_user(orm, 1)
    add_entry(orm, t["id"], 1, status=ENTRY_FINISHED, chips=1000)
    blackjack_repository.settle_blackjack_tournament(t["id"])

    with pytest.raises(ValueError, match="tournament not running"):
        blackjack_repository.create_blackjack_tournament_hand(1, t["id"], 10)


def test_deal_rejects_after_deadline(orm, monkeypatch):
    past = int(time.time() * 1000) - 1000
    t = add_tournament(orm, play_deadline_ms=past)
    add_user(orm, 1)
    add_entry(orm, t["id"], 1, status=ENTRY_PLAYING, chips=1000)

    with pytest.raises(ValueError, match="tournament finished"):
        blackjack_repository.create_blackjack_tournament_hand(1, t["id"], 10)


def test_deal_uses_wall_clock_after_lock(orm, monkeypatch):
    t = add_tournament(orm, play_deadline_ms=int(time.time() * 1000) + 60_000)
    add_user(orm, 1)
    add_entry(orm, t["id"], 1, status=ENTRY_PLAYING, chips=1000)

    real_lock = blackjack_repository._repository._lock_running_tournament

    def _lock_then_expire(session, tournament_id):
        row = real_lock(session, tournament_id)
        monkeypatch.setattr(time, "time", lambda: (t["play_deadline_ms"] / 1000.0) + 1)
        return row

    monkeypatch.setattr(
        blackjack_repository._repository, "_lock_running_tournament", _lock_then_expire
    )
    with pytest.raises(ValueError, match="tournament finished"):
        blackjack_repository.create_blackjack_tournament_hand(1, t["id"], 10)


def test_lock_running_misses_settled_tournament(orm):
    from app.core.db import get_session

    t = add_tournament(orm)
    add_user(orm, 1)
    add_entry(orm, t["id"], 1, status=ENTRY_FINISHED, chips=1000)
    blackjack_repository.settle_blackjack_tournament(t["id"])

    with get_session() as session:
        assert blackjack_repository.lock_running_tournament(session, t["id"]) is None


@pytest.mark.asyncio
async def test_tick_settles_all_terminal_before_deadline(orm, monkeypatch):
    t = add_tournament(orm)
    add_user(orm, 1)
    add_user(orm, 2)
    add_entry(orm, t["id"], 1, status=ENTRY_FINISHED, chips=1200, registered_at_ms=1)
    add_entry(orm, t["id"], 2, status=ENTRY_ELIMINATED, chips=800, registered_at_ms=2)

    monkeypatch.setattr(blackjack_service, "_notify_enabled", lambda: False)
    award = AsyncMock()
    monkeypatch.setattr(blackjack_service, "award_blackjack_champion_badge", award)

    await blackjack_service._tick_play_deadlines(_now_before_deadline(t), [_row(t)])
    assert (
        blackjack_repository.get_blackjack_tournament(t["id"])["status"]
        == TOURNAMENT_SETTLED
    )
    # 冠军勋章由 tick 工作流在同一阶段协调授予，入参就是结算出的冠军
    award.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_tick_does_not_settle_while_someone_is_playing(orm, monkeypatch):
    t = add_tournament(orm)
    add_user(orm, 1)
    add_user(orm, 2)
    add_entry(orm, t["id"], 1, status=ENTRY_FINISHED, chips=1200)
    add_entry(orm, t["id"], 2, status=ENTRY_PLAYING, chips=800)

    settle = MagicMock()
    monkeypatch.setattr(blackjack_service, "settle_blackjack_tournament", settle)

    await blackjack_service._tick_play_deadlines(_now_before_deadline(t), [_row(t)])
    settle.assert_not_called()
    assert (
        blackjack_repository.get_blackjack_tournament(t["id"])["status"]
        == TOURNAMENT_RUNNING
    )


@pytest.mark.asyncio
async def test_tick_settles_at_deadline_even_with_playing_entry(orm, monkeypatch):
    t = add_tournament(orm, play_deadline_ms=int(time.time() * 1000) - 1000)
    add_user(orm, 1)
    add_user(orm, 2)
    add_entry(orm, t["id"], 1, status=ENTRY_FINISHED, chips=1200, registered_at_ms=1)
    add_entry(orm, t["id"], 2, status=ENTRY_PLAYING, chips=800, registered_at_ms=2)

    monkeypatch.setattr(blackjack_service, "_notify_enabled", lambda: False)
    monkeypatch.setattr(
        blackjack_service, "award_blackjack_champion_badge", AsyncMock()
    )

    await blackjack_service._tick_play_deadlines(
        int(t["play_deadline_ms"]) + 1, [_row(t)]
    )
    settled = blackjack_repository.get_blackjack_tournament(t["id"])
    assert settled["status"] == TOURNAMENT_SETTLED


@pytest.mark.asyncio
async def test_tick_query_none_does_not_early_settle(orm, monkeypatch):
    t = add_tournament(orm)
    add_user(orm, 1)
    add_entry(orm, t["id"], 1, status=ENTRY_FINISHED, chips=1000)

    monkeypatch.setattr(
        blackjack_service,
        "list_blackjack_tournaments_with_playing_entries",
        lambda _ids: None,
    )
    settle = MagicMock()
    monkeypatch.setattr(blackjack_service, "settle_blackjack_tournament", settle)

    await blackjack_service._tick_play_deadlines(_now_before_deadline(t), [_row(t)])
    settle.assert_not_called()


@pytest.mark.asyncio
async def test_tick_skips_settle_when_clear_fails(orm, monkeypatch):
    t = add_tournament(orm)
    add_user(orm, 1)
    add_entry(orm, t["id"], 1, status=ENTRY_FINISHED, chips=1000)

    monkeypatch.setattr(
        blackjack_service,
        "force_settle_tournament_hands",
        lambda _tid: {"cleared": False, "remaining": 1},
    )
    settle = MagicMock()
    monkeypatch.setattr(blackjack_service, "settle_blackjack_tournament", settle)

    await blackjack_service._tick_play_deadlines(_now_before_deadline(t), [_row(t)])
    settle.assert_not_called()


def _now_before_deadline(tournament: dict) -> int:
    return int(tournament["play_deadline_ms"]) - 60_000
