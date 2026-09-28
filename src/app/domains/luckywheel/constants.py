"""Shared luckywheel source vocabulary."""

FREE_SPIN_SOURCE_TO_WHEEL_SOURCE = {
    "blackjack": "blackjack_free",
    "gift_pack": "gift_pack_free",
}
WHEEL_SOURCE_TO_FREE_SPIN_SOURCE = {
    value: key for key, value in FREE_SPIN_SOURCE_TO_WHEEL_SOURCE.items()
}


def wheel_source_for_free_spin(free_spin_source: str | None) -> str:
    """Map a ledger source to the immutable wheel-statistics source snapshot."""
    return FREE_SPIN_SOURCE_TO_WHEEL_SOURCE.get(
        free_spin_source or "blackjack", "blackjack_free"
    )


__all__ = [
    "FREE_SPIN_SOURCE_TO_WHEEL_SOURCE",
    "WHEEL_SOURCE_TO_FREE_SPIN_SOURCE",
    "wheel_source_for_free_spin",
]
