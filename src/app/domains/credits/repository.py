from __future__ import annotations

from collections.abc import Iterable
from math import isfinite

from sqlalchemy import select, update

from app.core.db import get_session, register_post_commit
from app.domains.credits.cache import invalidate_user_credits
from app.domains.credits.exceptions import CreditAccountNotFound, InsufficientCredits
from app.domains.credits.types import (
    CreditAccount,
    CreditMutation,
    CreditTransfer,
    validate_amount,
)
from app.domains.identity.models import EmbyUser, PlexUser, Statistics


def _cache_invalidation_key(cache_key: str) -> str:
    return f"credit-cache:{cache_key}"


def queue_cache_invalidation(session, cache_keys: Iterable[str]) -> None:
    """Register post-commit cache invalidation for the mutated balances.

    Every credit mutation queues its own invalidation, so a caller cannot forget
    it; re-registering the same key is idempotent.
    """
    for cache_key in dict.fromkeys(cache_keys):
        register_post_commit(
            session,
            _cache_invalidation_key(cache_key),
            lambda key=cache_key: invalidate_user_credits((key,)),
        )


def _account_model(account: CreditAccount):
    if account.kind == "tg":
        return Statistics, Statistics.tg_id, Statistics.credits
    if account.kind == "plex":
        return PlexUser, PlexUser.plex_id, PlexUser.credits
    return EmbyUser, EmbyUser.emby_id, EmbyUser.emby_credits


def _cache_keys(session, account: CreditAccount, row) -> tuple[str, ...]:
    if account.kind == "plex":
        return (f"plex:{row.plex_username.lower()}",) if row.plex_username else ()
    if account.kind == "emby":
        return (f"emby:{row.emby_username.lower()}",) if row.emby_username else ()

    keys: list[str] = []
    plex_names = session.execute(
        select(PlexUser.plex_username).where(PlexUser.tg_id == account.identifier)
    ).scalars()
    keys.extend(f"plex:{name.lower()}" for name in plex_names if name)
    emby_names = session.execute(
        select(EmbyUser.emby_username).where(EmbyUser.tg_id == account.identifier)
    ).scalars()
    keys.extend(f"emby:{name.lower()}" for name in emby_names if name)
    return tuple(keys)


def get_tx(
    session, account: CreditAccount, *, for_update: bool = False
) -> tuple[float, tuple[str, ...]]:
    """Read a credit-bearing row, optionally acquiring its row lock."""
    model, key_column, credit_column = _account_model(account)
    statement = select(model).where(key_column == account.identifier)
    if for_update:
        statement = statement.with_for_update()
    row = session.execute(statement).scalar_one_or_none()
    if row is None:
        raise CreditAccountNotFound(account.label)
    return float(getattr(row, credit_column.key)), _cache_keys(session, account, row)


def _zero_mutation(
    session, account: CreditAccount, *, for_update: bool = False
) -> CreditMutation:
    before, cache_keys = get_tx(session, account, for_update=for_update)
    return CreditMutation(
        account=account,
        before=before,
        after=before,
        delta=0.0,
        cache_keys=cache_keys,
    )


def add_tx(session, account: CreditAccount, amount: float) -> CreditMutation:
    """Atomically add a positive delta using a caller-owned transaction."""
    if not isinstance(amount, bool) and amount == 0:
        return _zero_mutation(session, account)
    delta = validate_amount(amount)
    model, key_column, credit_column = _account_model(account)
    statement = select(model).where(key_column == account.identifier).with_for_update()
    row = session.execute(statement).scalar_one_or_none()
    if row is None:
        raise CreditAccountNotFound(account.label)
    before = float(getattr(row, credit_column.key))
    after = round(before + delta, 2)
    session.execute(
        update(model)
        .where(key_column == account.identifier)
        .values({credit_column: credit_column + (after - before)})
    )
    cache_keys = _cache_keys(session, account, row)
    queue_cache_invalidation(session, cache_keys)
    return CreditMutation(
        account=account,
        before=before,
        after=after,
        delta=delta,
        cache_keys=cache_keys,
    )


