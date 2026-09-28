"""Typed luckywheel workflow errors."""

from app.core.errors import DomainError


class LuckywheelError(DomainError, ValueError):
    """A luckywheel business rejection compatible with legacy ValueError callers."""


def user_not_found(tg_id: int) -> LuckywheelError:
    return LuckywheelError(
        "luckywheel.user_not_found",
        f"未找到用户 {int(tg_id)}",
        status_code=404,
        payload={"detail": f"未找到用户 {int(tg_id)}"},
    )


def insufficient_credits(required: float) -> LuckywheelError:
    required_text = int(required) if float(required).is_integer() else required
    return LuckywheelError(
        "luckywheel.insufficient_credits",
        f"积分不足，需要至少 {required_text} 积分才能参与",
        status_code=400,
        payload={"detail": f"积分不足，需要至少 {required_text} 积分才能参与"},
    )


def ten_spin_insufficient_credits(required: float) -> LuckywheelError:
    required_text = int(required) if float(required).is_integer() else required
    return LuckywheelError(
        "luckywheel.ten_spin_insufficient_credits",
        f"积分不足，十连抽需要至少 {required_text} 积分才能参与",
        status_code=400,
        payload={"detail": f"积分不足，十连抽需要至少 {required_text} 积分才能参与"},
    )


__all__ = [
    "LuckywheelError",
    "insufficient_credits",
    "ten_spin_insufficient_credits",
    "user_not_found",
]
