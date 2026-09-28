"""夺宝现行行为：参与、满员开奖、创建、取消退款与自动开期调度。

提升之前用这些用例固定当前实现的结果（`promote-activity-domains` 任务
1.3）。外部副作用（群通知、调度提交）用替身记录，ETH 取块哈希用替身，
使开奖随机数可复现。
"""

from __future__ import annotations

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import event, select
from sqlalchemy.exc import NoResultFound
from starlette.requests import Request

from app.core.db import get_session
from app.core.schemas import TelegramUser
from app.databases import db
from app.domains.identity.models import Statistics
from app.domains.treasure import jobs as treasure_jobs
from app.domains.treasure import router as tr
from app.domains.treasure.models import TreasureIssue, TreasureParticipation
from app.domains.treasure.schemas import TreasureCreateIssueRequest, TreasureJoinRequest
from app.integrations import eth_rpc
from tests.conftest import add_user, next_id

ADMIN = TelegramUser(id=123456789, first_name="admin", username="admin")


def _assign_row_id(mapper, connection, target) -> None:  # pragma: no cover - hook
    if target.id is None:
        target.id = next_id()


# SQLite 上 BIGINT 主键不自增，生产代码插入的行在 flush 前补 id
event.listen(TreasureIssue, "before_insert", _assign_row_id)
event.listen(TreasureParticipation, "before_insert", _assign_row_id)


def _user(tg_id: int) -> TelegramUser:
    return TelegramUser(id=tg_id, first_name=f"u{tg_id}", username=f"u{tg_id}")


def _request() -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/api", "headers": []})
    request.state.telegram_data = {}
    return request


def _credits(tg_id: int) -> float:
    with get_session() as session:
        row = session.get(Statistics, int(tg_id))
        assert row is not None
        return float(row.credits)


def _issue(issue_id: int) -> dict:
    with get_session() as session:
        row = session.get(TreasureIssue, int(issue_id))
        assert row is not None
        return {
            "id": int(row.id),
            "status": int(row.status),
            "shares_sold": int(row.shares_sold),
            "total_shares": int(row.total_shares),
            "prize_credits": int(row.prize_credits),
            "winner_tg_id": int(row.winner_tg_id) if row.winner_tg_id else None,
            "winner_number": int(row.winner_number) if row.winner_number else None,
            "external_random_b": row.external_random_b,
        }


def _participations(issue_id: int) -> list[dict]:
    with get_session() as session:
        rows = (
            session.execute(
                select(TreasureParticipation)
                .where(TreasureParticipation.issue_id == int(issue_id))
                .order_by(TreasureParticipation.id)
            )
            .scalars()
            .all()
        )
        return [
            {
                "tg_id": int(row.tg_id),
                "lucky_number": int(row.lucky_number),
                "cost_credits": int(row.cost_credits),
            }
            for row in rows
        ]


@pytest.fixture
def treasure_env(monkeypatch):
    """替身：ETH、群通知、自动开期调度、显示名。"""
    calls: dict[str, list] = {
        "settled": [],
        "progress": [],
        "created": [],
        "reopen": [],
    }

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(eth_rpc, "latest_block_hash_int", _noop)
    monkeypatch.setattr(
        tr,
        "notify_treasure_not_full_after_join",
        lambda **kwargs: calls["progress"].append(kwargs) or _noop(),
    )
    monkeypatch.setattr(
        tr,
        "notify_treasure_settled",
        lambda **kwargs: calls["settled"].append(kwargs) or _noop(),
    )
    monkeypatch.setattr(
        tr,
        "notify_treasure_issue_created",
        lambda **kwargs: calls["created"].append(kwargs) or _noop(),
    )
    monkeypatch.setattr(
        tr,
        "schedule_auto_reopen_treasure_issue",
        lambda *, source_issue_id: calls["reopen"].append(int(source_issue_id)),
    )
    monkeypatch.setattr(
        treasure_jobs,
        "notify_treasure_issue_created",
        lambda **kwargs: calls["created"].append(kwargs) or _noop(),
    )
    return calls


def _join(issue_id: int, tg_id: int, quantity: int = 1):
    return tr.join_issue(
        request=_request(),
        issue_id=issue_id,
        background_tasks=BackgroundTasks(),
        data=TreasureJoinRequest(quantity=quantity),
        current_user=_user(tg_id),
    )


def _create_issue(**overrides) -> int:
    payload = {
        "title": "issue",
        "description": "d",
        "prize_credits": 50,
        "total_credits_required": 100,
        "credits_per_share": 10,
        "start_number": 10_000_001,
    }
    payload.update(overrides)
    return db.create_treasure_issue(**payload)


# --------------------------------------------------------------------------- #
# 参与
# --------------------------------------------------------------------------- #


