"""启动恢复：为仍在进行中的手牌重建持久化超时任务（6.4 验证）。"""

from __future__ import annotations

import time

from app.domains.blackjack.jobs import cash as blackjack_cash_jobs
from tests.conftest import add_cash_hand, add_user

NOW_MS = int(time.time() * 1000)


def _scheduled(monkeypatch) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []

    def _schedule_task(task_name, **kwargs):
        calls.append((task_name, kwargs))

    monkeypatch.setattr("app.core.scheduler.schedule_task", _schedule_task)
    return calls


def test_restores_timeout_for_active_hand(monkeypatch):
    add_user(1, credits=100.0)
    hand_id = add_cash_hand(1, created_at_ms=NOW_MS)
    calls = _scheduled(monkeypatch)

    blackjack_cash_jobs.restore_blackjack_timeouts()

    assert len(calls) == 1
    task_name, kwargs = calls[0]
    assert task_name == "blackjack.hand_timeout"
    assert kwargs["job_id"] == f"blackjack_timeout_{hand_id}"
    assert kwargs["kwargs"] == {"hand_id": hand_id}
    # 服务重启后不得因错过窗口被丢弃
    assert kwargs["misfire_grace_time"] is None
    assert 0 < kwargs["run_date"].timestamp() - time.time() < 15 * 60 + 5


def test_expired_hand_is_left_to_the_sweeper(monkeypatch):
    """已过期的牌不在启动阶段处理，交给定时兜底全量清理。"""

    add_user(1, credits=100.0)
    add_cash_hand(1, created_at_ms=NOW_MS - 16 * 60 * 1000)
    calls = _scheduled(monkeypatch)

    blackjack_cash_jobs.restore_blackjack_timeouts()

    assert calls == []


def test_no_active_hands_schedules_nothing(monkeypatch):
    add_user(1, credits=100.0)
    calls = _scheduled(monkeypatch)

    blackjack_cash_jobs.restore_blackjack_timeouts()

    assert calls == []


def test_restore_never_raises_when_listing_fails(monkeypatch):
    """启动钩子失败不得阻断启动：异常只记日志。"""

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(
        "app.domains.blackjack.service.list_active_blackjack_hands", _boom
    )

    blackjack_cash_jobs.restore_blackjack_timeouts()
