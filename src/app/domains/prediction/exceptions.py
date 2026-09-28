"""Structured business errors for prediction workflows.

Each rejection constructor carries the *final* transport values (status code and
Chinese ``detail``) that the router used to derive by scanning the exception
text. The English ``message`` is kept as the exception's text so any remaining
``except ValueError`` caller (this domain is mid-migration) still sees the
legacy message.

Two entries deliberately preserve shadowed behaviour: the router matched a bare
``"not found"`` before the more specific ``"user stats not found"``, so a bet
placed by a user without a statistics row keeps answering 404 "预测题目不存在".
The same holds for the two different ``betting_deadline`` details (create /
submit versus review).
"""

from __future__ import annotations

from typing import Any

from app.core.errors import DomainError


class PredictionError(DomainError, ValueError):
    """A typed prediction rejection that stays compatible with ``except ValueError``."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        detail: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        response_payload = dict(payload or {})
        response_payload.setdefault("detail", detail or message)
        super().__init__(
            code,
            message,
            status_code=status_code,
            payload=response_payload,
        )


#: 下注
def market_not_found() -> PredictionError:
    return PredictionError(
        "prediction.market_not_found",
        "market not found",
        status_code=404,
        detail="预测题目不存在",
    )


def market_not_open() -> PredictionError:
    return PredictionError(
        "prediction.market_not_open", "market not open", detail="当前不可押注"
    )


def betting_closed() -> PredictionError:
    return PredictionError(
        "prediction.betting_closed", "betting closed", detail="当前不可押注"
    )


def max_bet_exceeded() -> PredictionError:
    return PredictionError(
        "prediction.max_bet_exceeded",
        "max bet per user exceeded",
        detail="超过该题目个人押注上限",
    )


def user_stats_not_found() -> PredictionError:
    """被 ``not found`` 遮蔽的分支：现状返回 404「预测题目不存在」。"""
    return PredictionError(
        "prediction.user_stats_not_found",
        "user stats not found",
        status_code=404,
        detail="预测题目不存在",
    )


def insufficient_credits() -> PredictionError:
    return PredictionError(
        "prediction.insufficient_credits", "insufficient credits", detail="积分不足"
    )


def invalid_option() -> PredictionError:
    return PredictionError("prediction.invalid_option", "invalid option")


def amount_must_be_positive() -> PredictionError:
    return PredictionError("prediction.amount_must_be_positive", "amount must be > 0")


#: 投稿与审核
def submission_not_found() -> PredictionError:
    return PredictionError(
        "prediction.submission_not_found",
        "submission not found",
        status_code=404,
        detail="投稿不存在",
    )


def submission_already_reviewed() -> PredictionError:
    return PredictionError(
        "prediction.submission_already_reviewed",
        "submission already reviewed",
        detail="该投稿已审核",
    )


def deadline_invalid() -> PredictionError:
    """创建 / 投稿的截止时间拒绝。"""
    return PredictionError(
        "prediction.deadline_invalid",
        "betting_deadline must be in the future",
        detail="请设置有效的截止时间",
    )


def deadline_missing() -> PredictionError:
    return PredictionError(
        "prediction.deadline_missing",
        "betting_deadline is required",
        detail="请设置有效的截止时间",
    )


def review_deadline_invalid() -> PredictionError:
    """审核改动后的截止时间拒绝（与创建使用不同的 detail）。"""
    return PredictionError(
        "prediction.review_deadline_invalid",
        "betting_deadline must be in the future",
        detail="截止时间必须晚于当前时间",
    )


def title_required() -> PredictionError:
    return PredictionError("prediction.title_required", "title is required")


def invalid_fee_split() -> PredictionError:
    return PredictionError("prediction.invalid_fee_split", "invalid fee split")


#: 截止与开奖
def market_already_settled() -> PredictionError:
    return PredictionError(
        "prediction.market_already_settled", "market already settled"
    )


def invalid_result_option() -> PredictionError:
    return PredictionError("prediction.invalid_result_option", "invalid result option")


__all__ = [
    "PredictionError",
    "amount_must_be_positive",
    "betting_closed",
    "deadline_invalid",
    "deadline_missing",
    "insufficient_credits",
    "invalid_fee_split",
    "invalid_option",
    "invalid_result_option",
    "market_already_settled",
    "market_not_found",
    "market_not_open",
    "max_bet_exceeded",
    "review_deadline_invalid",
    "submission_already_reviewed",
    "submission_not_found",
    "title_required",
    "user_stats_not_found",
]
