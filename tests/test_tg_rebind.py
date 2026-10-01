"""End-to-end transaction and CLI contracts for Telegram identity reassignment."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.db import get_session
from app.domains.identity.models import Statistics
from app.domains.tg_rebind import service


def _seed_stats(old_id: int, new_id: int) -> None:
    with get_session() as session:
        session.add(
            Statistics(
                tg_id=old_id,
                credits=10,
                donation=2,
                tournament_wallet_credits=7,
                blackjack_lose_streak=3,
                blackjack_hands_since_freespin=4,
            )
        )
        session.add(
            Statistics(
                tg_id=new_id,
                credits=5,
                donation=3,
                tournament_wallet_credits=11,
                blackjack_lose_streak=2,
                blackjack_hands_since_freespin=1,
            )
        )


def test_rebind_merges_statistics_and_removes_old_identity(session_env):
    old_id, new_id = 981001, 981002
    _seed_stats(old_id, new_id)

    report = service.rebind(new_id, from_tg_id=old_id)

    assert report.old_tg_id == old_id
    assert report.new_tg_id == new_id
    assert report.dry_run is False
    with get_session() as session:
        merged = session.get(Statistics, new_id)
        assert merged is not None
        assert merged.credits == 15
        assert merged.donation == 5
        assert merged.tournament_wallet_credits == 18
        assert merged.blackjack_lose_streak == 5
        assert merged.blackjack_hands_since_freespin == 5
        assert session.get(Statistics, old_id) is None


def test_rebind_dry_run_rolls_back_everything(session_env):
    old_id, new_id = 982001, 982002
    _seed_stats(old_id, new_id)

    report = service.rebind(new_id, from_tg_id=old_id, dry_run=True)

    assert report.dry_run is True
    with get_session() as session:
        old = session.get(Statistics, old_id)
        new = session.get(Statistics, new_id)
        assert old is not None and old.credits == 10
        assert new is not None and new.credits == 5


def test_rebind_locator_is_case_insensitive(session_env):
    from app.domains.identity.models import PlexUser

    old_id, new_id = 983001, 983002
    _seed_stats(old_id, new_id)
    with get_session() as session:
        session.add(
            PlexUser(plex_id=983003, tg_id=old_id, plex_email="Case@Example.test")
        )

    report = service.rebind(new_id, plex_email="case@example.test")

    assert report.old_tg_id == old_id
    with get_session() as session:
        assert (
            session.execute(
                select(PlexUser.tg_id).where(PlexUser.plex_id == 983003)
            ).scalar_one()
            == new_id
        )


def test_rebind_unbound_media_account_transfers_credits(session_env):
    from app.domains.identity.models import PlexUser

    new_id = 984002
    with get_session() as session:
        session.add(Statistics(tg_id=new_id, credits=4))
        session.add(
            PlexUser(
                id=984003,
                plex_id=None,
                tg_id=None,
                credits=8,
                plex_email="Pending@Example.test",
                plex_username="pending-user",
            )
        )

    report = service.rebind(new_id, plex_email="pending@example.test")

    assert report.old_tg_id == 0
    with get_session() as session:
        user = session.get(PlexUser, 984003)
        assert user is not None and user.tg_id == new_id and user.credits == 0
        assert session.get(Statistics, new_id).credits == 12


def test_rebind_late_failure_rolls_back_all_domains(session_env, monkeypatch):
    old_id, new_id = 985001, 985002
    _seed_stats(old_id, new_id)
    from app.domains.gift_pack import repository as gift_pack_repository

    def fail_after_previous_domains(*args, **kwargs):
        raise RuntimeError("injected rebind failure")

    monkeypatch.setattr(
        gift_pack_repository, "reassign_tg_id_tx", fail_after_previous_domains
    )

    with pytest.raises(RuntimeError, match="injected"):
        service.rebind(new_id, from_tg_id=old_id)

    with get_session() as session:
        old = session.get(Statistics, old_id)
        new = session.get(Statistics, new_id)
        assert old is not None and (old.credits, old.donation) == (10, 2)
        assert new is not None and (new.credits, new.donation) == (5, 3)


def test_rebind_dry_run_does_not_refresh_cache(session_env, monkeypatch):
    old_id, new_id = 986001, 986002
    _seed_stats(old_id, new_id)
    refreshed = []
    from app.domains.identity import repository as identity_repository

    monkeypatch.setattr(
        identity_repository,
        "refresh_user_info_for_tg",
        lambda tg_id: refreshed.append(tg_id),
    )

    service.rebind(new_id, from_tg_id=old_id, dry_run=True)

    assert refreshed == []


def test_rebind_moves_invitation_owner_and_encoded_redeemer(session_env):
    from app.domains.invitation.models import Invitation

    old_id, new_id = 987001, 987002
    _seed_stats(old_id, new_id)
    with get_session() as session:
        session.add(
            Invitation(
                code="rebind-invite",
                owner=old_id,
                used_by=f"credits_by_{old_id}",
                is_used=1,
            )
        )

    service.rebind(new_id, from_tg_id=old_id)

    with get_session() as session:
        invitation = session.get(Invitation, "rebind-invite")
        assert invitation.owner == new_id
        assert invitation.used_by == f"credits_by_{new_id}"
