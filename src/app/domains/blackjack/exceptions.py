"""Structured business errors for blackjack workflows."""

from __future__ import annotations

import ast
import re
from typing import Any

from app.core.errors import DomainError

_MESSAGE_CODES = (
    ("blackjack disabled", "blackjack.disabled"),
    ("invalid bet", "blackjack.invalid_bet"),
    (
        "hand in progress in tournament",
        "blackjack.hand_in_progress_in_tournament",
    ),
    ("hand in progress in cash game", "blackjack.hand_in_progress_in_cash_game"),
    ("hand in progress", "blackjack.hand_in_progress"),
    ("hand already finished", "blackjack.hand_already_finished"),
    ("not player turn", "blackjack.not_player_turn"),
    ("hand not found", "blackjack.hand_not_found"),
    ("tournament not found", "blackjack.tournament_not_found"),
    ("already registered", "blackjack.already_registered"),
    ("tournament full", "blackjack.tournament_full"),
    ("registration closed", "blackjack.registration_closed"),
    ("tournament finished", "blackjack.tournament_finished"),
    ("tournament not running", "blackjack.tournament_not_running"),
    ("not open for registration", "blackjack.tournament_not_open_for_registration"),
    ("tournament already started", "blackjack.tournament_already_started"),
    (
        "insufficient credits to double",
        "blackjack.insufficient_credits_to_double",
    ),
    ("insufficient credits: need", "blackjack.insufficient_credits_for_entry"),
    ("insufficient credits", "blackjack.insufficient_credits"),
    ("insufficient chips to double", "blackjack.insufficient_chips_to_double"),
    ("insufficient chips", "blackjack.insufficient_chips"),
    ("deal too frequent", "blackjack.deal_too_frequent"),
    ("bet must be a multiple of", "blackjack.bet_must_be_a_multiple_of"),
    ("bet out of range", "blackjack.bet_out_of_range"),
    ("play window must be at least", "blackjack.play_window_must_be_at_least"),
    ("cannot change", "blackjack.cannot_change_after_entrants_joined"),
    (
        "seeded_prize_credits must not decrease",
        "blackjack.seeded_prize_credits_must_not_decrease",
    ),
    (
        "register deadline must be in the future",
        "blackjack.register_deadline_must_be_in_the_future",
    ),
    ("cannot surrender now", "blackjack.cannot_surrender_now"),
    ("tournament entry not found", "blackjack.tournament_entry_not_found"),
    ("tournament title required", "blackjack.tournament_title_required"),
)


class BlackjackError(DomainError, ValueError):
    """A typed blackjack rejection that remains compatible with old callers."""

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


