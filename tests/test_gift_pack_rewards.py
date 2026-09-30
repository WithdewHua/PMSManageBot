"""礼包新增奖励类型的发放测试（openspec: expand-gift-pack-rewards）。

走公开路径 `claim_gift_pack`，验证各奖励分支在同一事务内与领取同生共死，
以及提交后副作用（下载权限同步）失败不回滚领取。
"""

from __future__ import annotations

import time

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import event, select
from starlette.requests import Request

from app.core.config import settings
from app.core.db import get_session
from app.core.kv import SystemConfig
from app.domains.accounts import service as accounts_service
from app.domains.gift_pack import repository as gift_pack_repository
from app.domains.gift_pack import service as gift_pack_service
from app.domains.gift_pack.models import GiftPack, GiftPackUserState
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
from app.domains.invitation.models import Invitation
from app.domains.invitation.schemas import RedeemInviteCodeRequest
from app.domains.luckywheel import repository as luckywheel_repository
from app.domains.luckywheel.models import LuckywheelFreeSpin, WheelStats
from app.transport.http.schemas import TelegramUser
from tests.conftest import add_user, get_stats, next_id


# SQLite 上 BIGINT 主键不会自增（见 conftest 注释），生产代码插入的行在
# flush 前补 id——只影响测试进程
@event.listens_for(GiftPack, "before_insert")
def _assign_pack_id(mapper, connection, target):
    if target.id is None:
        target.id = next_id()


@event.listens_for(GiftPackUserState, "before_insert")
def _assign_state_id(mapper, connection, target):
    if target.id is None:
        target.id = next_id()


@event.listens_for(SystemConfig, "before_insert")
def _assign_system_config_id(mapper, connection, target):
    if target.id is None:
        target.id = next_id()


@event.listens_for(WheelStats, "before_insert")
def _assign_wheel_stats_id(mapper, connection, target):
    if target.id is None:
        target.id = next_id()


def _pack(orm, rewards: list, **kwargs) -> int:
    now = int(time.time())
    return gift_pack_repository.create_gift_pack(
        "test pack", rewards, now - 10, now + 3600, **kwargs
    )


def _bind_plex(tg_id: int, **cols) -> None:
    with get_session() as session:
        session.add(
            PlexUser(
                plex_id=tg_id * 10,
                tg_id=tg_id,
                plex_email=f"{tg_id}@x",
                plex_username=f"p{tg_id}",
                **cols,
            )
        )


def _bind_emby(tg_id: int, **cols) -> None:
    with get_session() as session:
        session.add(EmbyUser(emby_username=f"e{tg_id}", tg_id=tg_id, **cols))


def _invitations(tg_id: int) -> list:
    with get_session() as session:
        return list(
            session.execute(select(Invitation.code).where(Invitation.owner == tg_id))
            .scalars()
            .all()
        )


def _user_col(model, tg_id: int, col: str):
    with get_session() as session:
        return session.execute(
            select(getattr(model, col)).where(model.tg_id == tg_id)
        ).scalar_one()


# ------------------------------------------------------ 大转盘免费机会


def test_wheel_free_spins_granted_with_gift_pack_source(orm):
    add_user(orm, 1)
    pack = _pack(orm, [{"type": "wheel_free_spins", "count": 3, "expiry_days": 7}])
    before = int(time.time())

    result = gift_pack_service.claim_gift_pack(pack, 1)

    assert luckywheel_repository.free_spin_summary(1)["available"] == 3
    item = result["results"][0]
    assert item["count"] == 3
    assert before + 7 * 86400 <= item["expires_at"] <= int(time.time()) + 7 * 86400
    with get_session() as session:
        rows = session.query(LuckywheelFreeSpin).filter_by(tg_id=1).all()
        assert {r.source for r in rows} == {"gift_pack"}
        assert all(r.expires_at_ms - r.granted_at_ms == 7 * 86400 * 1000 for r in rows)


