"""Typed business rejections; the badge router preserves legacy responses."""

from app.core.errors import DomainError


class BadgeError(DomainError, ValueError):
    """Base for badge business rejections."""


class BadgeNotFound(BadgeError):
    def __init__(self) -> None:
        super().__init__("badge_not_found", "勋章不存在")


class BadgeUnavailable(BadgeError):
    def __init__(self) -> None:
        super().__init__("badge_unavailable", "该勋章暂不可兑换")


class BadgeAlreadyOwned(BadgeError):
    def __init__(self) -> None:
        super().__init__("badge_already_owned", "您已经拥有该勋章")


class BadgeUserNotFound(BadgeError):
    def __init__(self) -> None:
        super().__init__("badge_user_not_found", "用户不存在")


class BadgeInsufficientCredits(BadgeError):
    def __init__(self, cost: float) -> None:
        super().__init__(
            "badge_insufficient_credits",
            f"积分不足，需要 {cost} 积分",
            payload={"credits_cost": cost},
        )


class BadgeCenterDisabled(BadgeError):
    def __init__(self, message: str | None) -> None:
        super().__init__("badge_center_disabled", message or "勋章中心功能未启用")


class BadgeAccountNotBound(BadgeError):
    def __init__(self) -> None:
        super().__init__("badge_account_not_bound", "用户未绑定 Plex/Emby 账户")
