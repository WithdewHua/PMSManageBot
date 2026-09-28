"""Typed business errors raised by the treasure domain."""

from app.core.errors import DomainError


class TreasureError(DomainError, ValueError):
    """A treasure business rejection compatible with legacy ValueError callers."""


def _error(code: str, detail: str, *, status_code: int = 400) -> TreasureError:
    return TreasureError(
        code,
        detail,
        status_code=status_code,
        payload={"detail": detail},
    )


def issue_not_found() -> TreasureError:
    return _error("treasure.issue_not_found", "期数不存在", status_code=404)


def issue_not_active() -> TreasureError:
    return _error("treasure.issue_not_active", "本期已结束")


def issue_full() -> TreasureError:
    return _error("treasure.issue_full", "本期已满员")


def quantity_invalid() -> TreasureError:
    return _error("treasure.quantity_invalid", "参与份数必须大于0")


def quantity_too_large() -> TreasureError:
    return _error("treasure.quantity_too_large", "参与份数过大")


def purchase_limit_exceeded(max_per_user: int) -> TreasureError:
    return _error(
        "treasure.purchase_limit_exceeded",
        "超过单用户购买上限",
    )


def user_stats_not_found() -> TreasureError:
    return _error("treasure.user_stats_not_found", "期数不存在", status_code=404)


def insufficient_credits() -> TreasureError:
    return _error("treasure.insufficient_credits", "积分不足")


def invalid_number_range() -> TreasureError:
    return _error("treasure.invalid_number_range", "invalid number range")


def create_total_shares_invalid() -> TreasureError:
    return _error("treasure.total_shares_invalid", "总份数必须大于0")


def create_not_divisible() -> TreasureError:
    return _error("treasure.total_not_divisible", "总所需积分必须能被每份积分整除")


def create_credits_invalid() -> TreasureError:
    return _error(
        "treasure.credits_invalid",
        "积分配置不合法（奖池必须大于0且不超过总积分）",
    )


def start_number_invalid() -> TreasureError:
    return _error("treasure.start_number_invalid", "start_number must be > 0")


def cancel_not_active() -> TreasureError:
    return _error("treasure.cancel_not_active", "仅进行中的期数可删除")


def operation_failed(detail: str) -> TreasureError:
    return _error("treasure.operation_failed", detail, status_code=500)


__all__ = [
    "TreasureError",
    "cancel_not_active",
    "create_credits_invalid",
    "create_not_divisible",
    "create_total_shares_invalid",
    "insufficient_credits",
    "invalid_number_range",
    "issue_full",
    "issue_not_active",
    "issue_not_found",
    "operation_failed",
    "purchase_limit_exceeded",
    "quantity_invalid",
    "quantity_too_large",
    "start_number_invalid",
    "user_stats_not_found",
]
