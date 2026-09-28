"""Typed business errors raised by the auction domain."""

from app.core.errors import DomainError


class AuctionError(DomainError, ValueError):
    """An auction business rejection compatible with legacy ValueError callers."""


def _error(code: str, detail: str, *, status_code: int = 400) -> AuctionError:
    return AuctionError(
        code,
        detail,
        status_code=status_code,
        payload={"detail": detail},
    )


def not_found() -> AuctionError:
    return _error("auction.not_found", "竞拍不存在", status_code=404)


def ended() -> AuctionError:
    return _error("auction.ended", "竞拍已结束")


def expired() -> AuctionError:
    return _error("auction.expired", "竞拍已过期")


def own_auction() -> AuctionError:
    return _error("auction.own_auction", "不能对自己创建的竞拍出价")


def bid_too_low(current_price: float) -> AuctionError:
    return _error("auction.bid_too_low", f"出价必须高于当前价格 {current_price}")


def credits_unavailable() -> AuctionError:
    return _error("auction.credits_unavailable", "无法获取用户积分信息")


def insufficient_credits(current: float, required: float) -> AuctionError:
    return _error(
        "auction.insufficient_credits",
        f"积分不足，当前积分: {current}，需要: {required}",
    )


def create_failed() -> AuctionError:
    return _error("auction.create_failed", "创建竞拍失败", status_code=500)


def bid_failed() -> AuctionError:
    return _error("auction.bid_failed", "出价失败", status_code=500)


def finish_failed() -> AuctionError:
    return _error("auction.finish_failed", "结束竞拍失败", status_code=500)


def update_failed() -> AuctionError:
    return _error("auction.update_failed", "更新竞拍失败", status_code=500)


def delete_failed() -> AuctionError:
    return _error("auction.delete_failed", "删除竞拍失败", status_code=500)


def operation_failed(detail: str) -> AuctionError:
    return _error("auction.operation_failed", detail, status_code=500)


__all__ = [
    "AuctionError",
    "bid_failed",
    "bid_too_low",
    "create_failed",
    "credits_unavailable",
    "delete_failed",
    "ended",
    "expired",
    "finish_failed",
    "insufficient_credits",
    "not_found",
    "operation_failed",
    "own_auction",
    "update_failed",
]
