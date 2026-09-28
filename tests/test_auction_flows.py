"""竞拍现行行为：出价、创建、修改、删除、手动结束与过期兜底。

提升之前固定当前实现（`promote-activity-domains` 任务 1.3），并把 design
「已知缺陷」的现状写成断言：
- 无人出价时结束流程会对 `send_message_by_url(None)` 发起调用；
- 结束竞拍不检查 `is_active`，重复结束会再次扣分；
- `finish_expired_auctions` 的 `group_by` 选了未聚合的 `bidder_id`（SQLite
  容忍并返回最大值所在行，PostgreSQL 直接报错）；
- 启动恢复只处理前 50 条。
"""

from __future__ import annotations

import time

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import event
from starlette.requests import Request

from app.core.db import get_session
from app.core.schemas import TelegramUser
from app.domains.auction import jobs as auction_jobs
from app.domains.auction import repository as auction_repository
from app.domains.auction import router as auc
from app.domains.auction import service as auction_service
from app.domains.auction.models import AuctionBids, Auctions
from app.domains.auction.schemas import CreateAuctionRequest, PlaceBidRequest
from app.domains.identity.models import Statistics
from tests.conftest import add_user, next_id

ADMIN = TelegramUser(id=123456789, first_name="admin", username="admin")
FUTURE = int(time.time()) + 86_400
PAST = int(time.time()) - 10


def _assign_row_id(mapper, connection, target) -> None:  # pragma: no cover - hook
    if target.id is None:
        target.id = next_id()


# SQLite 上 BIGINT 主键不自增
event.listen(Auctions, "before_insert", _assign_row_id)
event.listen(AuctionBids, "before_insert", _assign_row_id)


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


def _auction(auction_id: int) -> dict:
    with get_session() as session:
        row = session.get(Auctions, int(auction_id))
        assert row is not None
        return {
            "title": row.title,
            "current_price": float(row.current_price),
            "is_active": int(row.is_active),
            "winner_id": row.winner_id,
            "bid_count": int(row.bid_count),
        }


def _create_auction(**overrides) -> int:
    payload = {
        "title": "auction",
        "description": "d",
        "starting_price": 100.0,
        "end_time": FUTURE,
        "created_by": 99,
    }
    payload.update(overrides)
    auction_id = auction_repository.create_auction(**payload)
    assert auction_id is not None
    return int(auction_id)


@pytest.fixture
def auction_env(monkeypatch):
    """替身：调度器、TG 通知、显示名。"""
    calls: dict[str, list] = {"jobs": [], "sent": [], "channel": [], "bids": []}

    class _Recorder:
        def add_async_job(self, **kwargs):
            calls["jobs"].append({"op": "add", **kwargs})

        def add_job(self, **kwargs):
            calls["jobs"].append({"op": "add", **kwargs})

        def remove_job(self, job_id, **kwargs):
            calls["jobs"].append({"op": "remove", "job_id": job_id})

    async def _send(chat_id, text=None, **kwargs):
        calls["sent"].append(chat_id)

    async def _channel(text):
        calls["channel"].append(text)

    async def _bid_notifications(**kwargs):
        calls["bids"].append(kwargs)

    monkeypatch.setattr(auction_service, "Scheduler", _Recorder)
    monkeypatch.setattr(
        auction_service,
        "schedule_task",
        lambda task_id, **kwargs: calls["jobs"].append(
            {"op": "add", "task_id": task_id, **kwargs}
        ),
    )
    monkeypatch.setattr(
        auction_service.auction_notifications,
        "send_message_by_url",
        _send,
    )
    monkeypatch.setattr(
        auction_service.auction_notifications,
        "send_channel_auction_notification",
        _channel,
    )
    monkeypatch.setattr(
        auction_service.auction_notifications,
        "send_bid_notifications",
        _bid_notifications,
    )
    monkeypatch.setattr(
        auction_service.auction_notifications,
        "send_auction_created_notification",
        lambda **kwargs: _channel(kwargs["title"]),
    )
    return calls


async def _bid(auction_id: int, tg_id: int, amount: float, background_tasks=None):
    return await auc.place_bid(
        bid_request=PlaceBidRequest(auction_id=auction_id, bid_amount=amount),
        background_tasks=background_tasks or BackgroundTasks(),
        request=_request(),
        current_user=_user(tg_id),
    )


# --------------------------------------------------------------------------- #
# 创建、修改、删除
# --------------------------------------------------------------------------- #


