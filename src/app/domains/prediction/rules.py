"""Pure prediction computations: pool settlement and per-user payouts.

No I/O, no session, no configuration reads: the repository supplies every input
and writes every result. The three payout branches, the possibly negative fees
and the rounding remainder are copied verbatim from the pre-promotion
``resolve_prediction_market`` so the outcomes stay byte-for-byte identical.
"""

from __future__ import annotations


def settle_market(
    *,
    real_yes_pool: int,
    real_no_pool: int,
    result_option: int,
    fee_burn_bp: int,
    fee_glory_bp: int,
    current_glory: float,
) -> dict:
    """按开奖结果计算手续费、奖池与荣耀奖池的变化。"""
    total_real_pool = int(real_yes_pool) + int(real_no_pool)
    fee_burned = int(total_real_pool * int(fee_burn_bp) / 10000)
    fee_to_glory = int(total_real_pool * int(fee_glory_bp) / 10000)
    total_fee = int(fee_burned + fee_to_glory)
    base_payout_pool = int(total_real_pool - total_fee)

    winner_pool = int(real_yes_pool) if int(result_option) == 1 else int(real_no_pool)
    loser_pool = int(total_real_pool - winner_pool)

    # 默认：按常规 95% 奖池分发
    payout_pool = int(base_payout_pool)
    glory_pool_extra_in = 0
    glory_pool_extra_out = 0

    # 情况1：没有胜方（开奖侧无人押中）
    # 95% 奖池不再分发，全部并入荣耀奖池。
    if int(winner_pool) <= 0 and int(base_payout_pool) > 0:
        glory_pool_extra_in = int(base_payout_pool)
        payout_pool = 0
    # 情况2：全部为胜方、没有败方
    # 从荣耀奖池提取手续费 1.5 倍用于补偿发放（余额不足则按余额发放）。
    elif int(winner_pool) > 0 and int(loser_pool) <= 0 and int(total_fee) > 0:
        target_compensation = int(float(total_fee) * 1.5)
        # 补偿以整数积分发放，故可用额向下取整；余额的小数部分留在池中
        available_glory = max(0, int(current_glory))
        glory_pool_extra_out = min(int(target_compensation), int(available_glory))
        payout_pool = int(base_payout_pool + glory_pool_extra_out)

    final_glory_balance = round(
        float(current_glory)
        + float(fee_to_glory)
        + float(glory_pool_extra_in)
        - float(glory_pool_extra_out),
        2,
    )

    return {
        "total_real_pool": int(total_real_pool),
        "fee_burned": int(fee_burned),
        "fee_to_glory": int(fee_to_glory),
        "total_fee": int(total_fee),
        "base_payout_pool": int(base_payout_pool),
        "winner_pool": int(winner_pool),
        "loser_pool": int(loser_pool),
        "payout_pool": int(payout_pool),
        "glory_pool_extra_in": int(glory_pool_extra_in),
        "glory_pool_extra_out": int(glory_pool_extra_out),
        "final_glory_balance": float(final_glory_balance),
    }


def payout_for(*, amount: int, winner_pool: int, payout_pool: int) -> float:
    """Single user's payout; zero when the side did not win or nothing is paid.

    与结算时的逐人派奖使用同一条公式（含两点小数舍入），供通知复用。
    """
    if winner_pool > 0 and payout_pool > 0 and int(amount) > 0:
        ratio = float(amount) / float(winner_pool)
        return round(float(payout_pool) * ratio, 2)
    return 0.0


__all__ = ["payout_for", "settle_market"]
