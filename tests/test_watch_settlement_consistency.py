"""fix-live-defects D2：观看积分结算的一致性。

修复前的缺陷（proposal）：
- 会员流量费套用了不允许透支的 ``deduct_tx``，余额不足时当天后续用户全部中止。
- 没有结算记录，同一天重跑、补跑 ``legacy-credit-sync`` 会重复发放。
- 中途失败时：失败点之后用户漏发、邀请人奖励漏发、幽灵补偿不标记（下轮重复）。
- 邀请人通知里的“当前总积分”把奖励多算了一次（仅显示）。

外部服务（Tautulli/Plex/Emby、账号同步、premium 结算规则）全部用替身。
"""

from __future__ import annotations

from sqlalchemy import event, select

from app.core.db import get_session
from app.domains.credits import repository as credits_repository
from app.domains.identity.models import PlexUser, Statistics
from app.domains.invitation.models import Invitation
from app.domains.watch_rewards import service as wr_service
from app.domains.watch_rewards.models import GhostSessionLog
from tests.conftest import next_id

# ----------------------------------------------------------------------------
# 替身与工具
# ----------------------------------------------------------------------------


class FakePlexIntegration:
    def __init__(self, user_count: int = 0):
        self.users_by_id = {i: None for i in range(user_count)}


class FakeTautulli:
    def __init__(self, home_stats=None):
        self._home_stats = home_stats or []

    def get_home_stats(self, *args, **kwargs):
        return self._home_stats


def _no_traffic_settlement(**kwargs):
    return {
        "exceed_bytes": 0,
        "traffic_cost_credits": kwargs.get("cost", 0.0),
        "chargeable_bytes": 0,
        "debt_before_today": 0,
        "next_debt_bytes": 0,
        "next_debt_updated_date": None,
        "effective_limit": 0,
        "recovered_before_today": 0,
    }


def _seed_plex_user(
    plex_id: int,
    *,
    tg_id: int | None = None,
    credits: float = 100.0,
    watched: float = 0.0,
    username: str | None = None,
    premium: int = 0,
) -> None:
    with get_session() as session:
        session.add(
            PlexUser(
                plex_id=plex_id,
                tg_id=tg_id,
                plex_email=f"{plex_id}@example.com",
                plex_username=username or f"plex{plex_id}",
                credits=credits,
                watched_time=watched,
                is_premium=premium,
            )
        )


def _seed_stats(tg_id: int, credits: float = 100.0) -> None:
    with get_session() as session:
        session.add(Statistics(tg_id=tg_id, credits=credits, donation=0.0))


def _seed_inviter(inviter_tg_id: int, plex_id: int) -> None:
    with get_session() as session:
        session.add(
            Invitation(
                code=f"code-{plex_id}",
                owner=inviter_tg_id,
                is_used=1,
                plex_id=plex_id,
                service="plex",
            )
        )


def _assign_ghost_id(mapper, connection, target) -> None:
    if target.id is None:
        target.id = next_id()


event.listen(GhostSessionLog, "before_insert", _assign_ghost_id)


def _seed_ghost(plex_id: int, hours: float, *, compensated: int = 0) -> None:
    with get_session() as session:
        session.add(
            GhostSessionLog(
                row_id=10_000 + plex_id,
                user_id=str(plex_id),
                started=0,
                stopped=3600,
                play_date="2026-09-27",
                raw_seconds=int(hours * 3600),
                media_seconds=int(hours * 3600),
                percent_complete=100,
                compensated_seconds=int(hours * 3600),
                deleted=1,
                compensated=compensated,
                created_at=0,
            )
        )


def _plex_row(plex_id: int) -> PlexUser:
    with get_session() as session:
        row = session.execute(
            select(PlexUser).where(PlexUser.plex_id == int(plex_id))
        ).scalar_one()
        session.refresh(row)
        session.expunge(row)
        return row


def _plex_credits(plex_id: int) -> float:
    return float(_plex_row(plex_id).credits)


def _tg_credits(tg_id: int) -> float:
    with get_session() as session:
        row = session.get(Statistics, int(tg_id))
        assert row is not None
        return float(row.credits)


def _install(
    monkeypatch,
    *,
    durations: dict | None = None,
    traffic_costs: dict | None = None,
    fail_plex_ids: set | None = None,
):
    """把结算函数的外部依赖全部替换成可控行为。"""
    monkeypatch.setattr(wr_service, "update_plex_info", lambda **kwargs: None)
    monkeypatch.setattr(wr_service, "Plex", lambda: FakePlexIntegration())
    monkeypatch.setattr(
        wr_service,
        "Tautulli",
        lambda: FakeTautulli(),
    )
    monkeypatch.setattr(
        wr_service, "get_user_total_duration", lambda stats: dict(durations or {})
    )
    monkeypatch.setattr(
        wr_service,
        "_resolve_premium_status_for_settlement",
        lambda **kwargs: False,
    )

    costs = traffic_costs or {}
    failing = fail_plex_ids or set()
    active_account = {"plex_id": 0}

    def fake_traffic_settlement(**kwargs):
        cost = float(costs.get(active_account["plex_id"], 0.0))
        result = _no_traffic_settlement(cost=cost)
        result["traffic_cost_credits"] = cost
        return result

    monkeypatch.setattr(
        wr_service, "_settle_premium_traffic_usage", fake_traffic_settlement
    )

    from app.databases import db

    def fake_daily_traffic(user_id, service, date, premium_only=False):
        active_account["plex_id"] = int(user_id)
        if int(user_id) in failing:
            raise RuntimeError("injected traffic query failure")
        return 0

    monkeypatch.setattr(db, "get_user_daily_traffic", fake_daily_traffic)
    monkeypatch.setattr(
        credits_repository, "invalidate_user_credits", lambda cache_keys: None
    )