def test_gift_pack_free_spins_not_notified_and_not_capped(orm):
    add_user(orm, 1)
    pack = _pack(orm, [{"type": "wheel_free_spins", "count": 5, "expiry_days": 7}])
    luckywheel_repository.claim_unnotified_blackjack_freespins()  # 初始化游标
    gift_pack_service.claim_gift_pack(pack, 1)

    with get_session() as session:
        session.execute(
            LuckywheelFreeSpin.__table__.update().values(
                granted_at_ms=int(time.time() * 1000) - 5 * 60 * 1000
            )
        )
    assert luckywheel_repository.claim_unnotified_blackjack_freespins() == []


# ------------------------------------------------------ 争霸赛余额


def test_tournament_wallet_credited_not_credits(orm):
    add_user(orm, 1, credits=100.0)
    with get_session() as session:
        session.get(Statistics, 1).tournament_wallet_credits = 10.0
    pack = _pack(
        orm,
        [
            {"type": "credits", "amount": 5},
            {"type": "tournament_wallet", "amount": 50},
        ],
    )

    result = gift_pack_service.claim_gift_pack(pack, 1)

    stats = get_stats(1)
    assert stats["tournament_wallet_credits"] == 60.0
    assert stats["credits"] == 105.0
    wallet = next(r for r in result["results"] if r["type"] == "tournament_wallet")
    assert wallet["amount"] == 50
    assert wallet["balance_after"] == 60.0


# ------------------------------------------------------ 功能解锁


def test_download_unlock_for_premium_user_sets_permanent_flag(orm, monkeypatch):
    synced = []
    monkeypatch.setattr(
        "app.domains.premium.service.apply_download_unlock_to_media",
        lambda tg_id, service: synced.append((tg_id, service)),
        raising=False,
    )
    add_user(orm, 1)
    _bind_plex(1, is_premium=1, premium_expiry_time="2099-01-01T00:00:00")
    pack = _pack(orm, [{"type": "download_unlock"}])

    gift_pack_service.claim_gift_pack(pack, 1)

    assert _user_col(PlexUser, 1, "sync_unlocked") == 1


def test_line_schedule_unlock_skips_already_unlocked_service(orm):
    add_user(orm, 1)
    _bind_plex(1)
    _bind_emby(1, line_schedule_unlocked=1)
    pack = _pack(orm, [{"type": "line_schedule_unlock"}])

    result = gift_pack_service.claim_gift_pack(pack, 1)

    by_service = {r["service"]: r for r in result["results"]}
    assert by_service["emby"]["skipped"] == "already_unlocked"
    assert not by_service["plex"].get("skipped")
    assert _user_col(PlexUser, 1, "line_schedule_unlocked") == 1
    with get_session() as session:
        state = session.query(GiftPackUserState).filter_by(pack_id=pack).one()
        assert state.claimed_at


def test_unlock_requires_binding(orm):
    add_user(orm, 1)
    pack = _pack(orm, [{"type": "line_schedule_unlock"}])

    with pytest.raises(ValueError):
        gift_pack_service.claim_gift_pack(pack, 1)


# ------------------------------------------------------ 邀请码


def test_invite_codes_generated_and_in_snapshot(orm):
    add_user(orm, 1)
    pack = _pack(orm, [{"type": "invite_codes", "count": 20}])

    result = gift_pack_service.claim_gift_pack(pack, 1)

    codes = result["results"][0]["codes"]
    assert len(codes) == 20 == len(set(codes))
    assert all(len(c) == 32 for c in codes)
    assert sorted(_invitations(1)) == sorted(codes)

    # 已领取礼包的发放内容中可再次查看
    listed = next(
        p for p in gift_pack_repository.get_gift_packs_for_user(1) if p["id"] == pack
    )
    assert listed["reward_snapshot"][0]["codes"] == codes


def test_invite_codes_rolled_back_when_other_reward_fails(orm, monkeypatch):
    add_user(orm, 1)
    pack = _pack(
        orm,
        [
            {"type": "invite_codes", "count": 2},
            {"type": "tournament_wallet", "amount": 10},
        ],
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        gift_pack_repository.GiftPackRepository,
        "_grant_tournament_wallet_tx",
        staticmethod(_boom),
    )

    with pytest.raises(RuntimeError):
        gift_pack_service.claim_gift_pack(pack, 1)

    assert _invitations(1) == []
    with get_session() as session:
        assert session.get(GiftPack, pack).claimed_count == 0