async def test_create_auction_persists_and_schedules_finish(orm, auction_env) -> None:
    background_tasks = BackgroundTasks()

    result = await auc.create_auction(
        request_data=CreateAuctionRequest(
            title="new auction",
            description="d",
            starting_price=100.0,
            duration_hours=1,
        ),
        background_tasks=background_tasks,
        request=_request(),
        current_user=ADMIN,
    )

    auction_id = result["auction_id"]
    assert result["success"] is True
    stored = _auction(auction_id)
    assert stored["title"] == "new auction"
    assert stored["current_price"] == 100.0
    assert stored["is_active"] == 1
    jobs = [job for job in auction_env["jobs"] if job["op"] == "add"]
    assert len(jobs) == 1
    assert jobs[0]["task_id"] == "auction.finish"
    assert jobs[0]["job_id"] == f"finish_auction_{auction_id}"
    assert jobs[0]["kwargs"] == {"auction_id": auction_id}
    assert jobs[0]["jobstore"] == "default"
    assert len(background_tasks.tasks) == 0


async def test_update_auction_admin_updates_fields_and_reschedules(
    orm, auction_env
) -> None:
    auction_id = _create_auction()

    result = await auc.update_auction_admin(
        auction_id=auction_id,
        update_data=CreateAuctionRequest(
            title="renamed",
            description="new",
            starting_price=200.0,
            duration_hours=2,
        ),
        request=_request(),
        current_user=ADMIN,
    )

    assert result == {"success": True, "message": "竞拍更新成功"}
    stored = _auction(auction_id)
    assert stored["title"] == "renamed"
    operations = [job["op"] for job in auction_env["jobs"]]
    assert operations == ["remove", "add"]
    assert auction_env["jobs"][0]["job_id"] == f"finish_auction_{auction_id}"


async def test_delete_auction_admin_removes_row_and_job(orm, auction_env) -> None:
    auction_id = _create_auction()
    auction_repository.place_bid(auction_id=auction_id, bidder_id=1, bid_amount=150.0)

    result = await auc.delete_auction_admin(
        auction_id=auction_id, request=_request(), current_user=ADMIN
    )

    assert result == {"success": True, "message": "竞拍删除成功"}
    with get_session() as session:
        assert session.get(Auctions, auction_id) is None
    assert auction_env["jobs"] == [
        {"op": "remove", "job_id": f"finish_auction_{auction_id}"}
    ]


# --------------------------------------------------------------------------- #
# 出价
# --------------------------------------------------------------------------- #


async def test_place_bid_updates_price_and_records_bid(orm, auction_env) -> None:
    auction_id = _create_auction()
    add_user(orm, 1, credits=1000.0)
    background_tasks = BackgroundTasks()

    result = await _bid(auction_id, 1, 150.0, background_tasks)

    assert result.success is True
    assert result.current_price == 150.0
    assert result.user_credits == 1000.0
    stored = _auction(auction_id)
    assert stored["current_price"] == 150.0
    assert stored["bid_count"] == 1
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0].kwargs["bid_amount"] == 150.0


async def test_place_bid_rejections(orm, auction_env) -> None:
    active = _create_auction()
    inactive = _create_auction()
    auction_repository.finish_auction_by_id(inactive)
    expired = _create_auction(end_time=PAST)
    own = _create_auction(created_by=1)
    add_user(orm, 1, credits=1000.0)
    add_user(orm, 2, credits=5.0)

    with pytest.raises(HTTPException) as missing:
        await _bid(999_999, 1, 150.0)
    assert (missing.value.status_code, missing.value.detail) == (404, "竞拍不存在")

    with pytest.raises(HTTPException) as ended:
        await _bid(inactive, 1, 150.0)
    assert (ended.value.status_code, ended.value.detail) == (400, "竞拍已结束")

    with pytest.raises(HTTPException) as overdue:
        await _bid(expired, 1, 150.0)
    assert (overdue.value.status_code, overdue.value.detail) == (400, "竞拍已过期")

    with pytest.raises(HTTPException) as own_auction:
        await _bid(own, 1, 150.0)
    assert (own_auction.value.status_code, own_auction.value.detail) == (
        400,
        "不能对自己创建的竞拍出价",
    )

    with pytest.raises(HTTPException) as low:
        await _bid(active, 1, 50.0)
    assert (low.value.status_code, low.value.detail) == (
        400,
        "出价必须高于当前价格 100.0",
    )

    with pytest.raises(HTTPException) as ghost:
        await _bid(active, 3, 150.0)
    assert (ghost.value.status_code, ghost.value.detail) == (
        400,
        "无法获取用户积分信息",
    )

    with pytest.raises(HTTPException) as poor:
        await _bid(active, 2, 150.0)
    assert (poor.value.status_code, poor.value.detail) == (
        400,
        "积分不足，当前积分: 5.0，需要: 150.0",
    )


# --------------------------------------------------------------------------- #
# 手动结束与已知缺陷
# --------------------------------------------------------------------------- #


