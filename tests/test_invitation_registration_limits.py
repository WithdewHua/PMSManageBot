"""fix-live-defects D4/D6：Plex 注册人数上限与邀请码接口的未绑定响应。

修复前：人数上限用 ``== 100`` 判断，一旦越过 100 就彻底失效；未绑定
用户调用 points-info/generate 得到 404 被外层 ``except Exception`` 改
写成 500。
"""

from __future__ import annotations

from fastapi import BackgroundTasks
from starlette.requests import Request

from app.core.db import get_session
from app.domains.identity.models import PlexUser, Statistics
from app.domains.invitation import router as invitation_router
from app.domains.invitation.schemas import RedeemInviteCodeRequest
from app.transport.http.schemas import TelegramUser


def _request() -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/api", "headers": []})
    request.state.telegram_data = {}
    return request


def _seed_plex_users(count: int) -> None:
    with get_session() as session:
        for i in range(1, count + 1):
            session.add(
                PlexUser(
                    plex_id=10_000 + i,
                    plex_email=f"u{i}@example.com",
                    plex_username=f"u{i}",
                )
            )


async def test_plex_limit_blocks_at_101(session_env, monkeypatch):
    from app.domains.accounts import service as accounts_service
    from app.domains.invitation.models import Invitation

    accounts_service.set_registration_enabled("plex", True)

    with get_session() as session:
        session.add(Invitation(code="limit-code", owner=999, is_used=0))
    _seed_plex_users(101)

    invited: list[str] = []

    class FakePlex:
        @property
        def users_by_email(self):
            return {}

        def invite_friend(self, email, **kwargs):
            invited.append(email)
            return True

        def get_user_id_by_email(self, email):
            return 0

    monkeypatch.setattr("app.domains.invitation.router.Plex", lambda: FakePlex())

    response = await invitation_router.redeem_plex_code.__wrapped__(
        _request(),
        BackgroundTasks(),
        RedeemInviteCodeRequest(code="limit-code", email="new@example.com"),
        TelegramUser(id=1, first_name="u"),
    )

    assert response.success is False
    assert response.message == "Plex 用户数已达上限"
    assert invited == []  # 没有向 Plex 发出邀请
    with get_session() as session:
        row = session.get(Invitation, "limit-code")
        assert row.is_used == 0  # 邀请码未被消耗


async def test_plex_limit_allows_at_99(session_env, monkeypatch):
    """99 人时注册照常可用（修复前后一致）。"""
    from app.domains.accounts import service as accounts_service

    accounts_service.set_registration_enabled("plex", True)
    from app.domains.invitation.models import Invitation

    with get_session() as session:
        session.add(Invitation(code="ok-code", owner=999, is_used=0))
        session.add(Statistics(tg_id=1, credits=0.0, donation=0.0))
    _seed_plex_users(99)

    class FakePlex:
        @property
        def users_by_email(self):
            return {}

        def invite_friend(self, email, **kwargs):
            return True

        def get_user_id_by_email(self, email):
            return 0

    monkeypatch.setattr("app.domains.invitation.router.Plex", lambda: FakePlex())
    monkeypatch.setattr(
        "app.domains.invitation.router.send_message_by_url",
        _async_noop,
    )

    response = await invitation_router.redeem_plex_code.__wrapped__(
        _request(),
        BackgroundTasks(),
        RedeemInviteCodeRequest(code="ok-code", email="new@example.com"),
        TelegramUser(id=1, first_name="u"),
    )
    assert response.success is True


async def _async_noop(*args, **kwargs):
    return None


async def test_points_info_unbound_returns_200_contract(session_env):
    # 用户没有任何 statistics 行（未绑定）
    result = await invitation_router.get_invite_points_info.__wrapped__(
        _request(), TelegramUser(id=42, first_name="u")
    )
    assert result.required_points > 0
    assert result.current_points == 0
    assert result.can_generate is False
    assert result.error_message == "用户未绑定 Plex/Emby 账户"


async def test_generate_unbound_returns_200_contract(session_env):
    result = await invitation_router.generate_invite_code.__wrapped__(
        _request(), TelegramUser(id=42, first_name="u")
    )
    assert result.success is False
    assert result.message == "用户未绑定 Plex/Emby 账户"
    from sqlalchemy import select

    from app.domains.invitation.models import Invitation

    with get_session() as session:
        assert session.execute(select(Invitation)).scalars().all() == []
