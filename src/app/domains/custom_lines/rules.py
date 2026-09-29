"""Pure custom-line business rules."""

from __future__ import annotations

from datetime import datetime, tzinfo


def month_key(now: datetime, tz: tzinfo) -> str:
    """Return the local calendar month for an aware or naive datetime."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)
    return now.strftime("%Y-%m")


def is_line_valid(is_permanent: int | bool, expires_at: int | None, now: int) -> bool:
    """Return whether a custom line can be brought back online."""
    return bool(is_permanent or (expires_at is not None and expires_at > now))


def effective_traffic_gb(total_traffic: float, traffic_type: str) -> float:
    """Return the one-way traffic basis used by the settlement formula."""
    return (
        float(total_traffic) / 2 if traffic_type == "two_way" else float(total_traffic)
    )


def settlement_credits(
    traffic_gb: float,
    *,
    monthly_price: float,
    total_traffic: float,
    traffic_type: str,
    donation_multiplier: float,
) -> float:
    """Calculate owner credits for traffic consumed by a shared custom line."""
    effective_traffic = effective_traffic_gb(total_traffic, traffic_type)
    if effective_traffic <= 0:
        return 0.0
    price_per_gb = float(monthly_price) / effective_traffic
    return float(traffic_gb) * price_per_gb * float(donation_multiplier) * 0.8


def price_per_gb(
    *, monthly_price: float, total_traffic: float, traffic_type: str
) -> float:
    effective_traffic = effective_traffic_gb(total_traffic, traffic_type)
    return float(monthly_price) / effective_traffic if effective_traffic else 0.0
