from __future__ import annotations

from math import isfinite

from sqlalchemy import select, update

from app.core.db import get_session
from app.domains.credits.exceptions import CreditAccountNotFound, InsufficientCredits
from app.domains.credits.types import (
    CreditAccount,
    CreditMutation,
    CreditTransfer,
    validate_amount,
)
from app.domains.identity.models import EmbyUser, PlexUser, Statistics


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


def add_tx(session, account: CreditAccount, amount: float) -> CreditMutation:
    """Atomically add a positive delta using a caller-owned transaction."""
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
    return CreditMutation(
        account=account,
        before=before,
        after=after,
        delta=delta,
        cache_keys=_cache_keys(session, account, row),
    )


def deduct_tx(session, account: CreditAccount, amount: float) -> CreditMutation:
    """Atomically deduct a positive delta, rejecting insufficient funds."""
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
    return CreditMutation(
        account=account,
        before=before,
        after=after,
        delta=-delta,
        cache_keys=_cache_keys(session, account, row),
    )


def move_tx(session, source: CreditAccount, target: CreditAccount) -> CreditTransfer:
    """Move the entire source balance to another account under one transaction."""
    if source == target:
        raise ValueError("cannot move credits to the same account")
    ordered = sorted((source, target), key=lambda account: account.label)
    locked = {
        account.label: get_tx(session, account, for_update=True) for account in ordered
    }
    amount = locked[source.label][0]
    source_keys = locked[source.label][1]
    target_keys = locked[target.label][1]
    if amount > 0:
        deduct_tx(session, source, amount)
        add_tx(session, target, amount)
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
