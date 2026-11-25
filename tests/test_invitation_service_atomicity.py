import pytest
from sqlalchemy import select

from app.core.db import get_session
from app.domains.credits.exceptions import InsufficientCredits
from app.domains.identity.models import Statistics
from app.domains.invitation import repository as invitation_repository
from app.domains.invitation import service as invitation_service
from app.domains.invitation.exceptions import InvitationError
from app.domains.invitation.models import Invitation


def test_generate_code_rolls_back_code_when_credit_charge_fails(
    session_env, monkeypatch
):
    with get_session() as session:
        session.add(Statistics(tg_id=501, credits=100, donation=0))

    monkeypatch.setattr(
        invitation_repository.credits_repository,
        "deduct_tx",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            InsufficientCredits("tg:501", requested=10, available=0)
        ),
    )
    monkeypatch.setattr(invitation_service, "get_invitation_credits", lambda: 10)

    with pytest.raises(InvitationError):
        invitation_service.generate_one_code(501)

    with get_session() as session:
        assert session.execute(select(Invitation)).scalars().all() == []
        assert session.get(Statistics, 501).credits == 100


def test_redeem_code_is_single_use_and_credits_are_atomic(session_env, monkeypatch):
    monkeypatch.setattr(invitation_service, "get_invitation_credits", lambda: 10)
    with get_session() as session:
        session.add_all(
            [
                Statistics(tg_id=502, credits=0, donation=0),
                Invitation(code="once", owner=999, is_used=0),
            ]
        )

    assert invitation_service.redeem_for_credits(502, "once")[0] == 8
    with pytest.raises(InvitationError):
        invitation_service.redeem_for_credits(502, "once")

    with get_session() as session:
        assert session.get(Statistics, 502).credits == 8
        assert session.get(Invitation, "once").is_used == 1


@pytest.mark.parametrize(
    "reason", ["找不到模板用户", "新用户权限与模板不一致", "密码设置失败"]
)
async def test_emby_creation_failure_releases_invite_without_local_account(
    session_env, monkeypatch, reason
):
    from app.domains.accounts import service as accounts_service
    from app.domains.identity.models import EmbyUser
    from app.domains.invitation.exceptions import InvitationRejected
    from app.integrations.emby import Emby

    accounts_service.set_registration_enabled("emby", True)
    with get_session() as session:
        session.add(Invitation(code="emby-failure", owner=999, is_used=0))

    class FailedEmby(Emby):
        def get_uid_from_username(self, username):
            return None

        def add_user(
            self, username: str, password: str, user_template: str = "UserTemplate"
        ) -> tuple[bool, str]:
            return False, reason

    with pytest.raises(InvitationRejected, match=reason):
        await invitation_service.register_emby(
            code="emby-failure",
            username="newuser",
            password="test-password",
            bind_to_telegram=False,
            telegram_user_id=502,
            emby_factory=FailedEmby,
        )

    with get_session() as session:
        invitation = session.get(Invitation, "emby-failure")
        assert invitation is not None
        assert invitation.is_used == 0
        assert invitation.used_by is None
        assert invitation.emby_id is None
        assert session.execute(select(EmbyUser)).scalars().all() == []
