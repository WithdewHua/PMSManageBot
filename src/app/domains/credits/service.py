"""Transaction-aware credit ledger services."""

from __future__ import annotations

from collections.abc import Iterable

from app.core.cache import user_credits_cache
from app.core.log import logger
from app.domains.credits import repository
from app.domains.credits.types import (
    CreditAccount,
    CreditMutation,
    CreditTransfer,
    validate_amount,
)


def invalidate_cache_keys(keys: Iterable[str]) -> None:
    """Best-effort cache invalidation after the authoritative transaction commits."""
    for key in dict.fromkeys(keys):
        try:
            user_credits_cache.delete(key)
        except Exception as error:  # pragma: no cover - depends on Redis availability
            logger.warning(f"Failed to invalidate credit cache {key}: {error}")


def add(account: CreditAccount, amount: float) -> CreditMutation:
    """Add credits in a new transaction, invalidating cache after commit."""
    mutation = repository.add(account, amount)
    invalidate_cache_keys(mutation.cache_keys)
    return mutation


def apply_tx(session, account: CreditAccount, delta: float) -> CreditMutation | None:
    """Apply a signed delta inside a caller-owned transaction."""
    if delta > 0:
        return repository.add_tx(session, account, delta)
    if delta < 0:
        return repository.deduct_tx(session, account, -delta)
    return None


def deduct(account: CreditAccount, amount: float) -> CreditMutation:
    """Deduct credits in a new transaction, invalidating cache after commit."""
    mutation = repository.deduct(account, amount)
    invalidate_cache_keys(mutation.cache_keys)
    return mutation


def read(account: CreditAccount, *, for_update: bool = False) -> float:
    """Read a credit balance in a short standalone transaction."""
    balance, _ = repository.read(account, for_update=for_update)
    return balance


def transfer(sender_tg_id: int, recipient_tg_id: int, amount: float) -> CreditTransfer:
    """Transfer credits and invalidate both accounts after one commit."""
    result = repository.transfer(sender_tg_id, recipient_tg_id, amount)
    invalidate_cache_keys(result.cache_keys)
    return result


def collect_cache_keys(*mutations: CreditMutation) -> tuple[str, ...]:
    """Collect unique keys for invalidation after a caller-owned transaction."""
    return tuple(
        dict.fromkeys(key for mutation in mutations for key in mutation.cache_keys)
    )


def register_cache_invalidation(session, *mutations: CreditMutation) -> None:
    """Schedule cache invalidation for the generic post-commit hook."""
    keys = collect_cache_keys(*mutations)
    if not keys:
        return
    callbacks = session.info.setdefault("post_commit_callbacks", [])
    callbacks.append(lambda: invalidate_cache_keys(keys))


__all__ = [
    "add",
    "apply_tx",
    "collect_cache_keys",
    "deduct",
    "invalidate_cache_keys",
    "read",
    "register_cache_invalidation",
    "transfer",
    "validate_amount",
]
