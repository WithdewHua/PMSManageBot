"""Public badge workflows; all database work belongs to the repository."""

from app.domains.badges import exceptions, repository
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.identity import service as identity_service


def get_badge_center_config() -> tuple[bool, str | None]:
    return repository.get_badge_center_config()


def set_badge_center_config(enabled: bool, message: str | None = None) -> bool:
    return repository.set_badge_center_config(enabled, message)


def get_badge_by_type(badge_type: str) -> dict | None:
    return repository.get_badge_by_type(badge_type)


def get_badge_by_id(badge_id: int) -> dict | None:
    return repository.get_badge_by_id(badge_id)


def get_all_badges(only_enabled: bool = False) -> list[dict]:
    return repository.get_all_badges(only_enabled)


def create_badge(
    badge_type: str,
    name: str,
    description: str,
    icon_url: str,
    credits_cost: float,
    bonus_percentage: float,
    valid_days: int = 365,
    is_enabled: int = 1,
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


def update_badge(badge_id: int, **changes) -> bool:
    return repository.update_badge(badge_id, **changes)


def delete_badge(badge_id: int) -> bool:
    return repository.delete_badge(badge_id)


def redeem_badge(tg_id: int, badge_id: int) -> dict:
    """Raise a typed BadgeError for business rejections, not for storage faults."""
    return repository.redeem_badge_or_raise(tg_id, badge_id)


def get_user_badges(tg_id: int, only_active: bool = True) -> list[dict]:
    return repository.get_user_badges(tg_id, only_active)


def get_user_active_badges_with_bonus(tg_id: int) -> list[dict]:
    """Retain the detailed manual/read API alongside the aggregate API."""
    return repository.get_user_active_badges_with_bonus(tg_id)


def active_bonus_percentage(tg_id: int) -> float:
    return repository.active_bonus_percentage(tg_id)


def award_badge(tg_id: int, badge_type: str) -> bool:
    return repository.award_badge(tg_id, badge_type)


def award_or_renew_badge(
    tg_id: int, badge_id: int, valid_days: int, cap_days: int | None = None
) -> dict:
    return repository.award_or_renew_badge(
        tg_id=tg_id, badge_id=badge_id, valid_days=valid_days, cap_days=cap_days
    )


def _require_center_enabled() -> None:
    enabled, message = repository.get_badge_center_config()
    if not enabled:
        raise exceptions.BadgeCenterDisabled(message)


def get_badge_center(tg_id: int) -> dict:
    """Assemble the badge-center view without exposing foreign APIs to HTTP."""
    _require_center_enabled()
    badges = repository.get_all_badges(only_enabled=False)
    statistics = identity_service.get_statistics(tg_id)
    if statistics is None:
        raise exceptions.BadgeAccountNotBound()
    return {
        "badges": badges,
        "user_credits": statistics.credits,
        "user_badges": repository.get_user_badges(tg_id, only_active=True),
    }


def redeem_from_center(tg_id: int, badge_id: int) -> dict:
    """Coordinate center access, atomic redemption, and response balance."""
    _require_center_enabled()
    if identity_service.get_statistics(tg_id) is None:
        raise exceptions.BadgeAccountNotBound()
    user_badge = redeem_badge(tg_id, badge_id)
    return {
        "user_badge": user_badge,
        "remaining_credits": credits_service.read_optional(CreditAccount.tg(tg_id)),
    }