# ------------------------------------------------------ 特权邀请码与提交后副作用


def test_privileged_invite_stored_in_database_and_rolls_back_on_failure(
    orm, monkeypatch
):
    add_user(orm, 1)
    pack = _pack(
        orm,
        [
            {"type": "invite_codes", "count": 2, "privileged": True},
            {"type": "invalid_type", "count": 1},
        ],
    )
    saves = []

    def _capture_save(self, config_data, *, raise_on_error=False):
        saves.append(dict(config_data))

    monkeypatch.setattr(
        type(settings), "save_config_to_env_file", _capture_save, raising=False
    )

    with pytest.raises(ValueError, match="不支持的奖励类型"):
        gift_pack_service.claim_gift_pack(pack, 1)

    assert saves == []
    assert _invitations(1) == []
    with get_session() as session:
        persisted_pack = session.get(GiftPack, pack)
        assert persisted_pack.claimed_count == 0
        assert session.query(GiftPackUserState).filter_by(pack_id=pack).count() == 0


@pytest.mark.asyncio
async def test_privileged_invite_allows_registration_without_writing_env(
    orm, monkeypatch
):
    add_user(orm, 1)
    pack = _pack(
        orm,
        [{"type": "invite_codes", "count": 1, "privileged": True}],
    )
    saves = []
    accounts_service.set_registration_enabled("emby", False)
    monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [])

    def _capture_save(self, config_data, *, raise_on_error=False):
        saves.append(dict(config_data))

    monkeypatch.setattr(
        type(settings), "save_config_to_env_file", _capture_save, raising=False
    )
    code = gift_pack_service.claim_gift_pack(pack, 1)["results"][0]["codes"][0]

    with get_session() as session:
        inv = session.get(Invitation, code)
        assert inv is not None
        assert inv.is_privileged == 1
        assert inv.is_used == 0

    from app.domains.invitation import router as invitation

    class FakeEmby:
        def get_uid_from_username(self, username):
            return None

        def add_user(self, *, username, password):
            return True, "emby-user-1"

    async def _send_message(**kwargs):
        return None

    monkeypatch.setattr(invitation, "Emby", FakeEmby)
    monkeypatch.setattr(invitation, "send_message_by_url", _send_message)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/invitation/redeem/emby",
            "headers": [],
        }
    )
    request.state.telegram_data = {}
    response = await invitation.redeem_emby_code(
        request=request,
        background_tasks=BackgroundTasks(),
        data=RedeemInviteCodeRequest(
            code=code,
            username="new-emby-user",
            password="secret",
        ),
        telegram_user=TelegramUser(id=2, first_name="test"),
    )

    assert response.success is True
    assert "new-emby-user" in response.message
    assert saves == []  # .env is never written
    with get_session() as session:
        inv = session.get(Invitation, code)
        assert inv.is_used == 1
        assert inv.is_privileged == 1  # 兑换后仍保留特权标记


def test_all_seven_reward_types_are_aggregated_in_stats(orm, monkeypatch):
    monkeypatch.setattr(
        "app.domains.premium.service.apply_download_unlock_to_media",
        lambda tg_id, service: None,
    )
    monkeypatch.setattr(
        "app.domains.premium.service.sync_premium_media_access", lambda *args: None
    )
    add_user(orm, 1)
    _bind_plex(1)
    _bind_emby(1)
    pack = _pack(
        orm,
        [
            {"type": "credits", "amount": 100},
            {"type": "premium_days", "days": 7},
            {"type": "wheel_free_spins", "count": 3, "expiry_days": 7},
            {"type": "tournament_wallet", "amount": 50},
            {"type": "invite_codes", "count": 2},
            {"type": "line_schedule_unlock"},
            {"type": "download_unlock"},
        ],
    )

    gift_pack_service.claim_gift_pack(pack, 1)

    totals = {
        item["type"]: item
        for item in gift_pack_repository.get_gift_pack_stats(pack)["reward_totals"]
    }
    assert set(totals) == {
        "credits",
        "premium_days",
        "wheel_free_spins",
        "tournament_wallet",
        "invite_codes",
        "line_schedule_unlock",
        "download_unlock",
    }
    assert (totals["credits"]["total"], totals["credits"]["grants"]) == (100, 1)
    assert (totals["premium_days"]["total"], totals["premium_days"]["grants"]) == (
        14,
        2,
    )
    assert (
        totals["wheel_free_spins"]["total"],
        totals["wheel_free_spins"]["grants"],
    ) == (3, 1)
    assert (
        totals["tournament_wallet"]["total"],
        totals["tournament_wallet"]["grants"],
    ) == (50, 1)
    assert (totals["invite_codes"]["total"], totals["invite_codes"]["grants"]) == (2, 1)
    assert (
        totals["line_schedule_unlock"]["total"],
        totals["line_schedule_unlock"]["grants"],
    ) == (2, 2)
    assert (
        totals["download_unlock"]["total"],
        totals["download_unlock"]["grants"],
    ) == (2, 2)