def deduct_tx(session, account: CreditAccount, amount: float) -> CreditMutation:
    """Atomically deduct a positive delta, rejecting insufficient funds."""
    if not isinstance(amount, bool) and amount == 0:
        return _zero_mutation(session, account)
    delta = validate_amount(amount)
    model, key_column, credit_column = _account_model(account)
    statement = select(model).where(key_column == account.identifier).with_for_update()
    row = session.execute(statement).scalar_one_or_none()
    if row is None:
        raise CreditAccountNotFound(account.label)
    before = float(getattr(row, credit_column.key))
    if before < delta:
        raise InsufficientCredits(account.label, delta, before)
    after = round(before - delta, 2)
    session.execute(
        update(model)
        .where(key_column == account.identifier)
        .values({credit_column: credit_column + (after - before)})
    )
    cache_keys = _cache_keys(session, account, row)
    queue_cache_invalidation(session, cache_keys)
    return CreditMutation(
        account=account,
        before=before,
        after=after,
        delta=-delta,
        cache_keys=cache_keys,
    )


def charge_premium_traffic_tx(
    session, account: CreditAccount, amount: float
) -> CreditMutation:
    """Charge premium traffic; the only credit debit allowed to overdraw."""
    if not isinstance(amount, bool) and amount == 0:
        return _zero_mutation(session, account)
    delta = validate_amount(amount)
    model, key_column, credit_column = _account_model(account)
    statement = select(model).where(key_column == account.identifier).with_for_update()
    row = session.execute(statement).scalar_one_or_none()
    if row is None:
        raise CreditAccountNotFound(account.label)
    before = float(getattr(row, credit_column.key))
    after = round(before - delta, 2)
    session.execute(
        update(model)
        .where(key_column == account.identifier)
        .values({credit_column: credit_column + (after - before)})
    )
    cache_keys = _cache_keys(session, account, row)
    queue_cache_invalidation(session, cache_keys)
    return CreditMutation(
        account=account,
        before=before,
        after=after,
        delta=-delta,
        cache_keys=cache_keys,
    )


def move_tx(session, source: CreditAccount, target: CreditAccount) -> CreditTransfer:
    """Move the entire source balance to another account under one transaction."""
    if source == target:
        raise ValueError("cannot move credits to the same account")
    ordered = sorted(
        (source, target),
        key=lambda account: (
            account.kind,
            int(account.identifier)
            if account.kind in {"tg", "plex"}
            else str(account.identifier),
        ),
    )
    locked = {
        account.label: get_tx(session, account, for_update=True) for account in ordered
    }
    amount = locked[source.label][0]
    source_keys = locked[source.label][1]
    target_keys = locked[target.label][1]
    if amount != 0:
        source_model, source_key, source_credit = _account_model(source)
        target_model, target_key, target_credit = _account_model(target)
        session.execute(
            update(source_model)
            .where(source_key == source.identifier)
            .values({source_credit: source_credit - amount})
        )
        session.execute(
            update(target_model)
            .where(target_key == target.identifier)
            .values({target_credit: target_credit + amount})
        )
        queue_cache_invalidation(session, (*source_keys, *target_keys))
    return CreditTransfer(
        sender=source,
        recipient=target,
        amount=amount,
        fee=0.0,
        current_sender_balance=0.0,
        cache_keys=tuple(dict.fromkeys((*source_keys, *target_keys))),
    )


def move(source: CreditAccount, target: CreditAccount) -> CreditTransfer:
    """Move an entire balance in a repository-owned transaction."""
    with get_session() as session:
        return move_tx(session, source, target)


def add(account: CreditAccount, amount: float) -> CreditMutation:
    """Add credits in a repository-owned transaction."""
    with get_session() as session:
        return add_tx(session, account, amount)


def deduct(account: CreditAccount, amount: float) -> CreditMutation:
    """Deduct credits in a repository-owned transaction."""
    with get_session() as session:
        return deduct_tx(session, account, amount)


def read(
    account: CreditAccount, *, for_update: bool = False
) -> tuple[float, tuple[str, ...]]:
    """Read credits in a repository-owned transaction."""
    with get_session() as session:
        return get_tx(session, account, for_update=for_update)


