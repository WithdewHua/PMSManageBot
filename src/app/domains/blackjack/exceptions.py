"""Structured business errors for blackjack workflows."""

from __future__ import annotations

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
    (
        "insufficient credits to double",
        "blackjack.insufficient_credits_to_double",
    ),
    ("insufficient credits: need", "blackjack.insufficient_credits_for_entry"),
    ("insufficient credits", "blackjack.insufficient_credits"),
    ("insufficient chips to double", "blackjack.insufficient_chips_to_double"),
    ("insufficient chips", "blackjack.insufficient_chips"),
    ("deal too frequent", "blackjack.deal_too_frequent"),
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
    return BlackjackError(
        generated_code,
        message,
        status_code=status_code,
        detail=detail,
    )


__all__ = ["BlackjackError", "blackjack_error"]