@pytest.mark.asyncio
async def test_download_sync_failure_keeps_claim_and_notifies_admin(orm, monkeypatch):
    add_user(orm, 1)
    _bind_plex(1)
    pack = _pack(orm, [{"type": "download_unlock"}])
    with get_session() as session:
        session.get(GiftPack, pack).title = "VIP <2026>"
    sync_attempts = []

    def _fail_sync(tg_id, service):
        sync_attempts.append((tg_id, service))
        raise RuntimeError("media <server> unavailable")

    monkeypatch.setattr(
        "app.domains.premium.service.apply_download_unlock_to_media", _fail_sync
    )

    from app.domains.gift_pack import notifications as gift_pack_notifications
    from app.domains.gift_pack import router as gift_pack_router

    detached = []
    admin_messages = []
    monkeypatch.setattr(gift_pack_notifications, "_notify_detached", detached.append)
    monkeypatch.setattr(
        gift_pack_notifications,
        "get_user_name_from_tg_id",
        lambda tg_id: "test<user>",
    )

    async def _capture_admin_message(text, **kwargs):
        admin_messages.append(text)

    monkeypatch.setattr(
        gift_pack_notifications,
        "notify_admins_by_url",
        _capture_admin_message,
    )

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/api/gift-packs/{pack}/claim",
            "headers": [],
        }
    )
    request.state.telegram_data = {}
    response = await gift_pack_router.claim_gift_pack(
        request=request,
        pack_id=pack,
        background_tasks=BackgroundTasks(),
        telegram_user=TelegramUser(id=1, first_name="test"),
    )

    assert response.success is True
    assert sync_attempts == [(1, "plex")]
    assert "同步到媒体服务器未完成" in response.results[0].message
    assert _user_col(PlexUser, 1, "sync_unlocked") == 1
    with get_session() as session:
        assert session.get(GiftPack, pack).claimed_count == 1

    assert len(detached) == 1
    await detached[0]
    assert len(admin_messages) == 1
    assert "需人工处理" in admin_messages[0]
    assert "领取已成功" in admin_messages[0]
    assert "整体回滚" not in admin_messages[0]
    assert "VIP &lt;2026&gt;" in admin_messages[0]
    assert "test&lt;user&gt;" in admin_messages[0]
    assert "media &lt;server&gt; unavailable" in admin_messages[0]


# ------------------------------------------------------ 奖励回滚、会员续期与通知


def _free_spin_count(tg_id: int) -> int:
    with get_session() as session:
        return session.query(LuckywheelFreeSpin).filter_by(tg_id=int(tg_id)).count()


ROLLBACK_REWARDS = [
    pytest.param({"type": "credits", "amount": 25}, id="credits"),
    pytest.param({"type": "premium_days", "days": 7}, id="premium_days"),
    pytest.param(
        {"type": "wheel_free_spins", "count": 2, "expiry_days": 5},
        id="wheel_free_spins",
    ),
    pytest.param({"type": "tournament_wallet", "amount": 20}, id="tournament_wallet"),
    pytest.param({"type": "download_unlock"}, id="download_unlock"),
    pytest.param({"type": "line_schedule_unlock"}, id="line_schedule_unlock"),
]