# ----------------------------------------------------------------------------
# 复现测试（修复前失败）
# ----------------------------------------------------------------------------


def test_rerun_same_day_does_not_double_pay(session_env, monkeypatch):
    _seed_plex_user(101, tg_id=1, credits=10.0)
    _seed_stats(1, credits=50.0)
    _install(monkeypatch, durations={101: 2.0})

    wr_service.update_plex_credits()
    first = _tg_credits(1)
    assert first == 52.0  # 2 小时 → 2 积分

    wr_service.update_plex_credits()
    assert _tg_credits(1) == 52.0  # 重跑不得再发


def test_premium_traffic_overdraft_continues(session_env, monkeypatch):
    # A 余额 1，会员流量费 30；B 排在后面照常结算
    _seed_plex_user(101, tg_id=1, credits=1.0, premium=1)
    _seed_plex_user(102, tg_id=2, credits=10.0)
    _seed_stats(1, credits=1.0)
    _seed_stats(2, credits=10.0)
    _install(
        monkeypatch,
        durations={101: 0.0, 102: 1.0},
        traffic_costs={101: 30.0, 102: 0.0},
    )

    _notifications, deductions = wr_service.update_plex_credits()

    assert _tg_credits(1) == -29.0  # 全额透支扣除
    assert _tg_credits(2) == 11.0  # 后续用户照常
    assert any(d["tg_id"] == 1 and d["deducted_credits"] == 30.0 for d in deductions)


def test_single_user_failure_isolates(session_env, monkeypatch):
    _seed_plex_user(101, tg_id=1, credits=10.0)
    _seed_plex_user(102, tg_id=2, credits=10.0)  # 注入失败的用户
    _seed_plex_user(103, tg_id=3, credits=10.0)
    for tg in (1, 2, 3):
        _seed_stats(tg, credits=10.0)
    _install(
        monkeypatch,
        durations={101: 1.0, 102: 1.0, 103: 1.0},
        fail_plex_ids={102},
    )

    wr_service.update_plex_credits()

    assert _tg_credits(1) == 11.0  # 失败用户之前
    assert _tg_credits(2) == 10.0  # 失败用户本身无变化
    assert _tg_credits(3) == 11.0  # 失败用户之后照常


def test_failed_user_keeps_ghost_compensation(session_env, monkeypatch):
    _seed_plex_user(101, tg_id=1, credits=10.0)
    _seed_plex_user(102, tg_id=2, credits=10.0)
    for tg in (1, 2):
        _seed_stats(tg, credits=10.0)
    _seed_ghost(101, hours=1.0)
    _seed_ghost(102, hours=1.0)
    _install(
        monkeypatch,
        durations={101: 0.0, 102: 0.0},
        fail_plex_ids={102},
    )

    wr_service.update_plex_credits()

    with get_session() as session:
        rows = {
            int(r.user_id): int(r.compensated)
            for r in session.execute(select(GhostSessionLog)).scalars()
        }
    assert rows == {101: 1, 102: 0}  # 成功的标记，失败的保留


def test_inviter_notification_shows_actual_balance(session_env, monkeypatch):
    _seed_plex_user(101, tg_id=11, credits=0.0)
    _seed_stats(11, credits=10.0)
    _seed_stats(99, credits=100.0)  # 邀请人
    _seed_inviter(99, 101)
    _install(monkeypatch, durations={101: 2.0})

    notifications, _deductions = wr_service.update_plex_credits()

    assert _tg_credits(99) == 100.2  # 2 积分的 10%
    inviter_messages = [text for chat, text in notifications if chat == 99]
    assert inviter_messages, "邀请人应收到汇总通知"
    assert "当前总积分: 100.2" in inviter_messages[0]


def test_deduction_summary_lists_committed_only(session_env, monkeypatch):
    _seed_plex_user(101, tg_id=1, credits=1.0, premium=1)
    _seed_plex_user(102, tg_id=2, credits=5.0, premium=1)
    _seed_stats(1, credits=1.0)
    _seed_stats(2, credits=5.0)
    _install(
        monkeypatch,
        durations={101: 0.0, 102: 0.0},
        traffic_costs={101: 2.0, 102: 3.0},
        fail_plex_ids={102},
    )

    _notifications, deductions = wr_service.update_plex_credits()

    listed = {d["tg_id"] for d in deductions}
    assert listed == {1}  # 只有已提交的扣费


# ----------------------------------------------------------------------------
# 修复前后都成立的行为（防回归）
# ----------------------------------------------------------------------------


def test_normal_settlement_pays_credits(session_env, monkeypatch):
    _seed_plex_user(101, tg_id=1, credits=10.0)
    _seed_stats(1, credits=10.0)
    _install(monkeypatch, durations={101: 2.0})

    wr_service.update_plex_credits()

    assert _tg_credits(1) == 12.0
    assert float(_plex_row(101).watched_time) == 2.0