async def test_join_below_full_deducts_credits_and_notifies_progress(
    orm, treasure_env
) -> None:
    issue_id = _create_issue()
    add_user(orm, 1, credits=100.0)

    result = await _join(issue_id, 1)

    assert result.success is True
    assert result.settled is False
    assert result.winner_number is None
    assert _credits(1) == 90.0
    records = _participations(issue_id)
    assert len(records) == 1
    assert records[0]["tg_id"] == 1
    assert records[0]["cost_credits"] == 10
    assert 10_000_001 <= records[0]["lucky_number"] <= 10_000_010
    assert _issue(issue_id)["shares_sold"] == 1
    assert len(treasure_env["progress"]) == 1
    assert treasure_env["progress"][0]["joiner_tg_id"] == 1


async def test_join_rejects_insufficient_credits_without_side_effects(
    orm, treasure_env
) -> None:
    issue_id = _create_issue()
    add_user(orm, 2, credits=5.0)

    with pytest.raises(HTTPException) as excinfo:
        await _join(issue_id, 2)

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "积分不足"
    assert _credits(2) == 5.0
    assert _participations(issue_id) == []
    assert _issue(issue_id)["shares_sold"] == 0


async def test_join_rejections_report_issue_state(orm, treasure_env) -> None:
    active = _create_issue()
    closed = _create_issue(prize_credits=15, total_credits_required=20)
    db.cancel_treasure_issue(issue_id=closed)
    add_user(orm, 1, credits=100.0)

    with pytest.raises(HTTPException) as missing:
        await _join(999_999, 1)
    assert (missing.value.status_code, missing.value.detail) == (404, "期数不存在")

    with pytest.raises(HTTPException) as inactive:
        await _join(closed, 1)
    assert (inactive.value.status_code, inactive.value.detail) == (400, "本期已结束")

    # 被遮蔽分支：缺少统计行时仓储抛 "user stats not found"，路由先匹配 "not found"
    with pytest.raises(HTTPException) as shadowed:
        await _join(active, 3)
    assert (shadowed.value.status_code, shadowed.value.detail) == (404, "期数不存在")


# --------------------------------------------------------------------------- #
# 满员开奖
# --------------------------------------------------------------------------- #


# 说明：`join_treasure_issue` 在开奖查询前不 flush（会话 autoflush=False），
# 同一事务里刚插入的参与行对开奖查询不可见。所以开奖用例预置一条已落库的
# 参与记录，并让中奖号来自这条记录；填满的那次参与赢的情况由缺陷用例覆盖。
def _seed_partially_filled_issue(*, committed_ms: int) -> int:
    """预置 1/2 份、号码为起始号的已落库参与记录。"""
    issue_id = _create_issue(prize_credits=15, total_credits_required=20)
    with get_session() as session:
        session.get(TreasureIssue, issue_id).shares_sold = 1
        session.add(
            TreasureParticipation(
                issue_id=issue_id,
                tg_id=1,
                lucky_number=10_000_001,
                cost_credits=10,
                created_at_ms=committed_ms,
            )
        )
    return issue_id


async def test_full_issue_settlement_pays_winner_and_schedules_reopen(
    orm, treasure_env, monkeypatch
) -> None:
    issue_id = _seed_partially_filled_issue(committed_ms=1000)
    add_user(orm, 1, credits=100.0)
    add_user(orm, 2, credits=100.0)

    async def _block_hash():
        return 0

    monkeypatch.setattr(eth_rpc, "latest_block_hash_int", _block_hash)

    result = await _join(issue_id, 2)

    # A = 1000（已落库行），B = 0 → 中奖号 = 起始号，由已落库的 user 1 持有
    assert result.settled is True
    assert result.winner_tg_id == 1
    assert result.winner_number == 10_000_001
    issue = _issue(issue_id)
    assert issue["status"] == 2
    assert _credits(1) == 115.0  # 预置的 10 分未从余额扣；开奖 +15
    assert _credits(2) == 90.0
    assert len(treasure_env["settled"]) == 1
    assert treasure_env["settled"][0]["winner_tg_id"] == 1
    assert treasure_env["reopen"] == [issue_id]


def test_settlement_winner_number_derives_from_created_at_and_b(
    orm, treasure_env
) -> None:
    issue_id = _seed_partially_filled_issue(committed_ms=1000)
    add_user(orm, 1, credits=100.0)
    add_user(orm, 2, credits=100.0)

    result = db.join_treasure_issue(
        issue_id=issue_id, tg_id=2, external_random_b=0, timestamp_ms=2000
    )

    assert result["settled"] is True
    assert result["winner_number"] == 10_000_001
    assert result["winner_tg_id"] == 1
    assert _issue(issue_id)["external_random_b"] == 0
    assert _credits(1) == 115.0


