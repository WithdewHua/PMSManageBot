"""Pure calculations for daily watch rewards."""

from __future__ import annotations


def watch_daily_award(
    base_credits: float, play_duration: float, traffic_usage_total: float
) -> tuple[float, float, float]:
    time_penalty = (play_duration - 8 * 1.2) * 0.5 if play_duration > 8 * 1.2 else 0.0
    expected_data = play_duration * 10 * 1024**3
    data_penalty = 0.0
    if traffic_usage_total > 0 and expected_data > 0:
        ratio = float(traffic_usage_total) / float(expected_data)
        if ratio > 1.2:
            data_penalty = float(base_credits) * (ratio - 1.2) * 0.5
    award = max(0.0, min(float(base_credits) - time_penalty - data_penalty, 8.0))
    return award, time_penalty, data_penalty


def inviter_bonus(
    daily_award: float, inviter_tg_id: int | None, tg_id: int | None
) -> float:
    if inviter_tg_id and inviter_tg_id != tg_id and daily_award > 0:
        return round(daily_award * 0.1, 2)
    return 0.0


__all__ = ["inviter_bonus", "watch_daily_award"]
