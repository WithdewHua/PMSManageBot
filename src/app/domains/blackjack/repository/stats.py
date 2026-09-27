"""21 点 repository：统计（由 part_N 机械拆分）。"""

from sqlalchemy import case, distinct, func, select

from app.core.db import get_session
from app.core.log import logger
from app.domains.blackjack.config import JACKPOT_CONFIG_KEY, JACKPOT_CONFIG_TYPE
from app.domains.blackjack.models import BlackjackHand


class _BlackjackRepositoryStats:
    def get_user_blackjack_stats(self, tg_id: int) -> dict:
        """用户的 21 点个人统计。"""
        empty = {
            "total_hands": 0,
            "net_credits": 0.0,
            "max_win": 0.0,
            "win_rate": 0.0,
            "accuracy": 0.0,
            "decisions_total": 0,
            "jackpot_total": 0.0,
            "surrender_hands": 0,
        }
        try:
            with get_session() as session:
                return self.get_user_blackjack_stats_tx(session, tg_id)
        except Exception as e:
            logger.error(f"获取用户 21 点统计失败 (tg_id={tg_id}): {e}")
            return empty

    def get_blackjack_admin_stats(self) -> dict:
        """21 点的运营聚合统计，供管理页卡片展示。"""
        empty = {
            "total_hands": 0,
            "active_hands": 0,
            "total_players": 0,
            "today_hands": 0,
            "total_wagered": 0.0,
            "total_rake": 0.0,
            "net_credits": 0.0,
            "jackpot_paid": 0.0,
            "jackpot_balance": 0.0,
        }
        try:
            with get_session() as session:
                return self.get_blackjack_admin_stats_tx(session)
        except Exception as e:
            logger.error(f"获取 21 点运营统计失败: {e}")
            return empty

    def get_user_blackjack_stats_tx(self, session, tg_id: int) -> dict:
        """Read user statistics using the caller-owned session."""
        from app.domains.blackjack import rules as engine

        total_stake = case(
            (BlackjackHand.doubled == 1, BlackjackHand.bet_credits * 2),
            else_=BlackjackHand.bet_credits,
        )
        net = (
            func.coalesce(BlackjackHand.payout_credits, 0)
            - total_stake
            + func.coalesce(BlackjackHand.relief_credits, 0)
        )
        win_flag = case(
            (
                BlackjackHand.outcome.in_(
                    [engine.OUTCOME_WIN, engine.OUTCOME_BLACKJACK]
                ),
                1,
            ),
            else_=0,
        )
        surrender_flag = case(
            (BlackjackHand.outcome == engine.OUTCOME_SURRENDER, 1), else_=0
        )
        row = session.execute(
            select(
                func.count(BlackjackHand.id),
                func.coalesce(func.sum(net), 0),
                func.coalesce(func.max(net), 0),
                func.coalesce(func.sum(win_flag), 0),
                func.coalesce(func.sum(BlackjackHand.decisions_total), 0),
                func.coalesce(func.sum(BlackjackHand.decisions_correct), 0),
                func.coalesce(func.sum(BlackjackHand.jackpot_won), 0),
                func.coalesce(func.sum(surrender_flag), 0),
            ).where(
                BlackjackHand.tg_id == int(tg_id),
                BlackjackHand.status.in_(engine.TERMINAL_STATUSES),
                BlackjackHand.tournament_id.is_(None),
            )
        ).one()
        hands = int(row[0] or 0)
        decisions_total = int(row[4] or 0)
        return {
            "total_hands": hands,
            "net_credits": round(float(row[1] or 0), 2),
            "max_win": round(float(row[2] or 0), 2),
            "win_rate": round(float(row[3] or 0) / hands * 100, 2) if hands else 0.0,
            "accuracy": round(float(row[5] or 0) / decisions_total * 100, 2)
            if decisions_total
            else 0.0,
            "decisions_total": decisions_total,
            "jackpot_total": round(float(row[6] or 0), 2),
            "surrender_hands": int(row[7] or 0),
        }

    def get_blackjack_admin_stats_tx(self, session) -> dict:
        """Read aggregate statistics using the caller-owned session."""
        from app.domains.blackjack import rules as engine

        terminal = BlackjackHand.status.in_(engine.TERMINAL_STATUSES)
        stake = case(
            (BlackjackHand.doubled == 1, BlackjackHand.bet_credits * 2),
            else_=BlackjackHand.bet_credits,
        )
        staked = case((terminal, stake), else_=0)
        paid = case((terminal, func.coalesce(BlackjackHand.payout_credits, 0)), else_=0)
        raked = case((terminal, func.coalesce(BlackjackHand.rake_credits, 0)), else_=0)
        jackpot = case((terminal, func.coalesce(BlackjackHand.jackpot_won, 0)), else_=0)
        relief = case(
            (terminal, func.coalesce(BlackjackHand.relief_credits, 0)), else_=0
        )
        row = session.execute(
            select(
                func.coalesce(func.sum(case((terminal, 1), else_=0)), 0),
                func.coalesce(func.sum(case((terminal, 0), else_=1)), 0),
                func.count(distinct(BlackjackHand.tg_id)),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                BlackjackHand.created_at_ms
                                >= self._blackjack_day_start_ms(),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(func.sum(staked), 0),
                func.coalesce(func.sum(raked), 0),
                func.coalesce(func.sum(paid), 0),
                func.coalesce(func.sum(jackpot), 0),
                func.coalesce(func.sum(relief), 0),
            ).where(BlackjackHand.tournament_id.is_(None))
        ).one()
        wagered = float(row[4] or 0)
        payout = float(row[6] or 0)
        jackpot_paid = float(row[7] or 0)
        relief_paid = float(row[8] or 0)
        return {
            "total_hands": int(row[0] or 0),
            "active_hands": int(row[1] or 0),
            "total_players": int(row[2] or 0),
            "today_hands": int(row[3] or 0),
            "total_wagered": round(wagered, 2),
            "total_rake": round(float(row[5] or 0), 2),
            "net_credits": round(payout + jackpot_paid + relief_paid - wagered, 2),
            "jackpot_paid": round(jackpot_paid, 2),
            "jackpot_balance": self.read_fund_balance(
                session, JACKPOT_CONFIG_TYPE, JACKPOT_CONFIG_KEY
            ),
        }
