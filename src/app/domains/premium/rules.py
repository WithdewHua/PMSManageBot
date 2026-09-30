import math
from datetime import datetime


def _get_premium_daily_limit(
    is_premium: bool,
    *,
    user_traffic_limit: int,
    premium_user_traffic_limit: int,
) -> int:
    return premium_user_traffic_limit if is_premium else user_traffic_limit


def _get_traffic_cost_credits(
    chargeable_bytes: int, *, credits_cost_per_10gb: int
) -> float:
    if chargeable_bytes <= 0:
        return 0

    gb_tiers = math.ceil(chargeable_bytes / (10 * 1024 * 1024 * 1024))
    return round(gb_tiers * credits_cost_per_10gb, 2)


def _parse_debt_date(date_str: str | None, *, tzinfo) -> datetime | None:
    if not date_str:
        return None

    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tzinfo)
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
        premium_status_updated_at, tz=settlement_date.tzinfo
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
    user_traffic_limit: int,
    premium_user_traffic_limit: int,
    credits_cost_per_10gb: int,
) -> dict:
    daily_limit = _get_premium_daily_limit(
        is_premium,
        user_traffic_limit=user_traffic_limit,
        premium_user_traffic_limit=premium_user_traffic_limit,
    )
    max_debt_bytes = daily_limit * 2
    previous_debt = max(int(debt_bytes or 0), 0)
    debt_date = _parse_debt_date(debt_updated_date, tzinfo=settlement_date.tzinfo)
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
    traffic_cost_credits = _get_traffic_cost_credits(
        chargeable_bytes, credits_cost_per_10gb=credits_cost_per_10gb
    )

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


def project_daily_debt(current_debt: float, usage: float, daily_limit: float) -> float:
    """Project today's outstanding bytes, capped at two daily allowances."""
    return min(max(current_debt + usage - daily_limit, 0), daily_limit * 2)