@pytest.mark.parametrize("reward", ROLLBACK_REWARDS)
def test_each_reward_rolls_back_when_a_later_reward_fails(orm, reward):
    """除邀请码外的每类奖励，在后续奖励发放失败时一并回滚。"""
    add_user(orm, 1)
    _bind_plex(1)
    pack = _pack(orm, [reward, {"type": "unsupported_reward"}])

    with pytest.raises(ValueError, match="不支持的奖励类型"):
        gift_pack_service.claim_gift_pack(pack, 1)

    stats = get_stats(1)
    assert stats["credits"] == 100.0
    assert stats["tournament_wallet_credits"] == 0.0
    assert _free_spin_count(1) == 0
    assert _user_col(PlexUser, 1, "is_premium") == 0
    assert _user_col(PlexUser, 1, "premium_expiry_time") is None
    assert _user_col(PlexUser, 1, "sync_unlocked") == 0
    assert _user_col(PlexUser, 1, "line_schedule_unlocked") == 0
    with get_session() as session:
        assert session.get(GiftPack, pack).claimed_count == 0
        assert session.query(GiftPackUserState).filter_by(pack_id=pack).count() == 0


def test_premium_days_reward_extends_active_membership_from_expiry(orm):
    from datetime import datetime, timedelta

    add_user(orm, 1)
    current = datetime.now(settings.TZ) + timedelta(days=30)
    _bind_plex(1, is_premium=1, premium_expiry_time=current.isoformat())
    pack = _pack(orm, [{"type": "premium_days", "days": 7}])

    item = gift_pack_service.claim_gift_pack(pack, 1)["results"][0]

    new_expiry = datetime.fromisoformat(item["new_expiry"])
    assert abs((new_expiry - (current + timedelta(days=7))).total_seconds()) < 120
    assert item["service"] == "plex"
    assert item.get("skipped") is None


def test_premium_days_reward_starts_membership_for_new_user(orm):
    from datetime import datetime, timedelta

    add_user(orm, 1)
    _bind_plex(1)
    pack = _pack(orm, [{"type": "premium_days", "days": 7}])

    before = datetime.now(settings.TZ)
    item = gift_pack_service.claim_gift_pack(pack, 1)["results"][0]

    new_expiry = datetime.fromisoformat(item["new_expiry"])
    assert abs((new_expiry - (before + timedelta(days=7))).total_seconds()) < 120
    assert _user_col(PlexUser, 1, "is_premium") == 1


def test_premium_days_reward_skips_lifetime_member(orm):
    add_user(orm, 1)
    _bind_plex(1, is_premium=1)  # 永久会员：没有到期时间
    pack = _pack(orm, [{"type": "premium_days", "days": 7}])

    item = gift_pack_service.claim_gift_pack(pack, 1)["results"][0]

    assert item["success"] is True
    assert item["skipped"] == "lifetime"
    assert "new_expiry" not in item
    assert "永久会员" in item["message"]
    assert _user_col(PlexUser, 1, "premium_expiry_time") is None


@pytest.mark.asyncio
async def test_claim_response_reports_lifetime_skip_in_message(orm, monkeypatch):
    from fastapi import BackgroundTasks
    from starlette.requests import Request

    from app.domains.gift_pack import router
    from app.transport.http.schemas import TelegramUser

    add_user(orm, 1)
    _bind_plex(1, is_premium=1)
    pack = _pack(orm, [{"type": "premium_days", "days": 7}])
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/api/gift-packs/{pack}/claim",
            "headers": [],
        }
    )
    request.state.telegram_data = {}

    response = await router.claim_gift_pack(
        request=request,
        pack_id=pack,
        background_tasks=BackgroundTasks(),
        telegram_user=TelegramUser(id=1, first_name="test"),
    )

    assert response.success is True
    assert response.message == "领取成功；Plex 为永久会员，Premium 天数部分未生效"


