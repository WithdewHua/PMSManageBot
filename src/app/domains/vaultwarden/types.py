"""Pure value types for the Vaultwarden domain."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RedeemResult:
    """Outcome of a Vaultwarden account redemption attempt."""

    success: bool
    message: str
    credits_deducted: float | None = None
    remaining_credits: float | None = None


@dataclass(frozen=True, slots=True)
class RedeemInfo:
    """Current redemption eligibility and requirement summary."""

    enabled: bool
    required_credits: int
    current_credits: float
    can_redeem: bool
    error_message: str | None = None


__all__ = ["RedeemInfo", "RedeemResult"]
