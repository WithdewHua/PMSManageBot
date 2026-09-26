import math
from datetime import datetime

from app.core.config import settings


def _get_premium_daily_limit(is_premium: bool) -> int:
    return (
        settings.PREMIUM_USER_TRAFFIC_LIMIT
        if is_premium
        else settings.USER_TRAFFIC_LIMIT
    )


def _get_traffic_cost_credits(chargeable_bytes: int) -> float:
    if chargeable_bytes <= 0:
        return 0

    gb_tiers = math.ceil(chargeable_bytes / (10 * 1024 * 1024 * 1024))
    return round(gb_tiers * settings.CREDITS_COST_PER_10GB, 2)


def _parse_debt_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None

    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=settings.TZ)
    except ValueError:
        return None


def _resolve_premium_status_for_settlement(
    current_is_premium: bool,
    premium_status_updated_at: int | None,
    settlement_date: datetime,
) -> bool:
    if not premium_status_updated_at:
        return current_is_premium

    status_updated_at = datetime.fromtimestamp(
        premium_status_updated_at, tz=settings.TZ
    )
    settlement_day_end = settlement_date.replace(
        hour=23, minute=59, second=59, microsecond=999999
    )
    if status_updated_at > settlement_day_end:
        return not current_is_premium

    return current_is_premium


def _settle_premium_traffic_usage(
    traffic_usage_premium: int,
    is_premium: bool,
    debt_bytes: int,
    debt_updated_date: str | None,
    settlement_date: datetime,
) -> dict:
    daily_limit = _get_premium_daily_limit(is_premium)
    max_debt_bytes = daily_limit * 2
    previous_debt = max(int(debt_bytes or 0), 0)
    debt_date = _parse_debt_date(debt_updated_date)
    gap_days = 0

    if debt_date and debt_date.date() < settlement_date.date():
        gap_days = (settlement_date.date() - debt_date.date()).days - 1
        gap_days = max(gap_days, 0)

    recovered_before_today = min(previous_debt, gap_days * daily_limit)
    debt_before_today = max(previous_debt - recovered_before_today, 0)
    effective_limit = max(daily_limit - debt_before_today, 0)
    end_of_day_debt_raw = max(
        debt_before_today + traffic_usage_premium - daily_limit, 0
    )
    chargeable_bytes = max(end_of_day_debt_raw - max_debt_bytes, 0)
    next_debt_bytes = min(end_of_day_debt_raw, max_debt_bytes)
    exceed_bytes = max(traffic_usage_premium - effective_limit, 0)
    traffic_cost_credits = _get_traffic_cost_credits(chargeable_bytes)

    return {
        "daily_limit": daily_limit,
        "effective_limit": effective_limit,
        "debt_before_today": debt_before_today,
        "recovered_before_today": recovered_before_today,
        "exceed_bytes": exceed_bytes,
        "chargeable_debt_excess": chargeable_bytes,
        "next_debt_bytes": next_debt_bytes,
        "chargeable_bytes": chargeable_bytes,
        "traffic_cost_credits": traffic_cost_credits,
        "next_debt_updated_date": settlement_date.strftime("%Y-%m-%d"),
    }
