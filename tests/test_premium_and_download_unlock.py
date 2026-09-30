"""fix-live-defects D10/D11：会员购买原子性、到期任务、付费下载解锁。

修复前：
- 永久会员购买会员：先授予（返回 None）、再扣分，格式化 ``None`` 报错
  500，积分已扣。
- 到期任务：批量降级后再逐个处理；线路为 NULL 的用户让循环中止，其后
  的用户漏处理。
- 查询下载权限失败被当作未解锁，误撤销。
- 付费下载解锁：先扣分再写库；未绑定用户积分被扣、解锁失败。
"""

from __future__ import annotations

import time

import pytest
from fastapi import BackgroundTasks, HTTPException
from starlette.requests import Request

from app.core.db import get_session
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
from app.domains.media_access import router as ma_router
from app.domains.premium import router as premium_router
from app.domains.premium.router import PremiumUnlockRequest


class TelegramUserStub:
    def __init__(self, tg_id: int):
        self.id = tg_id
        self.first_name = "u"
        self.username = "u"


def _request(method: str = "POST") -> Request:
    request = Request({"type": "http", "method": method, "path": "/api", "headers": []})
    request.state.telegram_data = {}
    return request


def _seed_stats(tg_id: int, credits: float) -> None:
    with get_session() as session:
        session.add(Statistics(tg_id=tg_id, credits=credits, donation=0.0))


def _seed_premium_plex(
    tg_id: int, *, permanent: bool = False, expires_in: int = -3600
) -> None:
    with get_session() as session:
        session.add(
            PlexUser(
                plex_id=tg_id * 10,
                tg_id=tg_id,
                plex_email=f"{tg_id}@example.com",
                plex_username=f"plex{tg_id}",
                is_premium=1,
                premium_expiry_time=(
                    None if permanent else int(time.time()) + expires_in
                ),
            )
        )


def _credits(tg_id: int) -> float:
    with get_session() as session:
        return float(session.get(Statistics, int(tg_id)).credits)


