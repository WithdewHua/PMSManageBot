"""Static Telegram-ID reassignment coverage declarations."""

from __future__ import annotations

from dataclasses import dataclass

PARTICIPATING_DOMAINS: tuple[str, ...] = (
    "identity",
    "credits",
    "donation",
    "blackjack",
    "badges",
    "gift_pack",
    "luckywheel",
    "treasure",
    "prediction",
    "auction",
    "invitation",
    "lines",
    "custom_lines",
    "crypto_donation",
    "vaultwarden",
    "watch_rewards",
)


@dataclass(frozen=True, slots=True)
class EncodedTgIdLocation:
    domain: str
    table: str
    column: str
    kind: str
    prefix: str | None = None


ENCODED_TG_ID_LOCATIONS: tuple[EncodedTgIdLocation, ...] = (
    EncodedTgIdLocation(
        domain="invitation",
        table="invitation",
        column="used_by",
        kind="prefix",
        prefix="credits_by_",
    ),
    EncodedTgIdLocation(
        domain="gift_pack",
        table="gift_pack",
        column="audience",
        kind="json_path",
        prefix="user_list.tg_ids",
    ),
)

__all__ = [
    "ENCODED_TG_ID_LOCATIONS",
    "PARTICIPATING_DOMAINS",
    "EncodedTgIdLocation",
]