def transfer(
    sender_tg_id: int,
    recipient_tg_id: int,
    amount: float,
    *,
    fee_rate: float = 0.05,
) -> CreditTransfer:
    """Transfer credits atomically while locking both accounts canonically."""
    if int(sender_tg_id) == int(recipient_tg_id):
        raise ValueError("cannot transfer credits to yourself")
    transfer_amount = validate_amount(amount)
    normalized_fee_rate = float(fee_rate)
    if not isfinite(normalized_fee_rate) or normalized_fee_rate < 0:
        raise ValueError("fee rate must be finite and non-negative")
    fee = transfer_amount * normalized_fee_rate
    sender = CreditAccount.tg(int(sender_tg_id))
    recipient = CreditAccount.tg(int(recipient_tg_id))
    accounts = sorted((sender, recipient), key=lambda account: int(account.identifier))

    with get_session() as session:
        locked: dict[str, tuple[float, tuple[str, ...]]] = {
            account.label: get_tx(session, account, for_update=True)
            for account in accounts
        }
        sender_balance, sender_keys = locked[sender.label]
        if sender_balance < transfer_amount + fee:
            raise InsufficientCredits(
                sender.label, transfer_amount + fee, sender_balance
            )
        _, recipient_keys = locked[recipient.label]
        sender_mutation = deduct_tx(session, sender, transfer_amount + fee)
        add_tx(session, recipient, transfer_amount)
        result = CreditTransfer(
            sender=sender,
            recipient=recipient,
            amount=transfer_amount,
            fee=fee,
            current_sender_balance=sender_mutation.after,
            cache_keys=tuple(dict.fromkeys((*sender_keys, *recipient_keys))),
        )
    return result


def get_cache_statistics_balances() -> dict[int, float]:
    """Read Telegram balances for the gateway cache refresh."""
    with get_session() as session:
        return dict(session.execute(select(Statistics.tg_id, Statistics.credits)).all())


def list_cache_media_balances(service: str) -> list[tuple]:
    """Return raw account rows, leaving cache keys and side effects to service."""
    with get_session() as session:
        if service == "plex":
            query = select(
                PlexUser.plex_id,
                PlexUser.tg_id,
                PlexUser.credits,
                PlexUser.plex_username,
            )
        else:
            query = select(
                EmbyUser.emby_id,
                EmbyUser.tg_id,
                EmbyUser.emby_credits,
                EmbyUser.emby_username,
            )
        return [tuple(row) for row in session.execute(query).all()]


REASSIGNED_TG_ID_COLUMNS: tuple[str, ...] = ()


def check_tg_id_reassign_tx(session, old_tg_id: int, new_tg_id: int) -> list:
    """Credits have no uniqueness conflict; the locked move is the check boundary."""
    return []


def reassign_tg_id_tx(session, old_tg_id: int, new_tg_id: int) -> dict[str, int]:
    """Move the complete Telegram credit balance through the credit ledger."""
    mutation = move_tx(
        session, CreditAccount.tg(int(old_tg_id)), CreditAccount.tg(int(new_tg_id))
    )
    queue_cache_invalidation(session, mutation.cache_keys)
    return {"statistics.credits": 1 if mutation.amount else 0}


def move_unbound_media_tx(
    session, *, media_service: str, media_record_key: int | str, new_tg_id: int
) -> dict[str, int]:
    """Move an unbound row's balance even before its external ID is resolved."""
    if media_service == "plex":
        model, key, balance = PlexUser, PlexUser.id, PlexUser.credits
    elif media_service == "emby":
        model, key, balance = EmbyUser, EmbyUser.emby_username, EmbyUser.emby_credits
    else:
        raise ValueError("unsupported media credit source")
    target = CreditAccount.tg(new_tg_id)
    _, target_keys = get_tx(session, target, for_update=True)
    row = session.execute(
        select(model)
        .where(key == media_record_key, model.tg_id.is_(None))
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise CreditAccountNotFound(f"{media_service}:{media_record_key}")
    amount = float(getattr(row, balance.key))
    if not isfinite(amount):
        raise ValueError("source balance must be finite")
    source_name = row.plex_username if media_service == "plex" else row.emby_username
    source_keys = (f"{media_service}:{source_name.lower()}",) if source_name else ()
    if amount:
        session.execute(
            update(model)
            .where(key == media_record_key)
            .values({balance: balance - amount})
        )
        session.execute(
            update(Statistics)
            .where(Statistics.tg_id == new_tg_id)
            .values(credits=Statistics.credits + amount)
        )
    queue_cache_invalidation(session, (*source_keys, *target_keys))
    return {
        f"{model.__tablename__}.{balance.key}": int(bool(amount)),
        "statistics.credits": int(bool(amount)),
    }
