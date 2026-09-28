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


def _operation_failed(code: str, detail: str) -> LuckywheelError:
    return LuckywheelError(
        code,
        detail,
        status_code=500,
        payload={"detail": detail},
    )


def config_load_failed() -> LuckywheelError:
    return _operation_failed("luckywheel.config_load_failed", "获取配置失败")


def config_save_failed() -> LuckywheelError:
    return _operation_failed("luckywheel.config_save_failed", "保存配置失败")


def update_failed() -> LuckywheelError:
    return _operation_failed("luckywheel.update_failed", "更新配置失败")


def invalid_probability_total(total: float) -> LuckywheelError:
    return LuckywheelError(
        "luckywheel.invalid_probability_total",
        f"奖品概率总和必须为 100%，当前为 {total}%",
        status_code=400,
        payload={"detail": f"奖品概率总和必须为 100%，当前为 {total}%"},
    )


def user_status_failed() -> LuckywheelError:
    return _operation_failed("luckywheel.user_status_failed", "获取用户状态失败")


def randomness_read_failed() -> LuckywheelError:
    return _operation_failed("luckywheel.randomness_read_failed", "获取配置失败")


def randomness_write_failed() -> LuckywheelError:
    return _operation_failed("luckywheel.randomness_write_failed", "保存随机性配置失败")


def randomness_stats_failed() -> LuckywheelError:
    return _operation_failed("luckywheel.randomness_stats_failed", "获取统计信息失败")


def wheel_stats_failed() -> LuckywheelError:
    return _operation_failed("luckywheel.wheel_stats_failed", "获取统计数据失败")


def user_activity_stats_failed() -> LuckywheelError:
    return _operation_failed(
        "luckywheel.user_activity_stats_failed", "获取用户活动统计失败"
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
    "config_load_failed",
    "config_save_failed",
    "insufficient_credits",
    "invalid_probability_total",
    "randomness_read_failed",
    "randomness_stats_failed",
    "randomness_write_failed",
    "ten_spin_insufficient_credits",
    "update_failed",
    "user_activity_stats_failed",
    "user_not_found",
    "user_status_failed",
    "wheel_stats_failed",
]
