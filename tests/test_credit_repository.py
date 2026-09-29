from __future__ import annotations

import pytest

from app.core.db import get_session
from app.domains.credits import cache as cache_module
from app.domains.credits import repository, service
from app.domains.credits.exceptions import CreditAccountNotFound, InsufficientCredits
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import EmbyUser, PlexUser, Statistics


class _CacheSpy:
    """Stand-in for the Redis credit cache that records deleted keys."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete(self, key: str) -> None:
        self.deleted.append(key)


def _spy_invalidations(monkeypatch) -> _CacheSpy:
    spy = _CacheSpy()
    monkeypatch.setattr(cache_module, "user_credits_cache", spy)
    return spy


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


def test_delta_persists_two_decimal_rounding(session_env) -> None:
    _add_credit_rows()
    with get_session() as session:
        session.add(Statistics(tg_id=303, donation=0, credits=1.0))

    with get_session() as session:
        mutation = repository.add_tx(session, CreditAccount.tg(303), 0.005)

    assert mutation.after == 1.0
    assert service.read(CreditAccount.tg(303)) == 1.0


def test_transfer_rejects_invalid_fee_rate(session_env) -> None:
    _add_credit_rows()

    with pytest.raises(ValueError, match="fee rate"):
        repository.transfer(101, 202, 1, fee_rate=-1)
    with pytest.raises(ValueError, match="fee rate"):
        repository.transfer(101, 202, 1, fee_rate=float("inf"))


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
    spy = _spy_invalidations(monkeypatch)

    with get_session() as session:
        mutation = repository.add_tx(session, CreditAccount.tg(101), 1)
        assert spy.deleted == []

    assert spy.deleted == ["plex:bounduser"]
    assert mutation.cache_keys == ("plex:bounduser",)


def test_transaction_owned_mutation_rolls_back_with_caller(
    session_env, monkeypatch
) -> None:
    _add_credit_rows()
    spy = _spy_invalidations(monkeypatch)

    with (
        pytest.raises(RuntimeError, match="settlement failed"),
        get_session() as session,
    ):
        repository.add_tx(session, CreditAccount.tg(101), 5)
        raise RuntimeError("settlement failed")

    assert service.read(CreditAccount.tg(101)) == 10.0
    assert spy.deleted == []


def test_transfer_locks_both_accounts_and_conserves_balance(
    session_env, monkeypatch
) -> None:
    _add_credit_rows()
    spy = _spy_invalidations(monkeypatch)

    result = service.transfer(101, 202, 2)

    assert result.amount == 2.0
    assert result.fee == 0.1
    assert result.current_sender_balance == 7.9
    assert service.read(CreditAccount.tg(101)) == 7.9
    assert service.read(CreditAccount.tg(202)) == 6.0
    # 两个 TG 账号都没有绑定媒体行，因此没有可失效的缓存 key
    assert spy.deleted == []


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
    spy = _spy_invalidations(monkeypatch)

    mutation = service.add(CreditAccount.tg(101), 2)

    assert mutation.after == 12.0
    assert spy.deleted == []

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
    assert spy.deleted == ["plex:bounduser"]


def test_repeated_mutations_of_one_account_invalidate_its_key_once(
    session_env, monkeypatch
) -> None:
    _add_credit_rows()
    spy = _spy_invalidations(monkeypatch)

    with get_session() as session:
        first = repository.add_tx(session, CreditAccount.plex(501), 1)
        second = repository.add_tx(session, CreditAccount.plex(501), 2)
        # 显式登记同一条 key 不应产生第二次失效
        service.register_cache_invalidation(session, first, second)
        assert spy.deleted == []

    assert spy.deleted == ["plex:plexuser"]
    assert service.read(CreditAccount.plex(501)) == 10.0


def test_move_then_explicit_registration_invalidates_each_key_once(
    session_env, monkeypatch
) -> None:
    _add_credit_rows()
    spy = _spy_invalidations(monkeypatch)

    with get_session() as session:
        result = repository.move_tx(
            session, CreditAccount.plex(501), CreditAccount.tg(101)
        )
        service.register_cache_invalidation(session, result)
        assert spy.deleted == []

    assert spy.deleted == ["plex:plexuser"]
    assert service.read(CreditAccount.tg(101)) == 17.0
