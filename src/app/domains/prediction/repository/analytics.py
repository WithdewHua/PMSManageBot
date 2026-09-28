"""大预言家 repository：个人统计与排行（由 part_N 机械拆分）。"""

from datetime import UTC, datetime

from sqlalchemy import case, func, select

from app.core.db import get_session
from app.core.log import logger
from app.domains.prediction.models import PredictionBet, PredictionMarket


class _PredictionRepositoryAnalytics:
    def _get_prediction_settled_market_meta(
        self, session
    ) -> tuple[dict[int, dict], dict[int, int]]:
        """获取已结算预测市场的元信息与中奖侧总池。"""
        market_rows = session.execute(
            select(
                PredictionMarket.id,
                PredictionMarket.title,
                PredictionMarket.result_option,
                PredictionMarket.status,
                PredictionMarket.real_yes_pool,
                PredictionMarket.real_no_pool,
                PredictionMarket.total_fee_collected,
                PredictionMarket.resolved_at,
            ).where(
                PredictionMarket.status == 3,
                PredictionMarket.result_option.isnot(None),
            )
        ).all()

        market_map: dict[int, dict] = {}
        for row in market_rows:
            market_id = int(row[0])
            total_real_pool = int(row[4] or 0) + int(row[5] or 0)
            total_fee = int(row[6] or 0)
            payout_pool = max(0.0, float(total_real_pool - total_fee))
            market_map[market_id] = {
                "market_id": market_id,
                "title": str(row[1] or ""),
                "result_option": int(row[2]),
                "payout_pool": payout_pool,
                "resolved_at": int(row[7]) if row[7] is not None else None,
            }

        winner_pool_rows = session.execute(
            select(
                PredictionBet.market_id,
                func.coalesce(func.sum(PredictionBet.amount), 0),
            )
            .join(
                PredictionMarket,
                PredictionBet.market_id == PredictionMarket.id,
            )
            .where(
                PredictionMarket.status == 3,
                PredictionMarket.result_option.isnot(None),
                PredictionBet.option == PredictionMarket.result_option,
            )
            .group_by(PredictionBet.market_id)
        ).all()
        winner_pool_map = {int(r[0]): int(r[1] or 0) for r in winner_pool_rows}

        return market_map, winner_pool_map

    def get_prediction_user_stats(self, tg_id: int) -> dict:
        """获取用户大预言家个人统计（已结算净盈亏/胜率/最近结算记录）。"""
        try:
            with get_session() as session:
                market_map, winner_pool_map = self._get_prediction_settled_market_meta(
                    session
                )

                settled_positions = session.execute(
                    select(
                        PredictionBet.market_id,
                        func.coalesce(
                            func.sum(
                                case(
                                    (PredictionBet.option == 1, PredictionBet.amount),
                                    else_=0,
                                )
                            ),
                            0,
                        ).label("yes_amount"),
                        func.coalesce(
                            func.sum(
                                case(
                                    (PredictionBet.option == 0, PredictionBet.amount),
                                    else_=0,
                                )
                            ),
                            0,
                        ).label("no_amount"),
                    )
                    .join(
                        PredictionMarket, PredictionBet.market_id == PredictionMarket.id
                    )
                    .where(
                        PredictionBet.tg_id == int(tg_id),
                        PredictionMarket.status == 3,
                        PredictionMarket.result_option.isnot(None),
                    )
                    .group_by(PredictionBet.market_id)
                    .order_by(PredictionBet.market_id.desc())
                ).all()

                total_bet_amount = 0.0
                total_payout_amount = 0.0
                settled_markets = 0
                win_markets = 0
                recent_settlements = []

                for market_id_raw, yes_amount_raw, no_amount_raw in settled_positions:
                    market_id = int(market_id_raw)
                    market_meta = market_map.get(market_id)
                    if not market_meta:
                        continue

                    yes_amount = int(yes_amount_raw or 0)
                    no_amount = int(no_amount_raw or 0)
                    bet_amount = float(yes_amount + no_amount)
                    result_option = int(market_meta["result_option"])
                    win_amount = yes_amount if result_option == 1 else no_amount
                    winner_pool = int(winner_pool_map.get(market_id, 0))
                    payout_pool = float(market_meta["payout_pool"])

                    payout_amount = 0.0
                    if winner_pool > 0 and payout_pool > 0 and win_amount > 0:
                        payout_amount = round(
                            (payout_pool * float(win_amount)) / float(winner_pool), 2
                        )

                    net_profit = round(payout_amount - bet_amount, 2)

                    settled_markets += 1
                    total_bet_amount += bet_amount
                    total_payout_amount += payout_amount
                    if win_amount > 0 and payout_amount > 0:
                        win_markets += 1

                    if len(recent_settlements) < 10:
                        recent_settlements.append(
                            {
                                "market_id": market_id,
                                "title": market_meta["title"],
                                "result_option": result_option,
                                "yes_amount": yes_amount,
                                "no_amount": no_amount,
                                "bet_amount": round(bet_amount, 2),
                                "payout_amount": round(payout_amount, 2),
                                "net_profit": net_profit,
                                "is_win": win_amount > 0 and payout_amount > 0,
                                "resolved_at": market_meta["resolved_at"],
                            }
                        )

                unsettled = session.execute(
                    select(
                        func.count(func.distinct(PredictionBet.market_id)),
                        func.coalesce(func.sum(PredictionBet.amount), 0),
                    )
                    .join(
                        PredictionMarket, PredictionBet.market_id == PredictionMarket.id
                    )
                    .where(
                        PredictionBet.tg_id == int(tg_id),
                        PredictionMarket.status.in_([1, 2]),
                    )
                ).one()
                unsettled_markets = int(unsettled[0] or 0)
                unsettled_bet_amount = round(float(unsettled[1] or 0), 2)

                net_profit_total = round(total_payout_amount - total_bet_amount, 2)
                win_rate = (
                    round((float(win_markets) / float(settled_markets)) * 100, 2)
                    if settled_markets > 0
                    else 0.0
                )

                return {
                    "settled_markets": int(settled_markets),
                    "win_markets": int(win_markets),
                    "win_rate": float(win_rate),
                    "total_bet_amount": round(float(total_bet_amount), 2),
                    "total_payout_amount": round(float(total_payout_amount), 2),
                    "net_profit": float(net_profit_total),
                    "unsettled_markets": int(unsettled_markets),
                    "unsettled_bet_amount": float(unsettled_bet_amount),
                    "recent_settlements": recent_settlements,
                }
        except Exception as e:
            logger.error(f"Error getting prediction user stats: {e}")
            return {
                "settled_markets": 0,
                "win_markets": 0,
                "win_rate": 0.0,
                "total_bet_amount": 0.0,
                "total_payout_amount": 0.0,
                "net_profit": 0.0,
                "unsettled_markets": 0,
                "unsettled_bet_amount": 0.0,
                "recent_settlements": [],
            }

    def _get_prediction_user_rank_stats(self) -> list[dict]:
        """聚合所有用户在已结算预测题目的统计。"""
        with get_session() as session:
            market_map, winner_pool_map = self._get_prediction_settled_market_meta(
                session
            )
            if not market_map:
                return []

            positions = session.execute(
                select(
                    PredictionBet.tg_id,
                    PredictionBet.market_id,
                    func.coalesce(
                        func.sum(
                            case(
                                (PredictionBet.option == 1, PredictionBet.amount),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("yes_amount"),
                    func.coalesce(
                        func.sum(
                            case(
                                (PredictionBet.option == 0, PredictionBet.amount),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("no_amount"),
                )
                .join(PredictionMarket, PredictionBet.market_id == PredictionMarket.id)
                .where(
                    PredictionMarket.status == 3,
                    PredictionMarket.result_option.isnot(None),
                )
                .group_by(PredictionBet.tg_id, PredictionBet.market_id)
            ).all()

            stats_map: dict[int, dict] = {}
            for tg_id_raw, market_id_raw, yes_amount_raw, no_amount_raw in positions:
                tg_id = int(tg_id_raw)
                market_id = int(market_id_raw)
                market_meta = market_map.get(market_id)
                if not market_meta:
                    continue

                yes_amount = int(yes_amount_raw or 0)
                no_amount = int(no_amount_raw or 0)
                bet_amount = float(yes_amount + no_amount)
                result_option = int(market_meta["result_option"])
                win_amount = yes_amount if result_option == 1 else no_amount
                winner_pool = int(winner_pool_map.get(market_id, 0))
                payout_pool = float(market_meta["payout_pool"])

                payout_amount = 0.0
                if winner_pool > 0 and payout_pool > 0 and win_amount > 0:
                    payout_amount = round(
                        (payout_pool * float(win_amount)) / float(winner_pool), 2
                    )

                item = stats_map.setdefault(
                    tg_id,
                    {
                        "tg_id": tg_id,
                        "settled_markets": 0,
                        "win_markets": 0,
                        "total_bet_amount": 0.0,
                        "total_payout_amount": 0.0,
                        "net_profit": 0.0,
                        "win_rate": 0.0,
                    },
                )

                item["settled_markets"] += 1
                item["total_bet_amount"] = round(
                    item["total_bet_amount"] + bet_amount, 2
                )
                item["total_payout_amount"] = round(
                    item["total_payout_amount"] + payout_amount, 2
                )
                if win_amount > 0 and payout_amount > 0:
                    item["win_markets"] += 1

            for data in stats_map.values():
                data["net_profit"] = round(
                    float(data["total_payout_amount"])
                    - float(data["total_bet_amount"]),
                    2,
                )
                settled_markets = int(data["settled_markets"])
                win_markets = int(data["win_markets"])
                data["win_rate"] = (
                    round((float(win_markets) / float(settled_markets)) * 100, 2)
                    if settled_markets > 0
                    else 0.0
                )

            return list(stats_map.values())

    def get_prediction_net_profit_rank(self) -> list[dict]:
        """获取大预言家净盈亏排行榜。"""
        try:
            stats = self._get_prediction_user_rank_stats()
            stats.sort(
                key=lambda x: (
                    float(x.get("net_profit", 0)),
                    int(x.get("settled_markets", 0)),
                ),
                reverse=True,
            )
            return stats
        except Exception as e:
            logger.error(f"Error getting prediction net profit rank: {e}")
            return []

    def get_prediction_win_rate_rank(self) -> list[dict]:
        """获取大预言家胜率排行榜。"""
        try:
            stats = self._get_prediction_user_rank_stats()
            stats = [item for item in stats if int(item.get("settled_markets", 0)) > 0]
            stats.sort(
                key=lambda x: (
                    float(x.get("win_rate", 0)),
                    int(x.get("settled_markets", 0)),
                    float(x.get("net_profit", 0)),
                ),
                reverse=True,
            )
            return stats
        except Exception as e:
            logger.error(f"Error getting prediction win rate rank: {e}")
            return []


def count_bets_tx(session, tg_id: int, since: int, until: int) -> int:
    """指定时间窗内的大预言家下注次数（闭区间，秒级时间戳转 UTC datetime）。"""
    return int(
        session.execute(
            select(func.count(PredictionBet.id)).where(
                PredictionBet.tg_id == int(tg_id),
                PredictionBet.created_at >= datetime.fromtimestamp(int(since), UTC),
                PredictionBet.created_at <= datetime.fromtimestamp(int(until), UTC),
            )
        ).scalar_one()
    )
