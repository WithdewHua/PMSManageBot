from __future__ import annotations

import pytest

from app.core.db import get_session
from app.domains.accounts import repository as accounts_repository
from app.domains.credits import repository as credits_repository
from app.domains.identity.models import EmbyUser, PlexUser, Statistics


def test_plex_binding_moves_balance_atomically(session_env) -> None:
    with get_session() as session:
        session.add_all(
            [
                Statistics(tg_id=101, donation=0, credits=2),
                PlexUser(
                    id=1,
                    plex_id=501,
                    tg_id=None,
                    credits=7,
                    plex_username="plex-user",
                ),
            ]
        )

    accounts_repository.bind_plex_account(
        tg_id=101,
        plex_id=501,
        plex_email="plex@example.com",
        plex_username="plex-user",
        all_lib=1,
        watched_time=0,
        existing_unbound=True,
        existing_credits=7,
    )

    with get_session() as session:
        plex = session.get(PlexUser, 1)
        stats = session.get(Statistics, 101)
        assert plex.tg_id == 101
        assert plex.credits == 0
        assert stats.credits == 9


def test_plex_binding_rolls_back_if_credit_transfer_fails(
    session_env, monkeypatch
) -> None:
    with get_session() as session:
        session.add(
            PlexUser(
                id=1,
                plex_id=501,
                tg_id=None,
                credits=7,
                plex_username="plex-user",
            )
        )

    def fail_add(*_args, **_kwargs):
        raise RuntimeError("credit transfer failed")

    monkeypatch.setattr(credits_repository, "move_tx", fail_add)
    with pytest.raises(RuntimeError, match="credit transfer failed"):
        accounts_repository.bind_plex_account(
            tg_id=101,
            plex_id=501,
            plex_email="plex@example.com",
            plex_username="plex-user",
            all_lib=1,
            watched_time=0,
            existing_unbound=True,
            existing_credits=7,
        )

    with get_session() as session:
        plex = session.get(PlexUser, 1)
        stats = session.get(Statistics, 101)
        assert plex.tg_id is None
        assert plex.credits == 7
        assert stats is None


def test_emby_binding_moves_balance_atomically(session_env) -> None:
    with get_session() as session:
        session.add_all(
            [
                Statistics(tg_id=101, donation=0, credits=2),
                EmbyUser(
                    emby_username="emby-user",
                    emby_id="emby-501",
                    tg_id=None,
                    emby_credits=7,
                ),
            ]
        )

    accounts_repository.bind_emby_account(
        tg_id=101,
        emby_id="emby-501",
        emby_username="emby-user",
        existing_unbound=True,
    )

    with get_session() as session:
        emby = session.query(EmbyUser).filter_by(emby_id="emby-501").one()
        stats = session.get(Statistics, 101)
        assert emby.tg_id == 101
        assert emby.emby_credits == 0
        assert stats.credits == 9