def test_settlement_cannot_see_the_filling_participation(orm, treasure_env) -> None:
    """已知缺陷：开奖查询发生在同一事务 flush 之前。

    把中奖号推到填满的那次参与上（A = 1001，B = 0 → 偏移 1），中奖行尚未
    flush，查询取不到 → 抛 NoResultFound，整次参与失败、全部回滚。
    """
    issue_id = _seed_partially_filled_issue(committed_ms=1001)
    add_user(orm, 1, credits=100.0)
    add_user(orm, 2, credits=100.0)

    with pytest.raises(NoResultFound):
        db.join_treasure_issue(
            issue_id=issue_id, tg_id=2, external_random_b=0, timestamp_ms=2000
        )

    assert _participations(issue_id) == [
        {"tg_id": 1, "lucky_number": 10_000_001, "cost_credits": 10}
    ]


async def test_settlement_defect_surfaces_as_500_and_rolls_back(
    orm, treasure_env, monkeypatch
) -> None:
    issue_id = _seed_partially_filled_issue(committed_ms=1001)
    add_user(orm, 1, credits=100.0)
    add_user(orm, 2, credits=100.0)

    async def _block_hash():
        return 0

    monkeypatch.setattr(eth_rpc, "latest_block_hash_int", _block_hash)

    with pytest.raises(HTTPException) as excinfo:
        await _join(issue_id, 2)

    assert (excinfo.value.status_code, excinfo.value.detail) == (500, "参与失败")
    assert _credits(2) == 100.0  # 扣费已回滚
    assert _issue(issue_id)["shares_sold"] == 1
    assert treasure_env["settled"] == []


# --------------------------------------------------------------------------- #
# 创建与取消退款
# --------------------------------------------------------------------------- #


async def test_create_issue_persists_fields_and_notifies(orm, treasure_env) -> None:
    result = await tr.create_issue(
        request=_request(),
        data=TreasureCreateIssueRequest(
            title="new issue",
            description="d",
            prize_credits=50,
            total_credits_required=100,
            credits_per_share=10,
            start_number=10_000_001,
        ),
        current_user=ADMIN,
    )

    issue_id = result["issue_id"]
    issue = _issue(issue_id)
    assert result["success"] is True
    assert issue["total_shares"] == 10
    assert issue["status"] == 1
    assert issue["shares_sold"] == 0
    assert len(treasure_env["created"]) == 1
    assert treasure_env["created"][0]["issue_id"] == issue_id


async def test_cancel_issue_refunds_participants(orm, treasure_env) -> None:
    issue_id = _create_issue()
    add_user(orm, 1, credits=100.0)
    await _join(issue_id, 1, quantity=2)
    assert _credits(1) == 80.0

    result = await tr.cancel_issue(
        request=_request(), issue_id=issue_id, current_user=ADMIN
    )

    assert result["success"] is True
    assert result["refunded_total"] == 20.0
    assert result["refunded_users"] == 1
    assert result["participation_count"] == 2
    assert _credits(1) == 100.0
    assert _participations(issue_id) == []
    assert _issue(issue_id)["status"] == 3
    assert _issue(issue_id)["shares_sold"] == 0


# --------------------------------------------------------------------------- #
# 自动开期调度
# --------------------------------------------------------------------------- #


def test_schedule_auto_reopen_registers_named_task(treasure_env, monkeypatch) -> None:
    from app.core import scheduler

    calls: list[dict] = []
    monkeypatch.setattr(
        scheduler,
        "schedule_task",
        lambda task_id, **kwargs: calls.append({"task_id": task_id, **kwargs}),
    )

    treasure_jobs.schedule_auto_reopen_treasure_issue(source_issue_id=42)

    assert len(calls) == 1
    assert calls[0]["task_id"] == "treasure.open_next_issue"
    assert calls[0]["job_id"] == "treasure_auto_reopen_42"
    assert calls[0]["kwargs"] == {"source_issue_id": 42}
    assert calls[0]["misfire_grace_time"] == 60


async def test_auto_reopen_job_clones_settled_issue(orm, treasure_env) -> None:
    issue_id = _seed_partially_filled_issue(committed_ms=1000)
    add_user(orm, 1, credits=100.0)
    add_user(orm, 2, credits=100.0)
    db.join_treasure_issue(issue_id=issue_id, tg_id=2, external_random_b=0)
    assert _issue(issue_id)["status"] == 2

    await treasure_jobs._auto_create_next_treasure_issue_from(source_issue_id=issue_id)

    with get_session() as session:
        cloned = (
            session.execute(select(TreasureIssue).where(TreasureIssue.id != issue_id))
            .scalars()
            .all()
        )
        assert len(cloned) == 1
        assert int(cloned[0].status) == 1
        assert int(cloned[0].prize_credits) == 15
        assert int(cloned[0].total_credits_required) == 20
    assert len(treasure_env["created"]) == 1


async def test_auto_reopen_job_skips_unsettled_source(orm, treasure_env) -> None:
    issue_id = _create_issue()

    await treasure_jobs._auto_create_next_treasure_issue_from(source_issue_id=issue_id)

    with get_session() as session:
        rows = session.execute(select(TreasureIssue)).scalars().all()
        assert len(rows) == 1