def test_privileged_code_rolls_back_with_claim_when_commit_fails(orm, monkeypatch):
    """当提交失败时，特权码与领取记录一起回滚，不写入 .env。"""
    from sqlalchemy.orm import Session

    add_user(orm, 1)
    pack = _pack(orm, [{"type": "invite_codes", "count": 1, "privileged": True}])
    saves: list[dict] = []

    def _capture_save(self, config_data, *, raise_on_error=False):
        saves.append(dict(config_data))

    monkeypatch.setattr(
        type(settings), "save_config_to_env_file", _capture_save, raising=False
    )

    def _fail_commit(self):
        raise RuntimeError("commit failed")

    with monkeypatch.context() as patcher:
        patcher.setattr(Session, "commit", _fail_commit)
        with pytest.raises(RuntimeError, match="commit failed"):
            gift_pack_service.claim_gift_pack(pack, 1)

    assert len(saves) == 0  # 没有写入 .env
    assert _invitations(1) == []
    with get_session() as session:
        assert session.get(GiftPack, pack).claimed_count == 0


@pytest.mark.asyncio
async def test_created_and_sold_out_notifications_are_queued_once(orm, monkeypatch):
    from fastapi import BackgroundTasks
    from starlette.requests import Request

    from app.domains.gift_pack import notifications, router
    from app.domains.gift_pack.schemas import GiftPackCreateRequest
    from app.transport.http.schemas import TelegramUser

    now = int(time.time())
    add_user(orm, 1)
    monkeypatch.setattr(router, "check_admin_permission", lambda user: None)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/gift-packs/admin",
            "headers": [],
        }
    )
    request.state.telegram_data = {}
    admin = TelegramUser(id=1, first_name="Admin")

    from app.domains.gift_pack import notifications as gift_pack_notifications

    created_calls: list = []
    monkeypatch.setattr(
        gift_pack_notifications, "_notify_detached", created_calls.append
    )
    created = await router.admin_create_gift_pack(
        request=request,
        background_tasks=BackgroundTasks(),
        data=GiftPackCreateRequest(
            title="限量礼包",
            rewards=[{"type": "credits", "amount": 5}],
            start_at=now - 10,
            end_at=now + 3600,
            total_quantity=1,
        ),
        telegram_user=admin,
    )
    # 创建通知在提交后立刻派发一次（不再依赖 FastAPI BackgroundTasks）
    assert len(created_calls) == 1
    await created_calls[0]

    sold_out_calls: list = []
    monkeypatch.setattr(
        gift_pack_notifications, "_notify_detached", sold_out_calls.append
    )
    await router.claim_gift_pack(
        request=request,
        pack_id=created.id,
        background_tasks=BackgroundTasks(),
        telegram_user=TelegramUser(id=1, first_name="test"),
    )
    # 限量领完只派发一次
    assert len(sold_out_calls) == 1
    await sold_out_calls[0]

    sent: list[str] = []

    async def _notify(text, **kwargs):
        sent.append(text)

    monkeypatch.setattr(notifications, "notify_admins_by_url", _notify)
    await notifications.notify_gift_pack_created(created.model_dump())
    assert "礼包已上线" in sent[0]
    assert "限量" in sent[0]
    assert "限量礼包" in sent[0]

    await notifications.notify_gift_pack_sold_out(created.id, "限量礼包", 1)
    assert "礼包已领完" in sent[1]
    assert "1 份已全部领取" in sent[1]


def test_premium_sync_runs_after_the_claim_commits(orm, monkeypatch):
    """媒体权限同步在提交后执行：同步时数据库里已经有领取记录。"""
    add_user(orm, 1)
    _bind_plex(1)
    pack = _pack(orm, [{"type": "premium_days", "days": 7}])

    observed: list[tuple[int, str, int]] = []

    def _record(tg_id, services=None):
        with get_session() as session:
            claimed = session.get(GiftPack, pack).claimed_count
        observed.extend(
            (int(tg_id), service, int(claimed)) for service in services or ()
        )

    monkeypatch.setattr(
        "app.domains.premium.service.sync_premium_media_access", _record
    )

    gift_pack_service.claim_gift_pack(pack, 1)

    assert observed == [(1, "plex", 1)]
    assert _user_col(PlexUser, 1, "is_premium") == 1