@pytest.fixture
def silent_notifications(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    from app.domains.media_access import notifications as ma_notifications
    from app.domains.premium import notifications as premium_notifications

    monkeypatch.setattr(premium_notifications, "notify_premium_unlocked", _noop)
    monkeypatch.setattr(ma_notifications, "notify_download_unlocked", _noop)
    return _noop


# ---------------------------------------------------------------------------
# D10 购买
# ---------------------------------------------------------------------------


async def test_permanent_member_purchase_rejected_before_deduct(
    session_env, monkeypatch, silent_notifications
):
    from app.domains.premium import service as premium_service

    monkeypatch.setattr(premium_service, "is_premium_unlock_enabled", lambda: True)
    monkeypatch.setattr(
        "app.domains.premium.router.get_user_name_from_tg_id", lambda tg: "u"
    )
    _seed_stats(1, credits=100.0)
    _seed_premium_plex(1, permanent=True)

    with pytest.raises(HTTPException) as exc_info:
        await premium_router.unlock_premium.__wrapped__(
            _request(),
            BackgroundTasks(),
            PremiumUnlockRequest(service="plex", days=30, total_cost=240),
            user=TelegramUserStub(1),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "您已是永久 Premium 会员，无需续费"
    assert _credits(1) == 100.0  # 积分不变


async def test_purchase_deduct_failure_keeps_membership(
    session_env, monkeypatch, silent_notifications
):
    from app.domains.premium import service as premium_service

    monkeypatch.setattr(premium_service, "is_premium_unlock_enabled", lambda: True)
    monkeypatch.setattr(
        "app.domains.premium.router.get_user_name_from_tg_id", lambda tg: "u"
    )
    _seed_stats(1, credits=5.0)  # 积分不足
    _seed_premium_plex(1, permanent=False, expires_in=3600)

    with pytest.raises(HTTPException) as exc_info:
        await premium_router.unlock_premium.__wrapped__(
            _request(),
            BackgroundTasks(),
            PremiumUnlockRequest(service="plex", days=30, total_cost=240),
            user=TelegramUserStub(1),
        )
    assert exc_info.value.status_code == 400
    assert "积分不足" in exc_info.value.detail

    with get_session() as session:
        row = (
            session.execute(PlexUser.__table__.select().where(PlexUser.tg_id == 1))
            .mappings()
            .one()
        )
    # 会员状态没有被改动（原到期时间保持不变）
    assert row["premium_expiry_time"] is not None
    assert _credits(1) == 5.0


# ---------------------------------------------------------------------------
# D10 到期任务
# ---------------------------------------------------------------------------


async def test_expiry_handles_null_line_user(session_env, monkeypatch):
    from app.domains.premium import service as premium_service

    notified: list[int] = []

    async def _record(chat_id, *args, **kwargs):
        notified.append(chat_id)

    monkeypatch.setattr(premium_service, "send_message_by_url", _record)

    # 三个用户同时到期：1 号线路为空，2、3 号绑定高级线路
    now = int(time.time())
    premium_line = settings_premium_line()
    with get_session() as session:
        for tg in (1, 2, 3):
            session.add(Statistics(tg_id=tg, credits=0.0, donation=0.0))
        session.add(
            PlexUser(
                plex_id=11,
                tg_id=1,
                plex_email="a@x.com",
                plex_username="a",
                is_premium=1,
                premium_expiry_time=now - 100,
                plex_line=None,
            )
        )
        session.add(
            PlexUser(
                plex_id=12,
                tg_id=2,
                plex_email="b@x.com",
                plex_username="b",
                is_premium=1,
                premium_expiry_time=now - 100,
                plex_line=premium_line,
            )
        )
        session.add(
            EmbyUser(
                emby_id="u3",
                tg_id=3,
                emby_username="c",
                is_premium=1,
                premium_expiry_time=now - 100,
                emby_line=premium_line,
            )
        )

    await premium_service.check_premium_expiry()

    with get_session() as session:
        plex2 = (
            session.execute(PlexUser.__table__.select().where(PlexUser.tg_id == 2))
            .mappings()
            .one()
        )
        emby3 = (
            session.execute(EmbyUser.__table__.select().where(EmbyUser.tg_id == 3))
            .mappings()
            .one()
        )
    # 三人都被处理：降级、解绑、通知
    assert plex2["is_premium"] == 0 and plex2["plex_line"] is None
    assert emby3["is_premium"] == 0 and emby3["emby_line"] is None
    assert set(notified) == {1, 2, 3}


def settings_premium_line() -> str:
    from app.domains.lines import catalog

    premium_lines = catalog.premium_lines()
    return premium_lines[0] if premium_lines else "premium-line"


# ---------------------------------------------------------------------------
# D10 撤销下载权限
# ---------------------------------------------------------------------------


async def test_revoke_skipped_when_unlock_check_fails(session_env, monkeypatch):
    from app.domains.media_access import service as media_access_service
    from app.domains.premium import service as premium_service

    revoked: list[str] = []

    class FakePlex:
        def update_sync_for_user(self, email, allow_sync=False):
            revoked.append(email)

    monkeypatch.setattr("app.integrations.plex.Plex", lambda: FakePlex())

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(premium_service, "send_message_by_url", _noop)

    def broken_check(tg_id, service):
        raise RuntimeError("injected query failure")

    # 到期撤销路径中的权限检查失败
    monkeypatch.setattr(media_access_service, "is_download_unlocked", broken_check)
    monkeypatch.setattr(
        "app.domains.premium.service.is_download_unlocked", broken_check
    )

    now = int(time.time())
    _seed_stats(1, credits=0.0)
    with get_session() as session:
        session.add(
            PlexUser(
                plex_id=11,
                tg_id=1,
                plex_email="a@x.com",
                plex_username="a",
                is_premium=1,
                premium_expiry_time=now - 100,
            )
        )

    await premium_service.check_premium_expiry()

    assert revoked == []  # 查询失败时保守处理，不撤销


# ---------------------------------------------------------------------------
# D11 付费下载解锁
# ---------------------------------------------------------------------------


async def test_download_unlock_unbound_keeps_credits(
    session_env, monkeypatch, silent_notifications
):
    from app.domains.media_access import service as media_access_service

    monkeypatch.setattr(media_access_service, "get_download_unlock_credits", lambda: 50)
    _seed_stats(1, credits=100.0)  # 没有绑定任何媒体账号

    response = await ma_router.unlock_download_permission.__wrapped__(
        "plex", _request(), BackgroundTasks(), user=TelegramUserStub(1)
    )

    assert response.success is False
    assert response.message == "请先绑定 Plex/Emby 账户"
    assert _credits(1) == 100.0


async def test_download_unlock_already_unlocked_no_charge(
    session_env, monkeypatch, silent_notifications
):
    from app.domains.media_access import service as media_access_service

    monkeypatch.setattr(media_access_service, "get_download_unlock_credits", lambda: 50)
    _seed_stats(1, credits=100.0)
    with get_session() as session:
        session.add(
            PlexUser(
                plex_id=10,
                tg_id=1,
                plex_email="a@x.com",
                plex_username="a",
                sync_unlocked=1,
                sync_unlock_time=123,
            )
        )

    response = await ma_router.unlock_download_permission.__wrapped__(
        "plex", _request(), BackgroundTasks(), user=TelegramUserStub(1)
    )

    assert response.success is False
    assert "无需重复解锁" in response.message
    assert _credits(1) == 100.0
