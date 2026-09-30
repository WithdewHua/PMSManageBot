"""Transaction-aware credit ledger services."""

from __future__ import annotations

from collections.abc import Iterable

from app.domains.credits import repository
from app.domains.credits.cache import invalidate_user_credits
from app.domains.credits.config import CREDITS_CONFIG
from app.domains.credits.exceptions import CreditAccountNotFound
from app.domains.credits.types import (
    CreditAccount,
    CreditMutation,
    CreditTransfer,
    validate_amount,
)


def is_transfer_enabled() -> bool:
    return bool(CREDITS_CONFIG.get().transfer_enabled)


def set_transfer_enabled(enabled: bool):
    return CREDITS_CONFIG.update(transfer_enabled=enabled)


def invalidate_cache_keys(keys: Iterable[str]) -> None:
    """Best-effort cache invalidation after the authoritative transaction commits."""
    invalidate_user_credits(keys)


def add(account: CreditAccount, amount: float) -> CreditMutation:
    """Add credits in a new transaction; the mutation queues cache invalidation."""
    return repository.add(account, amount)


def apply_tx(session, account: CreditAccount, delta: float) -> CreditMutation | None:
    """Apply a signed delta inside a caller-owned transaction."""
    if delta > 0:
        return repository.add_tx(session, account, delta)
    if delta < 0:
        return repository.deduct_tx(session, account, -delta)
    return None


def deduct(account: CreditAccount, amount: float) -> CreditMutation:
    """Deduct credits in a new transaction; the mutation queues invalidation."""
    return repository.deduct(account, amount)


def charge_premium_traffic_tx(
    session, account: CreditAccount, amount: float
) -> CreditMutation:
    """Charge premium traffic inside a caller-owned transaction; overdraft is allowed."""
    return repository.charge_premium_traffic_tx(session, account, amount)


def read_optional(account: CreditAccount) -> float | None:
    """Read a balance, returning None when the account row does not exist."""
    try:
        return read(account)
    except CreditAccountNotFound:
        return None


def move(source: CreditAccount, target: CreditAccount) -> CreditTransfer:
    """Move a whole unbound account balance; the move queues invalidation."""
    return repository.move(source, target)


def read(account: CreditAccount, *, for_update: bool = False) -> float:
    """Read a credit balance in a short standalone transaction."""
    balance, _ = repository.read(account, for_update=for_update)
    return balance


def transfer(sender_tg_id: int, recipient_tg_id: int, amount: float) -> CreditTransfer:
    """Transfer credits; both mutations queue cache invalidation on commit."""
    return repository.transfer(sender_tg_id, recipient_tg_id, amount)


def collect_cache_keys(*mutations: CreditMutation | CreditTransfer) -> tuple[str, ...]:
    """Collect unique keys for invalidation after a caller-owned transaction."""
    return tuple(
        dict.fromkeys(key for mutation in mutations for key in mutation.cache_keys)
    )


def register_cache_invalidation(
    session, *mutations: CreditMutation | CreditTransfer
) -> None:
    """Schedule cache invalidation for mutations already applied to the session.

    Credit mutations queue their own invalidation, so this is only needed for
    cache keys that were not derived from a mutation; re-registering the same
    key is idempotent.
    """
    repository.queue_cache_invalidation(session, collect_cache_keys(*mutations))


__all__ = [
    "add",
    "apply_tx",
    "charge_premium_traffic_tx",
    "collect_cache_keys",
    "deduct",
    "invalidate_cache_keys",
    "move",
    "read",
    "read_optional",
    "register_cache_invalidation",
    "transfer",
    "validate_amount",
]


def refresh_balance_cache() -> None:
    """Refresh gateway balances, preserving legacy service ordering and keys."""
    from app.domains.credits import cache

    statistics = repository.get_cache_statistics_balances()
    for service in ("plex", "emby"):
        for media_id, tg_id, balance, username in repository.list_cache_media_balances(
            service
        ):
            if service == "plex" and not media_id:
                continue
            if tg_id:
                balance = statistics.get(tg_id, 0)
            cache.user_credits_cache.put(f"{service}:{username.lower()}", balance)