async def test_finish_auction_admin_deducts_winner(orm, auction_env) -> None:
    auction_id = _create_auction()
    add_user(orm, 1, credits=1000.0)
    auction_repository.place_bid(auction_id=auction_id, bidder_id=1, bid_amount=150.0)
    background_tasks = BackgroundTasks()

    result = await auc.finish_auction_admin(
        auction_id=auction_id,
        background_tasks=background_tasks,
        request=_request(),
        current_user=ADMIN,
    )

    assert result["success"] is True
    assert result["finished_auctions"][0]["winner_id"] == 1
    assert _credits(1) == 850.0
    stored = _auction(auction_id)
    assert stored["is_active"] == 0 and stored["winner_id"] == 1
    assert auction_env["sent"] == [1]
    assert len(background_tasks.tasks) == 0


async def test_finish_auction_without_bids_calls_send_message_with_none(
    orm, auction_env
) -> None:
    """已知缺陷：流拍时也调用 `send_message_by_url(None, …)`。"""
    auction_id = _create_auction()

    result = await auc.finish_auction_admin(
        auction_id=auction_id,
        background_tasks=BackgroundTasks(),
        request=_request(),
        current_user=ADMIN,
    )

    assert result["success"] is True
    assert result["finished_auctions"][0]["winner_id"] is None
    assert auction_env["sent"][0] is None


def test_finish_auction_by_id_twice_deducts_winner_again(orm, auction_env) -> None:
    """已知缺陷：仓储的 `finish_auction_by_id` 不检查 `is_active`，重复结束会再次
    扣分。路由与自动结束任务各自在外层拦了 `is_active`，所以只有直接调用仓储
    才能看到这一现状。
    """
    auction_id = _create_auction()
    add_user(orm, 1, credits=1000.0)
    auction_repository.place_bid(auction_id=auction_id, bidder_id=1, bid_amount=150.0)

    first, _ = auction_repository.finish_auction_by_id(auction_id)
    assert first is True
    assert _credits(1) == 850.0

    second, winner = auction_repository.finish_auction_by_id(auction_id)

    assert second is True
    assert winner["winner_id"] == 1
    assert _credits(1) == 700.0  # 第二次结束又扣了一次


async def test_finish_auction_admin_rejects_inactive_auction(orm, auction_env) -> None:
    auction_id = _create_auction()
    auction_repository.finish_auction_by_id(auction_id)

    with pytest.raises(HTTPException) as excinfo:
        await auc.finish_auction_admin(
            auction_id=auction_id,
            background_tasks=BackgroundTasks(),
            request=_request(),
            current_user=ADMIN,
        )

    assert (excinfo.value.status_code, excinfo.value.detail) == (400, "竞拍已结束")


# --------------------------------------------------------------------------- #
# 过期兜底与启动恢复
# --------------------------------------------------------------------------- #


async def test_finish_expired_auctions_job_notifies_none_winner(
    orm, auction_env
) -> None:
    """已知缺陷：兜底任务对无人出价的竞拍也发 `send_message_by_url(None, …)`。"""
    _create_auction(end_time=PAST)

    finished = await auction_jobs.finish_expired_auctions_job()

    assert [item["winner_id"] for item in finished] == [None]
    assert auction_env["sent"][0] is None


def test_finish_expired_auctions_group_by_returns_max_bidder_on_sqlite(
    orm, auction_env
) -> None:
    """已知缺陷：`group_by(auction_id)` 却选了 `bidder_id`。

    SQLite 容忍裸列并返回 `max()` 所在行（此处为最高出价者），PostgreSQL
    会因 `bidder_id` 不在 GROUP BY 中直接报错，使真个方法返回空列表。
    """
    auction_id = _create_auction()
    add_user(orm, 1, credits=1000.0)
    add_user(orm, 2, credits=1000.0)
    auction_repository.place_bid(auction_id=auction_id, bidder_id=1, bid_amount=150.0)
    auction_repository.place_bid(auction_id=auction_id, bidder_id=2, bid_amount=200.0)
    # `place_bid` 只接受未过期竞拍，先把出价写入再把结束时间改到过去
    with get_session() as session:
        session.get(Auctions, auction_id).end_time = PAST

    finished = auction_repository.finish_expired_auctions()

    assert len(finished) == 1
    assert finished[0]["winner_id"] == 2
    assert finished[0]["final_price"] == 200.0
    assert _credits(1) == 1000.0
    assert _credits(2) == 800.0
    assert _auction(auction_id)["is_active"] == 0


def test_restore_auction_schedules_limits_to_fifty(orm, auction_env) -> None:
    """已知缺陷：启动恢复只处理 `get_active_auctions()` 的前 50 条。"""
    with get_session() as session:
        for index in range(51):
            session.add(
                Auctions(
                    id=10_000 + index,
                    title=f"a{index}",
                    description="d",
                    starting_price=100.0,
                    current_price=100.0,
                    end_time=FUTURE,
                    created_by=99,
                    created_at=int(time.time()) + index,
                    is_active=1,
                    winner_id=None,
                    bid_count=0,
                )
            )

    auction_jobs.restore_auction_schedules()

    added = [job for job in auction_env["jobs"] if job["op"] == "add"]
    assert len(added) == 50
