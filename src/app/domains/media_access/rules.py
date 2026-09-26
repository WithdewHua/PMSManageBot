from time import time


def caculate_credits_fund(unlock_time, unlock_credits: int):
    if not unlock_time:
        return 0
    cur_time = time()
    gap = cur_time - float(unlock_time)
    # 一天内，返还 90%
    if gap <= 3600 * 24:
        return unlock_credits * 0.9
    elif gap <= 3600 * 24 * 7:
        return unlock_credits * 0.7
    elif gap <= 3600 * 24 * 30:
        return unlock_credits * 0.5
    else:
        return 0