def _legacy_detail(message: str) -> str:
    """Return the existing Chinese transport detail for a legacy message."""
    normalized = message.lower()
    if "blackjack disabled" in normalized:
        return "21 点活动当前未开放"
    if normalized.startswith("invalid bet"):
        raw_options = message.split("one of", 1)[-1].strip()
        try:
            options = ast.literal_eval(raw_options)
            return f"注额不合法，可选档位为 {'、'.join(str(x) for x in options)}"
        except (SyntaxError, ValueError):
            return f"参数不合法：{message}"
    details = (
        ("insufficient credits to double", "积分不足，无法加倍"),
        (
            "hand in progress in cash game",
            "你还有一手现金局的牌未结束，请先去 21 点打完",
        ),
        (
            "hand in progress in tournament",
            "你在锦标赛中还有一手牌未结束，请先到锦标赛里打完",
        ),
        ("hand in progress", "你还有一手牌未结束，请先完成"),
        ("hand already finished", "该手牌已结束"),
        ("not player turn", "当前不是你的回合"),
        ("already doubled", "本手牌已加倍，不能重复加倍"),
        ("cannot double after hit", "已要牌，不能再加倍"),
        ("surrender disabled", "投降当前未开放"),
        ("cannot surrender after hit", "已要牌，不能再投降"),
        ("cannot surrender after double", "已加倍，不能再投降"),
        ("cannot surrender now", "当前不可投降"),
        ("deal too frequent", "操作过于频繁，请稍后再试"),
        ("hand not found", "手牌不存在"),
        ("user stats not found", "用户积分信息不存在"),
        ("tournament not found", "赛事不存在"),
        ("tournament entry not found", "你未报名该赛事"),
        ("already registered", "你已报名该赛事"),
        ("tournament full", "报名人数已满"),
        ("registration closed", "报名已截止"),
        ("not open for registration", "该赛事当前不接受报名"),
        ("tournament already started", "赛事已开赛，无法修改或取消"),
        ("tournament not running", "赛事尚未开赛或已结束"),
        ("tournament finished", "赛事已结束"),
        ("all hands played", "你已打满全部手数"),
        ("eliminated", "你的筹码已不足最小注，已被淘汰"),
        ("insufficient chips to double", "筹码不足，无法加倍"),
        ("insufficient chips", "筹码不足"),
        ("tournament title required", "赛事名称不能为空"),
        ("register deadline must be in the future", "报名截止时点须晚于当前时间"),
        (
            "seeded_prize_credits must not decrease",
            "已有人报名，奖池补贴只能增加、不能减少",
        ),
        ("jackpot seed must be positive", "jackpot seed must be positive"),
    )
    for prefix, detail in details:
        if prefix in normalized:
            return detail
    if "cannot change" in normalized and "after entrants joined" in normalized:
        return "已有人报名，报名费与赛制参数不可再改；如需变更请先取消赛事再重建"
    if "bet must be a multiple of" in normalized:
        step = normalized.split("of", 1)[-1].strip()
        return f"注额须为 {step} 的整数倍"
    if "bet out of range" in normalized:
        return f"注额须在 {message.split(':', 1)[-1].strip()} 筹码之间"
    if "play window must be at least" in normalized:
        minutes = normalized.split("least", 1)[-1].split("minutes", 1)[0].strip()
        return f"赛程过短：报名截止到完赛截止之间至少需要 {minutes} 分钟"
    if (
        "must not exceed" in normalized
        or "must be" in normalized
        or "invalid" in normalized
    ):
        return f"参数不合法：{message}"
    return message


def _error_context(message: str) -> dict[str, Any]:
    """Extract stable parameters needed by transport adapters."""
    context: dict[str, Any] = {"legacy_message": message}
    if "one of" in message:
        raw_options = message.split("one of", 1)[-1].strip()
        try:
            context["bet_options"] = list(ast.literal_eval(raw_options))
        except (SyntaxError, ValueError):
            pass
    match = re.search(r"need ([0-9]+(?:\\.[0-9]+)?)", message)
    if match:
        context["required"] = match.group(1)
    match = re.search(r"multiple of ([0-9]+)", message)
    if match:
        context["bet_step"] = match.group(1)
    match = re.search(r"out of range: (.+)$", message)
    if match:
        context["bet_range"] = match.group(1)
    match = re.search(r"in tournament (\\d+)", message)
    if match:
        context["tournament_id"] = int(match.group(1))
    match = re.search(r"at least ([0-9]+) minutes", message)
    if match:
        context["minutes"] = int(match.group(1))
    return context


def blackjack_error(
    message: str,
    *,
    code: str | None = None,
    status_code: int = 400,
    detail: str | None = None,
) -> BlackjackError:
    """Build a stable blackjack error while preserving its legacy message."""
    normalized = message.lower()
    resolved_code = code
    if resolved_code is None:
        resolved_code = next(
            (candidate for prefix, candidate in _MESSAGE_CODES if prefix in normalized),
            "blackjack.business_rule_violation",
        )
    generated_code = re.sub(r"[^a-z0-9]+", "_", resolved_code.lower()).strip("_")
    effective_status = (
        429 if generated_code == "blackjack_deal_too_frequent" else status_code
    )
    return BlackjackError(
        generated_code,
        message,
        status_code=effective_status,
        detail=detail or _legacy_detail(message),
        payload=_error_context(message),
    )


__all__ = ["BlackjackError", "blackjack_error"]
