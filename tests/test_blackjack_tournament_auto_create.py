"""每周自动开赛任务：按本周对齐的截止时点、去重闸门与开关。"""

from __future__ import annotations

import datetime

import pytest

from app.domains.blackjack import repository as blackjack_repository
from app.domains.blackjack import service as blackjack_service
from app.domains.blackjack.config import BLACKJACK_CONFIG, TOURNAMENT_REGISTERING
from app.domains.blackjack.jobs.tournament import (
    auto_create_blackjack_tournament_job,
)
from tests.conftest import add_tournament, next_id


@pytest.fixture
def explicit_ids(session_env):
    """内存 SQLite 不给 BIGINT 主键自增，走真实创建路径的用例须显式补 id。"""
    from sqlalchemy import event

    from app.domains.blackjack.models import BlackjackTournament

    @event.listens_for(BlackjackTournament, "before_insert")
    def _assign_id(mapper, connection, target):
        if target.id is None:
            target.id = next_id()

    yield

    event.remove(BlackjackTournament, "before_insert", _assign_id)


def _config(**overrides) -> dict:
    from app.domains.blackjack.repository import DEFAULT_BLACKJACK_CONFIG

    config = dict(DEFAULT_BLACKJACK_CONFIG)
    config["enabled"] = True
    config.update(overrides)
    return config


def _monday_ms() -> int:
    """本周一 00:00（本地时区）的毫秒时间戳，与任务内的对齐算法独立同源。"""
    from app.core.config import settings

    now = datetime.datetime.now(settings.TZ)
    monday = (now - datetime.timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int(monday.timestamp() * 1000)


@pytest.fixture
def before_registration_deadline(monkeypatch):
    """将自动开赛测试固定在周一，避免周三报名截止后随真实日期失败。"""
    import time

    from app.core.config import settings

    monday = datetime.datetime.now(settings.TZ)
    monday = (monday - datetime.timedelta(days=monday.weekday())).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    real_datetime = datetime.datetime

    class FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return monday.astimezone(tz) if tz else monday.replace(tzinfo=None)

    monkeypatch.setattr(datetime, "datetime", FrozenDatetime)
    monkeypatch.setattr(time, "time", lambda: monday.timestamp())


@pytest.mark.asyncio
async def test_auto_create_uses_week_aligned_deadlines(
    explicit_ids, monkeypatch, before_registration_deadline
):
    BLACKJACK_CONFIG.update(**_config())
    monkeypatch.setattr(blackjack_service, "_notify_enabled", lambda: False)

    await auto_create_blackjack_tournament_job()

    rows = blackjack_repository.list_blackjack_tournaments(
        statuses=(TOURNAMENT_REGISTERING,), limit=10
    )
    assert len(rows) == 1
    t = rows[0]
    monday = _monday_ms()
    # 报名截止 = 周三 18:00，完赛截止 = 周日 23:59（均相对本周一 00:00 对齐）
    assert t["register_deadline_ms"] == monday + (2 * 86400 + 18 * 3600) * 1000
    assert t["play_deadline_ms"] == monday + (6 * 86400 + 23 * 3600 + 59 * 60) * 1000
    # 名称走自动命名；补贴不增发（须是管理员显式操作）
    assert "期" in t["title"]
    assert t["seeded_prize_credits"] == 0


@pytest.mark.asyncio
async def test_auto_create_skips_when_registration_open(monkeypatch):
    """去重闸门：已有报名未截止的赛事（无论谁建）就不再重复建。"""
    import time

    add_tournament(
        status=TOURNAMENT_REGISTERING,
        register_deadline_ms=int(time.time() * 1000) + 3600 * 1000,
    )
    created = []
    monkeypatch.setattr(
        blackjack_service,
        "create_blackjack_tournament",
        lambda *a, **kw: created.append(1) or {},
    )

    await auto_create_blackjack_tournament_job()
    assert created == []


@pytest.mark.asyncio
async def test_auto_create_double_fire_is_idempotent(
    explicit_ids, monkeypatch, before_registration_deadline
):
    """任务重复触发：第一轮建了周赛，第二轮必须被闸门挡下。"""
    BLACKJACK_CONFIG.update(**_config())
    monkeypatch.setattr(blackjack_service, "_notify_enabled", lambda: False)

    await auto_create_blackjack_tournament_job()
    await auto_create_blackjack_tournament_job()

    rows = blackjack_repository.list_blackjack_tournaments(limit=10)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_auto_create_respects_switches(monkeypatch):
    """活动总开关或自动开赛开关任一关闭，都不创建。"""
    monkeypatch.setattr(blackjack_service, "_notify_enabled", lambda: False)

    for overrides in (
        {"enabled": False},
        {"tournament_auto_create_enabled": False},
    ):
        BLACKJACK_CONFIG.update(**_config(**overrides))
        await auto_create_blackjack_tournament_job()

    assert blackjack_repository.list_blackjack_tournaments(limit=10) == []


@pytest.mark.asyncio
async def test_auto_create_skips_when_count_unavailable(monkeypatch):
    """闸门查询失败返回 None 时按「无法确认」跳过，宁可漏一期也不重复建。"""
    BLACKJACK_CONFIG.update(**_config())
    monkeypatch.setattr(
        blackjack_service,
        "count_registering_blackjack_tournaments",
        lambda _now: None,
    )
    created = []
    monkeypatch.setattr(
        blackjack_service,
        "create_blackjack_tournament",
        lambda *a, **kw: created.append(1) or {},
    )

    await auto_create_blackjack_tournament_job()
    assert created == []
