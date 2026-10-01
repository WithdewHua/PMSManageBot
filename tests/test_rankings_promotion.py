"""Comprehensive tests for rankings domain promotion.

Covers:
- Task 1.3: Rankings behavior freeze (success, empty 200, 500 on failure, per-row profile fallback, bot commands)
- Task 3.1: Analysis function contrast tests (luckywheel, treasure, invitation)
- Task 3.2: Service parameterization, batch enrichment, and router integration
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from starlette.requests import Request

from app.core.config import settings
from app.core.db import get_session
from app.domains.badges.models import Badge, UserBadge
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
from app.domains.invitation import service as invitation_service
from app.domains.invitation.models import Invitation
from app.domains.luckywheel import service as luckywheel_service
from app.domains.luckywheel.models import WheelStats
from app.domains.rankings import bot as rankings_bot
from app.domains.rankings import repository as rankings_repository
from app.domains.rankings import router as rankings_router
from app.domains.rankings import service as rankings_service
from app.domains.treasure import service as treasure_service
from app.domains.treasure.models import TreasureIssue
from app.transport.http.schemas import TelegramUser


def _request() -> Request:
    request = Request({"type": "http", "method": "GET", "path": "/api", "headers": []})
    request.state.telegram_data = {}
    return request


# ==============================================================================
# 1. Task 3.1: Analysis function contrast tests
# ==============================================================================


def test_luckywheel_invite_code_rank_contrast(session_env) -> None:
    """luckywheel.service.get_wheel_invite_code_rank 结果与原 SQL 逐条一致。"""
    now = int(time.time())
    with get_session() as session:
        # User 101: 2 invite codes, 1 credits
        session.add(
            WheelStats(
                id=1,
                tg_id=101,
                item_name="邀请码 1 枚",
                credits_change=0,
                cost_credits=10,
                timestamp=now,
                date="2026-01-01",
            )
        )
        session.add(
            WheelStats(
                id=2,
                tg_id=101,
                item_name="邀请码 1 枚",
                credits_change=0,
                cost_credits=10,
                timestamp=now,
                date="2026-01-01",
            )
        )
        session.add(
            WheelStats(
                id=3,
                tg_id=101,
                item_name="10 积分",
                credits_change=10,
                cost_credits=10,
                timestamp=now,
                date="2026-01-01",
            )
        )
        # User 102: 1 invite code
        session.add(
            WheelStats(
                id=4,
                tg_id=102,
                item_name="邀请码 1 枚",
                credits_change=0,
                cost_credits=10,
                timestamp=now,
                date="2026-01-01",
            )
        )
        # User 103: 0 invite codes
        session.add(
            WheelStats(
                id=5,
                tg_id=103,
                item_name="50 积分",
                credits_change=50,
                cost_credits=10,
                timestamp=now,
                date="2026-01-01",
            )
        )

    # 原 SQL 逻辑
    with get_session() as session:
        invite_count = func.count(WheelStats.id).label("invite_count")
        stmt = (
            select(WheelStats.tg_id, invite_count)
            .where(WheelStats.item_name == "邀请码 1 枚")
            .group_by(WheelStats.tg_id)
            .order_by(invite_count.desc())
        )
        original_result = [
            (int(r[0]), int(r[1] or 0))
            for r in session.execute(stmt).fetchall()
            if int(r[1] or 0) > 0
        ]

    service_result = luckywheel_service.get_wheel_invite_code_rank()
    alias_result = luckywheel_service.invite_code_prize_counts()

    assert service_result == original_result
    assert alias_result == original_result
    assert service_result == [(101, 2), (102, 1)]


def test_treasure_analysis_functions_contrast(session_env) -> None:
    """treasure.service 中奖期数与积分排行结果与原 SQL 逐条一致。"""
    with get_session() as session:
        # Issue 1: settled (status=2), winner 201, prize 100
        session.add(
            TreasureIssue(
                id=1,
                title="T1",
                prize_credits=100,
                total_credits_required=100,
                credits_per_share=10,
                total_shares=10,
                start_number=1000,
                shares_sold=10,
                status=2,
                winner_tg_id=201,
                winner_number=1001,
            )
        )
        # Issue 2: settled (status=2), winner 201, prize 50
        session.add(
            TreasureIssue(
                id=2,
                title="T2",
                prize_credits=50,
                total_credits_required=50,
                credits_per_share=10,
                total_shares=5,
                start_number=2000,
                shares_sold=5,
                status=2,
                winner_tg_id=201,
                winner_number=2001,
            )
        )
        # Issue 3: settled (status=2), winner 202, prize 300
        session.add(
            TreasureIssue(
                id=3,
                title="T3",
                prize_credits=300,
                total_credits_required=300,
                credits_per_share=10,
                total_shares=30,
                start_number=3000,
                shares_sold=30,
                status=2,
                winner_tg_id=202,
                winner_number=3001,
            )
        )
        # Issue 4: active (status=1), winner_tg_id set (should be ignored by status=2)
        session.add(
            TreasureIssue(
                id=4,
                title="T4",
                prize_credits=500,
                total_credits_required=500,
                credits_per_share=10,
                total_shares=50,
                start_number=4000,
                shares_sold=10,
                status=1,
                winner_tg_id=202,
            )
        )
        # Issue 5: settled (status=2), but winner_tg_id is None
        session.add(
            TreasureIssue(
                id=5,
                title="T5",
                prize_credits=100,
                total_credits_required=100,
                credits_per_share=10,
                total_shares=10,
                start_number=5000,
                shares_sold=10,
                status=2,
                winner_tg_id=None,
            )
        )

    # 原 SQL 逻辑 - 期数榜
    with get_session() as session:
        win_count = func.count(TreasureIssue.id).label("win_count")
        stmt_issues = (
            select(TreasureIssue.winner_tg_id, win_count)
            .where(TreasureIssue.status == 2, TreasureIssue.winner_tg_id.isnot(None))
            .group_by(TreasureIssue.winner_tg_id)
            .order_by(win_count.desc())
        )
        orig_issues = [
            (int(r[0]), int(r[1] or 0))
            for r in session.execute(stmt_issues).fetchall()
            if int(r[1] or 0) > 0
        ]

    # 原 SQL 逻辑 - 积分榜
    with get_session() as session:
        win_credits = func.sum(TreasureIssue.prize_credits).label("win_credits")
        stmt_credits = (
            select(TreasureIssue.winner_tg_id, win_credits)
            .where(TreasureIssue.status == 2, TreasureIssue.winner_tg_id.isnot(None))
            .group_by(TreasureIssue.winner_tg_id)
            .order_by(win_credits.desc())
        )
        orig_credits = [
            (int(r[0]), int(r[1] or 0))
            for r in session.execute(stmt_credits).fetchall()
            if int(r[1] or 0) > 0
        ]

    service_issues = treasure_service.get_treasure_win_issue_rank()
    alias_issues = treasure_service.win_issue_rank()
    service_credits = treasure_service.get_treasure_win_credits_rank()
    alias_credits = treasure_service.win_credits_rank()

    assert service_issues == orig_issues
    assert alias_issues == orig_issues
    assert service_issues == [(201, 2), (202, 1)]

    assert service_credits == orig_credits
    assert alias_credits == orig_credits
    assert service_credits == [(202, 300), (201, 150)]


def test_invitation_invitee_counts_contrast(session_env) -> None:
    """invitation.service.invitee_counts 结果与原 SQL 逐条一致。"""
    with get_session() as session:
        # Owner 301: 2 distinct used_by
        session.add(Invitation(code="c1", owner=301, is_used=1, used_by="u1@test"))
        session.add(
            Invitation(code="c2", owner=301, is_used=1, used_by="u1@test")
        )  # duplicate used_by
        session.add(Invitation(code="c3", owner=301, is_used=1, used_by="u2@test"))
        session.add(Invitation(code="c4", owner=301, is_used=0, used_by=None))  # unused
        # Owner 302: 1 used_by
        session.add(Invitation(code="c5", owner=302, is_used=1, used_by="u3@test"))
        # Owner 303: used but used_by is None (should be excluded)
        session.add(Invitation(code="c6", owner=303, is_used=1, used_by=None))

    # 原 SQL 逻辑
    with get_session() as session:
        stmt = (
            select(
                Invitation.owner,
                func.count(func.distinct(Invitation.used_by)).label("invite_count"),
            )
            .where(Invitation.is_used == 1, Invitation.used_by.isnot(None))
            .group_by(Invitation.owner)
            .order_by(func.count(func.distinct(Invitation.used_by)).desc())
        )
        orig_result = [(int(r[0]), int(r[1])) for r in session.execute(stmt).fetchall()]

    service_result = invitation_service.invitee_counts()
    alias_result = invitation_service.get_invitation_rank()

    assert service_result == orig_result
    assert alias_result == orig_result
    assert service_result == [(301, 2), (302, 1)]


# ==============================================================================
# 2. Task 3.2: Rankings Service Parameterization & Use Cases
# ==============================================================================


def test_service_credits_rank_parameterization(session_env, monkeypatch) -> None:
    """service.get_credits_rank 支持 limit、exclude_admins 和 is_self 标识。"""
    monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [999])
    with get_session() as session:
        session.add(Statistics(tg_id=999, credits=1000.0))  # admin
        session.add(Statistics(tg_id=1, credits=500.0))
        session.add(Statistics(tg_id=2, credits=300.0))
        session.add(Statistics(tg_id=3, credits=100.0))

    # 接口用例：排除管理员，不设 limit，设置当前用户为 2
    api_ranks = rankings_service.get_credits_rank(
        exclude_admins=True, current_user_id=2
    )
    assert len(api_ranks) == 3
    assert [r["tg_id"] for r in api_ranks] == [1, 2, 3]
    assert [r["credits"] for r in api_ranks] == [500.0, 300.0, 100.0]
    assert [r["is_self"] for r in api_ranks] == [False, True, False]

    # Bot 用例：不排除管理员，设 limit 为 2
    bot_ranks = rankings_service.get_credits_rank(limit=2, exclude_admins=False)
    assert len(bot_ranks) == 2
    assert [r["tg_id"] for r in bot_ranks] == [999, 1]
    assert [r["credits"] for r in bot_ranks] == [1000.0, 500.0]


def test_service_donation_rank_parameterization(session_env, monkeypatch) -> None:
    """service.get_donation_rank 支持 limit、exclude_admins、include_zero 和 is_self。"""
    monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [999])
    with get_session() as session:
        session.add(Statistics(tg_id=999, credits=0, donation=500.0))  # admin
        session.add(Statistics(tg_id=1, credits=0, donation=200.0))
        session.add(Statistics(tg_id=2, credits=0, donation=0.0))  # zero donation
        session.add(Statistics(tg_id=3, credits=0, donation=50.0))

    # 接口用例：排除管理员，过滤零捐赠
    api_ranks = rankings_service.get_donation_rank(
        exclude_admins=True, include_zero=False, current_user_id=1
    )
    assert len(api_ranks) == 2
    assert [r["tg_id"] for r in api_ranks] == [1, 3]
    assert [r["donation"] for r in api_ranks] == [200.0, 50.0]
    assert [r["is_self"] for r in api_ranks] == [True, False]

    # include_zero=True 保留零捐赠
    with_zero = rankings_service.get_donation_rank(
        exclude_admins=True, include_zero=True
    )
    assert len(with_zero) == 3
    assert [r["tg_id"] for r in with_zero] == [1, 3, 2]


def test_service_watch_time_rank_parameterization(session_env) -> None:
    """service.get_watch_time_rank 支持 Plex/Emby、limit、include_zero 与媒体头像。"""
    with get_session() as session:
        session.add(
            PlexUser(
                plex_id=10,
                tg_id=1,
                plex_username="plex_alice",
                watched_time=120.5,
                is_premium=1,
            )
        )
        session.add(
            PlexUser(
                plex_id=11,
                tg_id=2,
                plex_username="plex_bob",
                watched_time=0.0,
                is_premium=0,
            )
        )
        session.add(
            EmbyUser(
                emby_id="e10",
                tg_id=1,
                emby_username="emby_alice",
                emby_watched_time=88.0,
                is_premium=1,
            )
        )
        session.add(
            EmbyUser(
                emby_id="e11",
                tg_id=None,
                emby_username="emby_unbound",
                emby_watched_time=0.0,
                is_premium=0,
            )
        )

    # Plex 接口用例：过滤 0
    plex_api = rankings_service.get_watch_time_rank(
        "plex", include_zero=False, with_avatar=False, current_user_id=1
    )
    assert len(plex_api) == 1
    assert plex_api[0]["name"] == "plex_alice"
    assert plex_api[0]["watched_time"] == 120.5
    assert plex_api[0]["is_self"] is True
    assert plex_api[0]["is_premium"] is True

    # Plex Bot 用例：包含 0，limit 15
    plex_bot = rankings_service.get_watch_time_rank(
        "plex", limit=15, include_zero=True, with_avatar=False
    )
    assert len(plex_bot) == 2
    assert [r["name"] for r in plex_bot] == ["plex_alice", "plex_bob"]

    # Emby 接口用例
    emby_api = rankings_service.get_watch_time_rank(
        "emby", include_zero=False, with_avatar=False, current_user_id=1
    )
    assert len(emby_api) == 1
    assert emby_api[0]["name"] == "emby_alice"
    assert emby_api[0]["watched_time"] == 88.0
    assert emby_api[0]["is_self"] is True


def test_service_badge_rank_parameterization(session_env, monkeypatch) -> None:
    """service.get_badge_rank 排除管理员与零勋章。"""
    monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [999])
    now = int(time.time())
    with get_session() as session:
        session.add(
            Badge(
                id=1,
                badge_type="vip",
                name="VIP Badge",
                description="VIP",
                icon_url="https://example.com/icon.png",
                credits_cost=10,
                valid_days=30,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        # Admin user
        session.add(
            UserBadge(
                id=1,
                tg_id=999,
                badge_id=1,
                credits_cost=10,
                redeemed_at=now,
                expires_at=now + 86400,
                is_active=1,
            )
        )
        # Normal user 1
        session.add(
            UserBadge(
                id=2,
                tg_id=1,
                badge_id=1,
                credits_cost=10,
                redeemed_at=now,
                expires_at=now + 86400,
                is_active=1,
            )
        )
        # Inactive badge for user 2 (should not count)
        session.add(
            UserBadge(
                id=3,
                tg_id=2,
                badge_id=1,
                credits_cost=10,
                redeemed_at=now,
                expires_at=now + 86400,
                is_active=0,
            )
        )

    ranks = rankings_service.get_badge_rank(exclude_admins=True, current_user_id=1)
    assert len(ranks) == 1
    assert ranks[0]["tg_id"] == 1
    assert ranks[0]["badge_count"] == 1
    assert ranks[0]["is_self"] is True
    assert len(ranks[0]["badges"]) == 1
    assert ranks[0]["badges"][0]["badge"]["name"] == "VIP Badge"


# ==============================================================================
# 3. Task 1.3: Router Endpoints Behavior Freeze & Error Handling
# ==============================================================================


@pytest.mark.asyncio
async def test_router_credits_rank_endpoint(session_env, monkeypatch) -> None:
    """/rankings/credits 成功返回与管理员排除。"""
    monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [999])
    with get_session() as session:
        session.add(Statistics(tg_id=999, credits=9999.0))
        session.add(Statistics(tg_id=42, credits=123.45))

    res = await rankings_router.get_credits_rankings(
        request=_request(),
        user=TelegramUser(id=42, first_name="Answer", username="fortytwo"),
    )
    assert "credits_rank" in res
    assert len(res["credits_rank"]) == 1
    item = res["credits_rank"][0]
    assert item["credits"] == 123.45
    assert item["is_self"] is True


@pytest.mark.asyncio
async def test_router_donation_rank_endpoint(session_env, monkeypatch) -> None:
    """/rankings/donation 成功返回与零过滤。"""
    monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [999])
    with get_session() as session:
        session.add(Statistics(tg_id=999, credits=0, donation=500.0))
        session.add(Statistics(tg_id=42, credits=0, donation=88.8))
        session.add(Statistics(tg_id=43, credits=0, donation=0.0))

    res = await rankings_router.get_donation_rankings(
        request=_request(),
        user=TelegramUser(id=42, first_name="Answer", username="fortytwo"),
    )
    assert "donation_rank" in res
    assert len(res["donation_rank"]) == 1
    assert res["donation_rank"][0]["donation"] == 88.8
    assert res["donation_rank"][0]["is_self"] is True


@pytest.mark.asyncio
async def test_router_watch_time_endpoints(session_env) -> None:
    """/rankings/watched-time/plex 和 /rankings/watched-time/emby 成功响应。"""
    with get_session() as session:
        session.add(
            PlexUser(
                plex_id=1,
                tg_id=42,
                plex_username="p_user",
                watched_time=50.2,
                is_premium=1,
            )
        )
        session.add(
            EmbyUser(
                emby_id="e1",
                tg_id=42,
                emby_username="e_user",
                emby_watched_time=30.1,
                is_premium=0,
            )
        )

    plex_res = await rankings_router.get_plex_watched_time_rankings(
        request=_request(),
        user=TelegramUser(id=42, first_name="Answer", username="fortytwo"),
    )
    assert "watched_time_rank_plex" in plex_res
    assert len(plex_res["watched_time_rank_plex"]) == 1
    assert plex_res["watched_time_rank_plex"][0]["name"] == "p_user"
    assert plex_res["watched_time_rank_plex"][0]["watched_time"] == 50.2
    assert plex_res["watched_time_rank_plex"][0]["is_self"] is True

    emby_res = await rankings_router.get_emby_watched_time_rankings(
        request=_request(),
        user=TelegramUser(id=42, first_name="Answer", username="fortytwo"),
    )
    assert "watched_time_rank_emby" in emby_res
    assert len(emby_res["watched_time_rank_emby"]) == 1
    assert emby_res["watched_time_rank_emby"][0]["name"] == "e_user"
    assert emby_res["watched_time_rank_emby"][0]["watched_time"] == 30.1
    assert emby_res["watched_time_rank_emby"][0]["is_self"] is True


@pytest.mark.asyncio
async def test_router_invitation_endpoint(session_env) -> None:
    """/rankings/invitation 调用 invitation_service 并返回排行榜。"""
    with get_session() as session:
        session.add(Invitation(code="inv_1", owner=42, is_used=1, used_by="alice@p"))
        session.add(Invitation(code="inv_2", owner=42, is_used=1, used_by="bob@p"))

    res = await rankings_router.get_invitation_rankings(
        request=_request(),
        user=TelegramUser(id=42, first_name="Answer", username="fortytwo"),
    )
    assert "invitation_rank" in res
    assert len(res["invitation_rank"]) == 1
    assert res["invitation_rank"][0]["invite_count"] == 2
    assert res["invitation_rank"][0]["is_self"] is True


@pytest.mark.asyncio
async def test_router_wheel_game_endpoint(session_env) -> None:
    """/rankings/game/wheel 返回综合排行榜。"""
    now = int(time.time())
    with get_session() as session:
        session.add(
            WheelStats(
                id=1,
                tg_id=42,
                item_name="100 积分",
                credits_change=100.0,
                cost_credits=10,
                timestamp=now,
                date="2026-01-01",
            )
        )
        session.add(
            WheelStats(
                id=2,
                tg_id=42,
                item_name="邀请码 1 枚",
                credits_change=0,
                cost_credits=10,
                timestamp=now,
                date="2026-01-01",
            )
        )

    res = await rankings_router.get_wheel_game_rankings(
        request=_request(),
        user=TelegramUser(id=42, first_name="Answer", username="fortytwo"),
    )
    assert "wheel_credits_rank" in res
    assert "wheel_invite_code_rank" in res
    assert len(res["wheel_credits_rank"]) == 1
    assert res["wheel_credits_rank"][0]["earned_credits"] == 100.0
    assert len(res["wheel_invite_code_rank"]) == 1
    assert res["wheel_invite_code_rank"][0]["invite_code_count"] == 1


@pytest.mark.asyncio
async def test_router_treasure_game_endpoint(session_env) -> None:
    """/rankings/game/treasure 返回夺宝奇兵综合排行榜。"""
    with get_session() as session:
        session.add(
            TreasureIssue(
                id=1,
                title="T_Test",
                prize_credits=200,
                total_credits_required=200,
                credits_per_share=10,
                total_shares=20,
                start_number=1,
                shares_sold=20,
                status=2,
                winner_tg_id=42,
                winner_number=5,
            )
        )

    res = await rankings_router.get_treasure_game_rankings(
        request=_request(),
        user=TelegramUser(id=42, first_name="Answer", username="fortytwo"),
    )
    assert "treasure_win_issue_rank" in res
    assert "treasure_win_credits_rank" in res
    assert len(res["treasure_win_issue_rank"]) == 1
    assert res["treasure_win_issue_rank"][0]["win_issue_count"] == 1
    assert len(res["treasure_win_credits_rank"]) == 1
    assert res["treasure_win_credits_rank"][0]["win_credits"] == 200


@pytest.mark.asyncio
async def test_router_traffic_endpoints(session_env, monkeypatch) -> None:
    """/rankings/traffic/plex 和 /rankings/traffic/emby 的日期校验与响应。"""
    monkeypatch.setattr(
        rankings_service.traffic_service,
        "traffic_rank",
        lambda service, start, end: [("user1", 1, 1024.0, 1, 42)],
    )

    # 正常查询
    res_plex = await rankings_router.get_plex_traffic_rankings(
        request=_request(),
        user=TelegramUser(id=42, first_name="Answer", username="fortytwo"),
        start_date="2026-01-01",
        end_date="2026-01-31",
    )
    assert "traffic_rank_plex" in res_plex
    assert len(res_plex["traffic_rank_plex"]) == 1
    assert res_plex["traffic_rank_plex"][0]["name"] == "user1"
    assert res_plex["traffic_rank_plex"][0]["is_self"] is True

    # 错误日期格式返回 400
    with pytest.raises(HTTPException) as exc_info:
        await rankings_router.get_plex_traffic_rankings(
            request=_request(),
            user=TelegramUser(id=42, first_name="Answer", username="fortytwo"),
            start_date="invalid-date",
        )
    assert exc_info.value.status_code == 400
    assert "开始日期格式错误" in exc_info.value.detail


# ==============================================================================
# 4. Task 1.3: Empty Database (200 OK + []) & Query Failure (500)
# ==============================================================================


@pytest.mark.asyncio
async def test_empty_database_returns_200_with_empty_lists(session_env) -> None:
    """空数据时所有榜单接口返回 200 与空列表，非 500。"""
    user = TelegramUser(id=1, first_name="test", username="test")
    req = _request()

    res_credits = await rankings_router.get_credits_rankings(request=req, user=user)
    assert res_credits == {"credits_rank": []}

    res_donation = await rankings_router.get_donation_rankings(request=req, user=user)
    assert res_donation == {"donation_rank": []}

    res_plex = await rankings_router.get_plex_watched_time_rankings(
        request=req, user=user
    )
    assert res_plex == {"watched_time_rank_plex": []}

    res_emby = await rankings_router.get_emby_watched_time_rankings(
        request=req, user=user
    )
    assert res_emby == {"watched_time_rank_emby": []}

    res_badge = await rankings_router.get_badge_rankings(request=req, user=user)
    assert res_badge == {"badge_rank": []}

    res_invitation = await rankings_router.get_invitation_rankings(
        request=req, user=user
    )
    assert res_invitation == {"invitation_rank": []}

    res_wheel = await rankings_router.get_wheel_game_rankings(request=req, user=user)
    assert res_wheel == {"wheel_credits_rank": [], "wheel_invite_code_rank": []}

    res_treasure = await rankings_router.get_treasure_game_rankings(
        request=req, user=user
    )
    assert res_treasure == {
        "treasure_win_issue_rank": [],
        "treasure_win_credits_rank": [],
    }


@pytest.mark.asyncio
async def test_core_query_failure_returns_500(session_env, monkeypatch) -> None:
    """核心查询失败时返回固定的 500 状态码与相应提示。"""
    user = TelegramUser(id=1, first_name="test", username="test")
    req = _request()

    # 模拟 repository 抛异常
    monkeypatch.setattr(
        rankings_repository,
        "get_credits_rank",
        MagicMock(side_effect=RuntimeError("db connection failed")),
    )
    with pytest.raises(HTTPException) as exc_info:
        await rankings_router.get_credits_rankings(request=req, user=user)
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "获取积分排行榜数据失败"

    monkeypatch.setattr(
        rankings_repository,
        "get_donation_rank",
        MagicMock(side_effect=RuntimeError("db error")),
    )
    with pytest.raises(HTTPException) as exc_info:
        await rankings_router.get_donation_rankings(request=req, user=user)
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "获取捐赠排行榜数据失败"

    monkeypatch.setattr(
        rankings_repository,
        "get_badge_rank",
        MagicMock(side_effect=RuntimeError("db error")),
    )
    with pytest.raises(HTTPException) as exc_info:
        await rankings_router.get_badge_rankings(request=req, user=user)
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "获取勋章排行榜数据失败"


@pytest.mark.asyncio
async def test_per_row_profile_lookup_failure_fallback(
    session_env, monkeypatch
) -> None:
    """单行姓名或头像补全失败时保留该行排行，姓名与头像回退为空字段，不使全榜失败。"""
    with get_session() as session:
        session.add(Statistics(tg_id=888, credits=999.0))

    # 模拟缓存加载抛异常
    monkeypatch.setattr(
        rankings_service,
        "load_tg_user_info_cache",
        MagicMock(side_effect=RuntimeError("cache disk error")),
    )
    monkeypatch.setattr(
        rankings_service,
        "get_user_names_from_tg_ids",
        MagicMock(side_effect=RuntimeError("names lookup error")),
    )

    res = await rankings_router.get_credits_rankings(
        request=_request(),
        user=TelegramUser(id=888, first_name="Lucky", username="lucky"),
    )
    assert len(res["credits_rank"]) == 1
    row = res["credits_rank"][0]
    assert row["credits"] == 999.0
    assert row["name"] == ""
    assert row["avatar"] == ""
    assert row["is_self"] is True


# ==============================================================================
# 5. Task 1.3: Bot Commands Integration & Formatting
# ==============================================================================


@pytest.mark.asyncio
async def test_bot_credits_rank_command(session_env, monkeypatch) -> None:
    """Bot /credits_rank 命令格式化与上限 30 名。"""
    with get_session() as session:
        for i in range(1, 35):
            session.add(Statistics(tg_id=i, credits=float(1000 - i)))

    sent_messages = []

    async def mock_send_message(chat_id, text, parse_mode, context):
        sent_messages.append(
            {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        )

    monkeypatch.setattr(rankings_bot, "send_message", mock_send_message)

    update = MagicMock()
    update._effective_chat.id = 12345
    context = MagicMock()

    await rankings_bot.credits_rank(update, context)

    assert len(sent_messages) == 1
    text = sent_messages[0]["text"]
    assert "<strong>积分榜</strong>" in text
    assert "1. 1: 999.00" in text
    assert "30. 30: 970.00" in text
    # 超过 30 名的不在榜单内
    assert "31. 31:" not in text
    assert "⚠️只统计 TG 绑定用户" in text


@pytest.mark.asyncio
async def test_bot_donation_rank_command(session_env, monkeypatch) -> None:
    """Bot /donation_rank 命令格式化与零过滤。"""
    with get_session() as session:
        session.add(Statistics(tg_id=1, credits=0, donation=100.0))
        session.add(Statistics(tg_id=2, credits=0, donation=0.0))

    sent_messages = []

    async def mock_send_message(chat_id, text, parse_mode, context):
        sent_messages.append(
            {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        )

    monkeypatch.setattr(rankings_bot, "send_message", mock_send_message)

    update = MagicMock()
    update._effective_chat.id = 12345
    context = MagicMock()

    await rankings_bot.donation_rank(update, context)

    assert len(sent_messages) == 1
    text = sent_messages[0]["text"]
    assert "<strong>捐赠榜</strong>" in text
    assert "1. 1: 100.00" in text
    assert "2. 2:" not in text
    assert "衷心感谢各位的支持!" in text


@pytest.mark.asyncio
async def test_bot_watched_time_rank_command(session_env, monkeypatch) -> None:
    """Bot /play_duration_rank 命令格式化。"""
    with get_session() as session:
        session.add(
            PlexUser(plex_id=1, tg_id=1, plex_username="alice_plex", watched_time=20.5)
        )
        session.add(
            EmbyUser(
                emby_id="e1",
                tg_id=1,
                emby_username="alice_emby",
                emby_watched_time=15.2,
            )
        )

    sent_messages = []

    async def mock_send_message(chat_id, text, parse_mode, context):
        sent_messages.append(
            {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        )

    monkeypatch.setattr(rankings_bot, "send_message", mock_send_message)

    update = MagicMock()
    update._effective_chat.id = 12345
    context = MagicMock()

    await rankings_bot.watched_time_rank(update, context)

    assert len(sent_messages) == 1
    text = sent_messages[0]["text"]
    assert "<strong>观看时长榜 (Hour)</strong>" in text
    assert "------ Plex ------" in text
    assert "1. alice_plex: 20.50" in text
    assert "------ Emby ------" in text
    assert "1. alice_emby: 15.20" in text


@pytest.mark.asyncio
async def test_bot_device_rank_admin_permission(monkeypatch) -> None:
    """Bot /device_rank 非管理员越权拦截。"""
    monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [999])

    sent_messages = []

    async def mock_send_message(chat_id, text, context=None, parse_mode=None):
        sent_messages.append(text)

    monkeypatch.setattr(rankings_bot, "send_message", mock_send_message)

    update = MagicMock()
    update._effective_chat.id = 12345  # Not admin
    context = MagicMock()

    await rankings_bot.device_rank(update, context)

    assert sent_messages == ["错误：越权操作"]


@pytest.mark.asyncio
async def test_bot_error_handling_fallback(session_env, monkeypatch) -> None:
    """Bot 命令异常时返回用户友好的错误提示。"""
    monkeypatch.setattr(
        rankings_service,
        "get_credits_rank",
        MagicMock(side_effect=RuntimeError("service crash")),
    )

    sent_messages = []

    async def mock_send_message(chat_id, text, context=None, parse_mode=None):
        sent_messages.append(text)

    monkeypatch.setattr(rankings_bot, "send_message", mock_send_message)

    update = MagicMock()
    update._effective_chat.id = 12345
    context = MagicMock()

    await rankings_bot.credits_rank(update, context)

    assert sent_messages == ["获取失败，请稍后再试"]


def test_invitation_owner_invitee_count_and_codes(session_env) -> None:
    """invitation.service/repository 的 get_invitee_count_by_owner 与 get_invitation_code_by_owner 测试。"""
    with get_session() as session:
        # Owner 501: 2 available codes, 1 used code with used_by, 1 used code with duplicate used_by, 1 used code with None used_by
        session.add(Invitation(code="avail_1", owner=501, is_used=0, used_by=None))
        session.add(Invitation(code="avail_2", owner=501, is_used=0, used_by=None))
        session.add(Invitation(code="used_1", owner=501, is_used=1, used_by="alice@p"))
        session.add(Invitation(code="used_2", owner=501, is_used=1, used_by="alice@p"))
        session.add(Invitation(code="used_3", owner=501, is_used=1, used_by="bob@p"))
        session.add(Invitation(code="used_none", owner=501, is_used=1, used_by=None))

        # Owner 502: only available codes
        session.add(Invitation(code="avail_3", owner=502, is_used=0, used_by=None))

    # 1. get_invitee_count_by_owner 测试（distinct used_by where is_used==1 and used_by is not None）
    assert invitation_service.get_invitee_count_by_owner(501) == 2
    assert invitation_service.get_invitee_count_by_owner(502) == 0
    assert invitation_service.get_invitee_count_by_owner(999) == 0

    # 2. get_invitation_code_by_owner 测试
    # 默认 is_available=True：只返回 is_used == 0
    avail_codes = invitation_service.get_invitation_code_by_owner(501)
    assert set(avail_codes) == {"avail_1", "avail_2"}

    # is_available=False：返回所有 code
    all_codes = invitation_service.get_invitation_code_by_owner(501, is_available=False)
    assert set(all_codes) == {
        "avail_1",
        "avail_2",
        "used_1",
        "used_2",
        "used_3",
        "used_none",
    }


def test_invitation_get_invitee_count_error_fallback(session_env, monkeypatch) -> None:
    """invitation.repository.get_invitee_count_by_owner 异常时捕获并返回 0。"""
    import app.domains.invitation.repository as inv_repo

    monkeypatch.setattr(
        inv_repo, "get_session", MagicMock(side_effect=RuntimeError("db error"))
    )

    assert inv_repo.get_invitee_count_by_owner(501) == 0
    assert invitation_service.get_invitee_count_by_owner(501) == 0


def test_media_and_invitation_wire_fields_are_frozen(monkeypatch):
    """Do not add internal account identifiers to the historical public payloads."""
    from app.domains.rankings import service

    monkeypatch.setattr(
        service.rankings_repository,
        "get_plex_watched_time_rank",
        lambda: [(10, 42, "plex", 5, 1)],
    )
    monkeypatch.setattr(
        service.rankings_repository,
        "get_emby_watched_time_rank",
        lambda: [("id", "emby", 5, 1, 42)],
    )
    monkeypatch.setattr(service.invitation_service, "invitee_counts", lambda: [(42, 3)])
    monkeypatch.setattr(
        service, "_enrich_profiles_batch", lambda ids: {42: ("name", "avatar")}
    )
    expected_media = {"name", "watched_time", "avatar", "is_premium", "is_self"}
    for media in ("plex", "emby"):
        assert (
            set(service.get_watch_time_rank(media, with_avatar=False)[0])
            == expected_media
        )
    assert set(service.get_invitation_rank(exclude_admins=False)[0]) == {
        "name",
        "invite_count",
        "avatar",
        "is_self",
    }
