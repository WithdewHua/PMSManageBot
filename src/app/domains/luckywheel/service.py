"""Luckywheel workflows that coordinate repository operations for interfaces."""

from app.domains.luckywheel import repository


def get_blackjack_freespin_summary(tg_id: int) -> dict:
    return repository.get_blackjack_freespin_summary(tg_id)


def claim_unnotified_blackjack_freespins() -> list[dict]:
    return repository.claim_unnotified_blackjack_freespins()


def list_expiring_blackjack_freespins(*, within_ms: int = 86400 * 1000) -> list[dict]:
    return repository.list_expiring_blackjack_freespins(within_ms=within_ms)


def consume_blackjack_freespin(tg_id: int) -> dict | None:
    return repository.consume_blackjack_freespin(tg_id)


def release_blackjack_freespin(spin_id: int, *, claimed_at_ms: int) -> bool:
    return repository.release_blackjack_freespin(spin_id, claimed_at_ms=claimed_at_ms)


__all__ = [
    "claim_unnotified_blackjack_freespins",
    "consume_blackjack_freespin",
    "get_blackjack_freespin_summary",
    "list_expiring_blackjack_freespins",
    "release_blackjack_freespin",
]
