"""fix-live-defects D8：竞拍结束只扣一次分、流拍、恢复与出价。

修复前：结束不检查是否已结束、不加锁，重复结束重复扣分；最高出价无
同价裁定；流拍时尝试私信 ``None`` 得主；启动恢复只处理 50 场。
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import event

from app.core.db import get_session
from app.domains.auction import service as auction_service
from app.domains.auction.models import AuctionBids, Auctions
from app.domains.identity.models import Statistics
from tests.conftest import next_id


def _assign_row_id(mapper, connection, target) -> None:  # pragma: no cover - hook
    if target.id is None:
        target.id = next_id()


for _model in (Auctions, AuctionBids):
    event.listen(_model, "before_insert", _assign_row_id)


def _seed_stats(tg_id: int, credits: float = 100.0) -> None:
    with get_session() as session:
        session.add(Statistics(tg_id=tg_id, credits=credits, donation=0.0))


def _seed_auction(*, end_offset: int = 3600, active: int = 1) -> int:
    now = int(time.time())
    with get_session() as session:
        auction = Auctions(
            title="test auction",
            description="d",
            starting_price=1.0,
            current_price=1.0,
            end_time=now + end_offset,
            created_by=1,
            created_at=now,
            is_active=active,
            bid_count=0,
        )
        session.add(auction)
        session.flush()
        return int(auction.id)


def _seed_bid(auction_id: int, bidder_id: int, amount: float, bid_time: int) -> None:
    with get_session() as session:
        session.add(
            AuctionBids(
                auction_id=auction_id,
                bidder_id=bidder_id,
                bid_amount=amount,
                bid_time=bid_time,
            )
        )


def _credits(tg_id: int) -> float:
    with get_session() as session:
        return float(session.get(Statistics, int(tg_id)).credits)


@pytest.fixture
def silent_notifications(monkeypatch):
    from app.domains.auction import notifications as auction_notifications

    sent: list[dict] = []

    async def _fake_send(*args, **kwargs):
        sent.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(auction_notifications, "send_message_by_url", _fake_send)
    monkeypatch.setattr(
        auction_notifications, "send_channel_auction_notification", _fake_send
    )
    return sent


async def test_finish_twice_deducts_once(
    session_env, silent_notifications, monkeypatch
):
    from app.domains.auction import repository as auction_repository

    _seed_stats(10, credits=100.0)
    auction_id = _seed_auction()
    _seed_bid(auction_id, 10, 5.0, int(time.time()) - 60)

    first = await auction_service.finish_auction(auction_id=auction_id)
    assert first[0] is True
    assert _credits(10) == 95.0

    # 模拟并发窗口：第二次调用在第一个事务提交前读到的仍是“进行中”
    real_get = auction_repository.get_auction_by_id
    state = {"calls": 0}

    def stale_get(aid):
        data = dict(real_get(aid) or {})
        if state["calls"] == 0:
            state["calls"] += 1
            data["is_active"] = 1
        return data

    monkeypatch.setattr(auction_repository, "get_auction_by_id", stale_get)

    # 第二次结束（并发窗口）：不得再扣分
    with pytest.raises(Exception, match="已结束"):
        await auction_service.finish_auction(auction_id=auction_id)
    assert _credits(10) == 95.0


async def test_highest_bid_tiebreak_by_time(session_env, silent_notifications):

    _seed_stats(10, credits=100.0)
    _seed_stats(20, credits=100.0)
    auction_id = _seed_auction()
    base = int(time.time()) - 300
    # 同价：先出价的 20 号是较早的一条，后插入的记录 id 更大
    _seed_bid(auction_id, 10, 5.0, base + 100)
    _seed_bid(auction_id, 20, 5.0, base)

    await auction_service.finish_auction(auction_id=auction_id)

    assert _credits(20) == 95.0  # 较早出价者赢
    assert _credits(10) == 100.0


async def test_bidless_auction_sends_unsold_notice(session_env, silent_notifications):
    auction_id = _seed_auction()

    success, _winner = await auction_service.finish_auction(auction_id=auction_id)
    assert success is True

    direct_messages = [
        call for call in silent_notifications if call["args"][:1] == (None,)
    ]
    assert direct_messages == []  # 不得尝试通知不存在的得主


def test_restore_schedules_all_active_auctions(session_env, monkeypatch):
    scheduled: list[int] = []

    monkeypatch.setattr(
        auction_service,
        "schedule_finish",
        lambda *, auction_id, end_time: scheduled.append(int(auction_id)),
    )
    for i in range(60):
        _seed_auction(end_offset=3600 + i * 60)

    auction_service.restore_auction_schedules()

    assert len(scheduled) == 60


async def test_fallback_ends_expired_auction(session_env, silent_notifications):
    """兜底任务结束丢失调度的竞拍（SQLite 上修复前后行为一致的部分）。"""
    _seed_stats(10, credits=100.0)
    auction_id = _seed_auction(end_offset=-3600)  # 已过期
    _seed_bid(auction_id, 10, 5.0, int(time.time()) - 120)

    finished = await auction_service.finish_expired_auctions()

    assert any(item["id"] == auction_id for item in finished)
    assert _credits(10) == 95.0
