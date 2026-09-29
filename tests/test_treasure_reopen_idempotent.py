"""fix-live-defects D9：夺宝自动开期的幂等与补救。

修复前：开奖后只挂一个一次性的内存调度任务（``misfire_grace_time=60``），
错过的开期永远丢失；开期动作本身没有幂等保护，重入会开出两期。
修复后：源期记录 ``auto_reopen_due_at`` / ``auto_reopen_issue_id``，
``open_next_issue`` 在事务里幂等开期，``treasure.reopen_overdue`` 每 10
分钟补开。
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, select

from app.core.db import get_session
from app.domains.treasure import service as treasure_service
from app.domains.treasure.models import TreasureIssue
from tests.conftest import next_id


def _assign_row_id(mapper, connection, target) -> None:  # pragma: no cover - hook
    if target.id is None:
        target.id = next_id()


event.listen(TreasureIssue, "before_insert", _assign_row_id)


def _seed_issue(*, status: int = 2, settled_at: int | None = None) -> int:
    with get_session() as session:
        issue = TreasureIssue(
            title="issue",
            description=None,
            prize_credits=100,
            total_credits_required=120,
            credits_per_share=10,
            total_shares=12,
            status=status,
            shares_sold=12,
            created_by=1,
            created_at=datetime.now(UTC),
        )
        session.add(issue)
        session.flush()
        return int(issue.id)


def _issue_count() -> int:
    with get_session() as session:
        return len(session.execute(select(TreasureIssue)).scalars().all())


@pytest.fixture
def silent_notifications(monkeypatch):
    from app.domains.treasure import notifications as treasure_notifications

    sent: list[dict] = []

    async def _fake(*args, **kwargs):
        sent.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(treasure_notifications, "notify_treasure_issue_created", _fake)
    return sent


async def test_open_next_issue_is_idempotent(session_env, silent_notifications):
    source_id = _seed_issue(status=2)

    first = await treasure_service.open_next_issue(source_issue_id=source_id)
    assert first is not None
    count_after_first = _issue_count()

    # 同一期重复开期（任务重试、并发触发）：只开出一期
    second = await treasure_service.open_next_issue(source_issue_id=source_id)
    assert second is None or second == first
    assert _issue_count() == count_after_first
    # 只发一条开期通知
    assert len(silent_notifications) == 1


async def test_reopen_overdue_resumes_missed_reopen(session_env, silent_notifications):
    source_id = _seed_issue(status=2)

    # 模拟停机跨过开期时间：due_at 已过、没有后继期数
    with get_session() as session:
        issue = session.get(TreasureIssue, source_id)
        issue.auto_reopen_due_at = int(time.time()) - 60
    count_before = _issue_count()

    reopened = await treasure_service.reopen_overdue_issues()

    assert reopened >= 1
    assert _issue_count() == count_before + 1


async def test_reopen_overdue_skips_history(session_env, silent_notifications):
    # 本功能上线前已开奖的期数：两列都是空
    _seed_issue(status=2)

    reopened = await treasure_service.reopen_overdue_issues()

    assert reopened == 0
    assert _issue_count() == 1
