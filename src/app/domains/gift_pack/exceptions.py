"""Structured business errors for gift-pack workflows.

One exception type per rejection family (design D8): the transport detail stays
exactly what the legacy code returned, while callers stop matching on substrings.
``GiftPackError`` also derives from ``ValueError`` so the transitional callers and
the existing tests that catch ``ValueError`` keep working until task 5.4 removes
the last string comparison from the router.
"""

from __future__ import annotations

from typing import Any

from app.core.errors import DomainError

#: Legacy message -> stable code, longest/most specific prefixes first.
_MESSAGE_CODES = (
    ("礼包不存在", "gift_pack_not_found"),
    ("礼包已停用", "gift_pack_disabled"),
    ("礼包尚未开始", "gift_pack_not_started"),
    ("礼包已结束", "gift_pack_ended"),
    ("礼包已被领完", "gift_pack_sold_out"),
    ("你已领取过该礼包", "gift_pack_already_claimed"),
    ("用户积分信息不存在", "gift_pack_user_missing"),
    ("不满足领取条件", "gift_pack_conditions_not_met"),
    ("请先绑定媒体账号后再领取", "gift_pack_reward_rejected"),
    ("争霸赛余额数量必须为正", "gift_pack_reward_rejected"),
    ("免费机会的次数与有效天数必须为正", "gift_pack_reward_rejected"),
    ("邀请码数量必须为正", "gift_pack_reward_rejected"),
    ("不支持的奖励类型", "gift_pack_reward_rejected"),
    ("不支持的解锁类型", "gift_pack_reward_rejected"),
    ("引用", "gift_pack_referenced"),
    ("礼包不能引用自身", "gift_pack_referenced"),
    ("该礼包已有用户领取", "gift_pack_referenced"),
    ("礼包至少需要一项奖励", "gift_pack_invalid"),
    ("结束时间必须晚于开始时间", "gift_pack_invalid"),
    ("任务截止时间", "gift_pack_invalid"),
    ("限量份数", "gift_pack_invalid"),
    ("开启开始通知", "gift_pack_invalid"),
    ("礼包开始后不能修改", "gift_pack_invalid"),
    ("不支持的礼包条件", "gift_pack_invalid"),
)


class GiftPackError(DomainError, ValueError):
    """A typed gift-pack rejection that remains compatible with old callers."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        detail: Any | None = None,
        payload: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        response_payload = dict(payload or {})
        response_payload.setdefault("detail", detail if detail is not None else message)
        super().__init__(
            code,
            message,
            status_code=status_code,
            payload=response_payload,
            cause=cause,
        )


class ConditionsNotMet(GiftPackError):
    """Eligibility rejection that carries the per-condition progress."""

    def __init__(
        self,
        requirements: list[dict[str, Any]] | None = None,
        *,
        message: str = "不满足领取条件",
        status_code: int = 400,
        detail: Any | None = None,
    ) -> None:
        progress = list(requirements or [])
        payload: dict[str, Any] = {"requirements": progress}
        # 前端要展示逐项进度：有进度时 detail 是结构化对象，没有时退回原文。
        resolved_detail = detail
        if resolved_detail is None:
            resolved_detail = (
                {"message": message, "requirements": progress} if progress else message
            )
        super().__init__(
            "gift_pack_conditions_not_met",
            message,
            status_code=status_code,
            detail=resolved_detail,
            payload=payload,
        )
        self.requirements = progress


def _resolve_code(message: str, code: str | None) -> str:
    if code is not None:
        return code
    for prefix, candidate in _MESSAGE_CODES:
        if prefix in message:
            return candidate
    return "gift_pack_invalid"


def gift_pack_error(
    message: str,
    *,
    code: str | None = None,
    status_code: int = 400,
    detail: Any | None = None,
    payload: dict[str, Any] | None = None,
) -> GiftPackError:
    """Build a typed rejection while preserving the legacy transport detail.

    ``status_code`` is decided at the raise site: the same "礼包不存在" is a 400
    while claiming or editing and only the toggle/statistics paths map a missing
    pack to 404.
    """
    resolved_code = _resolve_code(message, code)
    if resolved_code == "gift_pack_conditions_not_met":
        return ConditionsNotMet(status_code=status_code, detail=detail or message)
    return GiftPackError(
        resolved_code,
        message,
        status_code=status_code,
        detail=detail or message,
        payload=payload,
    )


def gift_pack_not_found(message: str = "礼包不存在", **kwargs: Any) -> GiftPackError:
    return gift_pack_error(message, code="gift_pack_not_found", **kwargs)


def wrap_reward_rejection(error: BaseException) -> GiftPackError:
    """把发放阶段的外域业务异常包装成礼包拒绝，保留原文。

    外域抛出的 `ValueError`（含各自的 `DomainError`+`ValueError` 子类）代表
    “这笔奖励现在发不了”，对用户而言仍是 400 的业务拒绝、不应该通知管理员；
    原文进 detail，异常本身挂在 __cause__ 上便于排查。
    """
    if isinstance(error, GiftPackError):
        return error
    message = str(error) or "奖励发放失败"
    return GiftPackError(
        "gift_pack_reward_rejected",
        message,
        status_code=400,
        detail=message,
        cause=error,
    )


__all__ = [
    "ConditionsNotMet",
    "GiftPackError",
    "gift_pack_error",
    "gift_pack_not_found",
    "wrap_reward_rejection",
]
