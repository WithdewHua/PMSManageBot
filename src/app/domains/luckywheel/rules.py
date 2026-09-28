"""Pure luckywheel prize selection and effect calculations."""

from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass

from app.domains.luckywheel.schemas import LuckyWheelItem


@dataclass(frozen=True)
class PrizeEffects:
    """Database-independent effects of one prize."""

    credits_change: float = 0.0
    invite_codes: int = 0
    premium_days: int = 0


class RandomnessConfig:
    """Runtime random-selection tuning retained for the admin statistics API."""

    USE_WEIGHTED_PROTECTION = True
    PROTECTION_THRESHOLD = 2.0
    PROTECTION_FACTOR = 1.2
    USE_TIME_SEED_MIXING = True
    USE_USER_SEED_MIXING = True

    @classmethod
    def to_dict(cls) -> dict:
        return {
            "use_weighted_protection": cls.USE_WEIGHTED_PROTECTION,
            "protection_threshold": cls.PROTECTION_THRESHOLD,
            "protection_factor": cls.PROTECTION_FACTOR,
            "use_time_seed_mixing": cls.USE_TIME_SEED_MIXING,
            "use_user_seed_mixing": cls.USE_USER_SEED_MIXING,
        }

    @classmethod
    def from_dict(cls, config_dict: dict) -> None:
        cls.USE_WEIGHTED_PROTECTION = config_dict.get(
            "use_weighted_protection", cls.USE_WEIGHTED_PROTECTION
        )
        cls.PROTECTION_THRESHOLD = config_dict.get(
            "protection_threshold", cls.PROTECTION_THRESHOLD
        )
        cls.PROTECTION_FACTOR = config_dict.get(
            "protection_factor", cls.PROTECTION_FACTOR
        )
        cls.USE_TIME_SEED_MIXING = config_dict.get(
            "use_time_seed_mixing", cls.USE_TIME_SEED_MIXING
        )
        cls.USE_USER_SEED_MIXING = config_dict.get(
            "use_user_seed_mixing", cls.USE_USER_SEED_MIXING
        )


DEFAULT_RANDOMNESS = {
    "use_weighted_protection": True,
    "protection_threshold": 2.0,
    "protection_factor": 1.2,
    "use_time_seed_mixing": True,
    "use_user_seed_mixing": True,
}


def pick_prize(
    items: list[LuckyWheelItem] | object,
    *,
    user_id: int | None = None,
    randomness: dict | None = None,
) -> LuckyWheelItem:
    """Pick a prize without reading configuration or performing I/O.

    Both a list of items and a ``LuckyWheelConfig``-like object are accepted so
    callers can keep configuration loading outside this pure rules module.
    """
    items = getattr(items, "items", items)
    if not items:
        raise ValueError("奖品列表不能为空")

    valid_items = [item for item in items if item.probability > 0]
    if not valid_items:
        raise ValueError("没有有效的奖品（概率必须大于0）")

    options = {**RandomnessConfig.to_dict(), **(randomness or {})}
    secure_random = secrets.SystemRandom()
    if options["use_time_seed_mixing"]:
        secure_random.seed(time.time_ns() % 1_000_000)

    adjusted_items: list[tuple[LuckyWheelItem, float]] = []
    for item in valid_items:
        probability = float(item.probability)
        if options["use_weighted_protection"] and probability < float(
            options["protection_threshold"]
        ):
            probability *= float(options["protection_factor"])
        adjusted_items.append((item, probability))

    total_probability = sum(probability for _, probability in adjusted_items)
    if options["use_user_seed_mixing"] and user_id:
        user_entropy = (
            hash(str(user_id) + str(secure_random.randint(1, 1_000_000))) % 1_000_000
        )
        random_value = (
            secure_random.uniform(0, total_probability) + user_entropy / 1_000_000
        ) % total_probability
    else:
        random_value = secure_random.uniform(0, total_probability)

    accumulated_probability = 0.0
    for item, probability in adjusted_items:
        accumulated_probability += probability
        if random_value < accumulated_probability:
            return item
    return max(adjusted_items, key=lambda pair: pair[1])[0]


def prize_effects(
    prize: LuckyWheelItem | str, current_credits: float = 0.0
) -> PrizeEffects:
    """Calculate the effects of a prize; never mutates a database or account."""
    name = prize.name if isinstance(prize, LuckyWheelItem) else str(prize)
    normalized = name.lower().strip()

    if "谢谢参与" in normalized:
        return PrizeEffects()
    if "翻倍" in normalized:
        return PrizeEffects(credits_change=round(float(current_credits), 2))
    if "减半" in normalized:
        return PrizeEffects(credits_change=round(-float(current_credits) / 2, 2))
    if "邀请码" in normalized:
        return PrizeEffects(invite_codes=1)
    if "premium" in normalized:
        days_match = re.search(r"(\d+)", normalized)
        return PrizeEffects(premium_days=int(days_match.group(1)) if days_match else 0)

    match = re.search(r"([+-])(\d+)", normalized)
    if match:
        sign, amount = match.groups()
        value = int(amount)
        return PrizeEffects(credits_change=float(value if sign == "+" else -value))
    return PrizeEffects()


__all__ = [
    "DEFAULT_RANDOMNESS",
    "PrizeEffects",
    "RandomnessConfig",
    "pick_prize",
    "prize_effects",
]
