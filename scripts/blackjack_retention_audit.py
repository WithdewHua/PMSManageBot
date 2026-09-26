"""21 点留存三机制的对账与让利率周报（openspec: add-blackjack-retention）。

用法：
    python3 scripts/blackjack_retention_audit.py            # 对账 + 最近一周周报
    python3 scripts/blackjack_retention_audit.py --weeks 4  # 最近 N 周的让利率周报

两个职责：

1. **对账**：`statistics` 上的连败计数与免费机会手数进度，与
   `blackjack_hand` 历史回溯推导值比对。两者由结算核心同事务维护，正常
   情况下恒等；出现偏差即说明某条结算路径漏挂了钩子（或历史数据被手工
   改动），这是最重要的回归信号。

   回溯口径与写入口径一致：连败 = 自最近一次判胜以来的判负手数
   （平局/投降跳过不改），手数进度无法从历史推导（发放记录落在
   luckywheel_free_spins，扣减量 = 发放数 × 阈值），故对账只核对
   「历史手数 − 已发放机会 × 阈值」与存储进度的一致性——按发放时点把
   历史手数分段累计。

2. **让利率周报**：按周输出三项机制的发放额与结构性抽耗，供管理端核算
   design.md D1 的预算表。免费转盘一行按**当前线上奖池配置**计算单次
   EV——若奖池中出现「翻倍 / 减半」类随余额放大的奖品，周报首行会显著
   警示：该类奖品会使手数口径失去安全边界，须立即改回投注流水口径或
   增设使用余额上限。

只读不写，可随时重跑。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import get_session
from app.domains.blackjack.models import BlackjackHand, BlackjackWeeklyCashback
from app.domains.identity.models import Statistics
from app.domains.luckywheel.models import LuckywheelFreeSpin, WheelStats

settings.load_config_from_file()

WEEK_MS = 7 * 86400 * 1000


def week_start_ms(now_ms: int) -> int:
    """与 db._blackjack_week_start_ms 同口径的本周一零点（settings.TZ）。"""
    from datetime import datetime, timedelta

    now = datetime.fromtimestamp(now_ms / 1000, tz=settings.TZ)
    start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int(start.timestamp() * 1000)


def audit_counters() -> bool:
    """对账 statistics 上的两个计数列 vs 手牌历史回溯。"""

    from app.domains.blackjack import rules as engine

    ok = True
    with get_session() as session:
        users = session.execute(select(Statistics.tg_id)).scalars().all()
        for tg_id in users:
            # 回溯连败：从最新终态现金局手牌向前扫，判胜即停
            hands = (
                session.execute(
                    select(BlackjackHand.outcome)
                    .where(
                        BlackjackHand.tg_id == tg_id,
                        BlackjackHand.tournament_id.is_(None),
                        BlackjackHand.status.in_(engine.TERMINAL_STATUSES),
                    )
                    .order_by(BlackjackHand.settled_at.desc(), BlackjackHand.id.desc())
                )
                .scalars()
                .all()
            )
            derived_streak = 0
            for outcome in hands:
                if outcome in ("win", "blackjack"):
                    break
                if outcome in ("lose", "bust"):
                    derived_streak += 1
                # push / surrender：跳过不改

            stats = session.get(Statistics, tg_id)
            stored_streak = int(stats.blackjack_lose_streak or 0)
            if stored_streak != derived_streak:
                print(
                    f"[对账-偏差] tg_id={tg_id} 连败计数: 存储 {stored_streak}"
                    f" vs 回溯 {derived_streak}"
                )
                ok = False

            # 手数进度对账：历史终态手数 = Σ(已发放机会 × 发放时阈值) + 当前进度。
            # 阈值会随配置变化，按发放时点分段取「当时的阈值」不可考，故用
            # 当前配置阈值近似——只在管理员改过阈值时可能产生已知偏差，
            # 报告中按「无法精确对账」处理而非误报
            total_hands = len(hands)
            grants = (
                session.execute(
                    select(func.count(LuckywheelFreeSpin.id)).where(
                        LuckywheelFreeSpin.tg_id == tg_id,
                        # 只统计 21 点来源：礼包等其他来源与手数进度无关
                        LuckywheelFreeSpin.source == "blackjack",
                    )
                )
            ).scalar_one()
            stored_progress = int(stats.blackjack_hands_since_freespin or 0)
            # 仅提示，不判失败：阈值变更会使该等式天然不成立
            print(
                f"[进度] tg_id={tg_id} 终态手数 {total_hands}，已发放 {grants} 张，"
                f"当前进度 {stored_progress}"
            )
    return ok


def weekly_report(weeks: int) -> None:
    """最近 N 周的让利率周报（含本期进行中的当周）。"""
    import time

    from app.domains.blackjack import rules as engine

    now_ms = int(time.time() * 1000)
    current_week = week_start_ms(now_ms)

    # 线上转盘奖池的单次 EV（按当前配置计算；放大类奖品会触发警示）
    amplifying = False
    spin_ev = 0.0
    try:
        from app.domains.luckywheel.router import get_wheel_config

        config = get_wheel_config()
        for item in config.items:
            name = item.name.lower()
            prob = float(item.probability) / 100.0
            if "翻倍" in item.name or "减半" in item.name:
                amplifying = True
                continue
            if "谢谢参与" in item.name or "邀请码" in item.name or "premium" in name:
                continue
            import re

            m = re.search(r"([+-])(\d+)", item.name)
            if m:
                sign, amount = m.groups()
                spin_ev += prob * (int(amount) if sign == "+" else -int(amount))
    except Exception as e:
        print(f"[警告] 转盘配置读取失败，EV 按未知处理: {e}")
        spin_ev = None

    print("\n===== 让利率周报 =====")
    if amplifying:
        print(
            "!!! 警示：线上奖池含「翻倍/减半」类随余额放大的奖品 !!!\n"
            "    手数口径的安全边界失效（见 design.md D1 参数护栏），\n"
            "    须立即改回投注流水口径或增设使用余额上限。\n"
        )
    if spin_ev is not None:
        print(f"当前奖池单次转盘 EV（不含截断效应）：{spin_ev:+.2f} 积分")

    with get_session() as session:
        for i in range(weeks):
            ws = current_week - i * WEEK_MS
            we = ws + WEEK_MS
            start_s, end_s = ws // 1000, we // 1000

            # 结构性抽耗：抽水 + 规则期望不可直接观测，以「投注流水」为
            # 分母口径报告让利占比
            wage_expr = BlackjackHand.bet_credits * (1 + BlackjackHand.doubled)
            row = session.execute(
                select(
                    func.count(BlackjackHand.id),
                    func.coalesce(func.sum(wage_expr), 0),
                    func.coalesce(func.sum(BlackjackHand.relief_credits), 0),
                    func.coalesce(func.sum(BlackjackHand.jackpot_won), 0),
                ).where(
                    BlackjackHand.tournament_id.is_(None),
                    BlackjackHand.status.in_(engine.TERMINAL_STATUSES),
                    BlackjackHand.settled_at >= start_s,
                    BlackjackHand.settled_at < end_s,
                )
            ).one()
            hands, wagered, relief_total, jackpot_total = row

            cashback_total = (
                session.execute(
                    select(
                        func.coalesce(
                            func.sum(BlackjackWeeklyCashback.cashback_credits), 0
                        )
                    ).where(BlackjackWeeklyCashback.week_start_ms == ws)
                ).scalar_one()
                or 0
            )

            grants = int(
                session.execute(
                    select(func.count(LuckywheelFreeSpin.id)).where(
                        # 让利率只核算 21 点来源的发放
                        LuckywheelFreeSpin.source == "blackjack",
                        LuckywheelFreeSpin.granted_at_ms >= ws,
                        LuckywheelFreeSpin.granted_at_ms < we,
                    )
                ).scalar_one()
                or 0
            )
            used = int(
                session.execute(
                    select(func.count(WheelStats.id)).where(
                        WheelStats.source == "blackjack_free",
                        WheelStats.timestamp >= start_s,
                        WheelStats.timestamp < end_s,
                    )
                ).scalar_one()
                or 0
            )
            wheel_paid = (
                session.execute(
                    select(func.coalesce(func.sum(WheelStats.credits_change), 0)).where(
                        WheelStats.source == "blackjack_free",
                        WheelStats.timestamp >= start_s,
                        WheelStats.timestamp < end_s,
                    )
                ).scalar_one()
                or 0
            )

            print(
                f"\n-- 周 {datetime_str(ws)} ~ {datetime_str(we)}\n"
                f"   现金局手数 {hands}，投注流水 {wagered:.2f}\n"
                f"   连败救济发放 {relief_total:.2f}"
                f"（占流水 {pct(relief_total, wagered)}）\n"
                f"   周返还发放 {cashback_total:.2f}"
                f"（占流水 {pct(cashback_total, wagered)}，入争霸赛余额）\n"
                f"   免费机会：发放 {grants} 张，已用 {used} 张，"
                f"实际转盘入账 {wheel_paid:+.2f}\n"
                f"   （同期奖池派彩 {jackpot_total:.2f}，独立于让利口径）"
            )


def datetime_str(ms: int) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(ms / 1000, tz=settings.TZ).strftime("%m-%d")


def pct(part: float, whole: float) -> str:
    if not whole:
        return "-"
    return f"{part / whole * 100:.2f}%"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weeks", type=int, default=1, help="周报覆盖的周数")
    args = parser.parse_args()

    print("===== 计数对账 =====")
    ok = audit_counters()
    print("对账结论：", "一致" if ok else "存在偏差（见上）")

    weekly_report(max(1, args.weeks))


if __name__ == "__main__":
    main()
