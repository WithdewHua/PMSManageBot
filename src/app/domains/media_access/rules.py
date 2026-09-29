from time import time


def caculate_credits_fund(
    unlock_time, unlock_credits: int, *, now: float | None = None
) -> float:
    """Calculate the legacy NSFW refund using an explicit clock when supplied."""
    if not unlock_time:
        return 0.0
    cur_time = time() if now is None else float(now)
    gap = cur_time - float(unlock_time)
    # 一天内，返还 90%
    if gap <= 3600 * 24:
        return unlock_credits * 0.9
    if gap <= 3600 * 24 * 7:
        return unlock_credits * 0.7
    if gap <= 3600 * 24 * 30:
        return unlock_credits * 0.5
    return 0.0
