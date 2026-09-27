"""Badge workflows shared by domain services and background jobs."""

from app.domains.badges import repository


def get_badge_by_type(badge_type: str) -> dict | None:
    return repository.get_badge_by_type(badge_type)


def create_badge(
    badge_type: str,
    name: str,
    description: str,
    icon_url: str,
    credits_cost: float,
    bonus_percentage: float,
    valid_days: int,
    is_enabled: int,
) -> dict | None:
    return repository.create_badge(
        badge_type=badge_type,
        name=name,
        description=description,
        icon_url=icon_url,
        credits_cost=credits_cost,
        bonus_percentage=bonus_percentage,
        valid_days=valid_days,
        is_enabled=is_enabled,
    )


def award_or_renew_badge(
    tg_id: int,
    badge_id: int,
    valid_days: int,
    cap_days: int | None = None,
) -> dict:
    return repository.award_or_renew_badge(
        tg_id=tg_id,
        badge_id=badge_id,
        valid_days=valid_days,
        cap_days=cap_days,
    )


__all__ = [
    "award_or_renew_badge",
    "create_badge",
    "get_badge_by_type",
]
