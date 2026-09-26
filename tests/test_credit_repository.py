from __future__ import annotations

import pytest

from app.core.db import get_session
from app.domains.credits import repository, service
from app.domains.credits.exceptions import CreditAccountNotFound, InsufficientCredits
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import EmbyUser, PlexUser, Statistics


def _add_credit_rows() -> None:
    with get_session() as session:
        session.add_all(
            [
                Statistics(tg_id=101, donation=0, credits=10),
                Statistics(tg_id=202, donation=0, credits=4),
                PlexUser(
                    id=1,
                    plex_id=501,
                    tg_id=None,
                    credits=7,
                    plex_username="PlexUser",
                ),
                EmbyUser(
                    emby_username="emby-user",
                    emby_id="emby-501",
                    tg_id=None,
                    emby_credits=8,
                ),
            ]
        )


def test_delta_helpers_cover_all_three_account_kinds(session_env) -> None:
    _add_credit_rows()

    with get_session() as session:
        tg = repository.add_tx(session, CreditAccount.tg(101), 1.25)
        plex = repository.deduct_tx(session, CreditAccount.plex(501), 2)
        emby = repository.add_tx(session, CreditAccount.emby("emby-501"), 2)

    assert (tg.before, tg.after, tg.delta) == (10.0, 11.25, 1.25)
    assert (plex.before, plex.after, plex.delta) == (7.0, 5.0, -2.0)
    assert (emby.before, emby.after, emby.delta) == (8.0, 10.0, 2.0)
    assert plex.cache_keys == ("plex:plexuser",)
    assert emby.cache_keys == ("emby:emby-user",)


def test_deduction_rejects_insufficient_balance_without_mutating(session_env) -> None:
    _add_credit_rows()

    with pytest.raises(InsufficientCredits) as raised, get_session() as session:
        repository.deduct_tx(session, CreditAccount.tg(101), 11)

    assert raised.value.available == 10.0
    assert service.read(CreditAccount.tg(101)) == 10.0


def test_transaction_owned_mutation_invalidates_after_commit(
    session_env, monkeypatch
) -> None:
    _add_credit_rows()
    with get_session() as session:
        session.add(
            PlexUser(
                id=2,
                plex_id=502,
                tg_id=101,
                credits=0,
                plex_username="BoundUser",
            )
        )
    invalidated: list[str] = []
    monkeypatch.setattr(service, "invalidate_cache_keys", invalidated.extend)

    with get_session() as session:
        mutation = repository.add_tx(session, CreditAccount.tg(101), 1)
        service.register_cache_invalidation(session, mutation)
        assert invalidated == []

    assert invalidated == ["plex:bounduser"]


def test_transaction_owned_mutation_rolls_back_with_caller(session_env) -> None:
    _add_credit_rows()

    with (
        pytest.raises(RuntimeError, match="settlement failed"),
        get_session() as session,
    ):
        repository.add_tx(session, CreditAccount.tg(101), 5)
        raise RuntimeError("settlement failed")

    assert service.read(CreditAccount.tg(101)) == 10.0


def test_transfer_locks_both_accounts_and_conserves_balance(
    session_env, monkeypatch
) -> None:
    _add_credit_rows()
    invalidated: list[str] = []
    monkeypatch.setattr(service, "invalidate_cache_keys", invalidated.extend)

    result = service.transfer(101, 202, 2)

    assert result.amount == 2.0
    assert result.fee == 0.1
    assert result.current_sender_balance == 7.9
    assert service.read(CreditAccount.tg(101)) == 7.9
    assert service.read(CreditAccount.tg(202)) == 6.0
    assert invalidated == []


def test_transfer_rejects_insufficient_sender_without_partial_update(
    session_env,
) -> None:
    _add_credit_rows()

    with pytest.raises(InsufficientCredits):
        service.transfer(202, 101, 100)

    assert service.read(CreditAccount.tg(202)) == 4.0
    assert service.read(CreditAccount.tg(101)) == 10.0


def test_transfer_rejects_self_transfer(session_env) -> None:
    _add_credit_rows()

    with pytest.raises(ValueError, match="yourself"):
        service.transfer(101, 101, 1)


def test_missing_account_is_rejected(session_env) -> None:
    with pytest.raises(CreditAccountNotFound), get_session() as session:
        repository.add_tx(session, CreditAccount.tg(999), 1)


def test_standalone_service_invalidates_only_after_commit(
    session_env, monkeypatch
) -> None:
    _add_credit_rows()
    invalidated: list[str] = []
    monkeypatch.setattr(service, "invalidate_cache_keys", invalidated.extend)

    mutation = service.add(CreditAccount.tg(101), 2)

    assert mutation.after == 12.0
    assert invalidated == []

    # A Telegram account's cache keys are derived from its bound media rows.
    with get_session() as session:
        session.add(
            PlexUser(
                id=2,
                plex_id=502,
                tg_id=101,
                credits=0,
                plex_username="BoundUser",
            )
        )
    mutation = service.add(CreditAccount.tg(101), 1)
    assert mutation.cache_keys == ("plex:bounduser",)
    assert invalidated == ["plex:bounduser"]
