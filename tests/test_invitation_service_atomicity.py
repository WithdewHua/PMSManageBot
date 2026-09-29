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
