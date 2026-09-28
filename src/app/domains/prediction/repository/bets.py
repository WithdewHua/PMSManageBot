"""大预言家 repository：下注、个人持仓与下注记录（由 part_N 机械拆分）。"""

import time

from sqlalchemy import func, select

from app.core.db import get_session
from app.domains.credits import repository as credits_repository
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import Statistics
from app.domains.prediction import exceptions as prediction_exceptions
from app.domains.prediction.models import PredictionBet, PredictionMarket


class _PredictionRepositoryBets:
    def place_prediction_bet(
        self,
        market_id: int,
        tg_id: int,
        option: int,
        amount: int,
    ) -> dict:
        if int(option) not in [0, 1]:
            raise prediction_exceptions.invalid_option()
        if int(amount) <= 0:
            raise prediction_exceptions.amount_must_be_positive()

        now_ts = int(time.time())
        with get_session() as session:
            market = (
                session.execute(
                    select(PredictionMarket)
                    .where(PredictionMarket.id == int(market_id))
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not market:
                raise prediction_exceptions.market_not_found()
            if int(market.status) != 1:
                raise prediction_exceptions.market_not_open()
            if market.betting_deadline and int(now_ts) >= int(market.betting_deadline):
                raise prediction_exceptions.betting_closed()

            user_total = session.execute(
                select(func.coalesce(func.sum(PredictionBet.amount), 0)).where(
                    PredictionBet.market_id == int(market.id),
                    PredictionBet.tg_id == int(tg_id),
                )
            ).scalar_one()
            if int(user_total or 0) + int(amount) > int(market.max_bet_per_user):
                raise prediction_exceptions.max_bet_exceeded()

            stats = (
                session.execute(
                    select(Statistics)
                    .where(Statistics.tg_id == int(tg_id))
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not stats:
                raise prediction_exceptions.user_stats_not_found()
            if float(stats.credits) < float(amount):
                raise prediction_exceptions.insufficient_credits()

            credits_repository.deduct_tx(
                session, CreditAccount.tg(int(tg_id)), float(amount)
            )

            bet = PredictionBet(
                market_id=int(market.id),
                tg_id=int(tg_id),
                option=int(option),
                amount=int(amount),
            )
            session.add(bet)

            if int(option) == 1:
                market.real_yes_pool = int(market.real_yes_pool) + int(amount)
            else:
                market.real_no_pool = int(market.real_no_pool) + int(amount)

            session.flush()

            yes_odds, no_odds = self._calc_prediction_odds(
                int(market.real_yes_pool),
                int(market.real_no_pool),
                int(market.virtual_yes_pool),
                int(market.virtual_no_pool),
            )

            return {
                "bet": {
                    "id": int(bet.id),
                    "market_id": int(market.id),
                    "tg_id": int(tg_id),
                    "option": int(option),
                    "amount": int(amount),
                },
                "market": {
                    "id": int(market.id),
                    "title": market.title,
                    "description": market.description,
                    "status": int(market.status),
                    "result_option": int(market.result_option)
                    if market.result_option is not None
                    else None,
                    "betting_deadline": int(market.betting_deadline)
                    if market.betting_deadline is not None
                    else None,
                    "real_yes_pool": int(market.real_yes_pool),
                    "real_no_pool": int(market.real_no_pool),
                    "virtual_yes_pool": int(market.virtual_yes_pool),
                    "virtual_no_pool": int(market.virtual_no_pool),
                    "yes_odds": yes_odds,
                    "no_odds": no_odds,
                    "max_bet_per_user": int(market.max_bet_per_user),
                    "fee_rate_bp": int(market.fee_rate_bp),
                    "fee_burn_bp": int(market.fee_burn_bp),
                    "fee_glory_bp": int(market.fee_glory_bp),
                    "resolution_note": market.resolution_note,
                    "total_fee_collected": int(market.total_fee_collected),
                    "fee_burned": int(market.fee_burned),
                    "fee_to_glory": int(market.fee_to_glory),
                    "my_yes_amount": int(user_total or 0) + int(amount)
                    if int(option) == 1
                    else 0,
                    "my_no_amount": int(user_total or 0) + int(amount)
                    if int(option) == 0
                    else 0,
                    "created_at": market.created_at,
                },
                "user_credits": round(float(stats.credits), 2),
            }

    def list_prediction_bets(self, market_id: int, limit: int = 100) -> list[dict]:
        from app.core.telegram import get_user_name_from_tg_id

        with get_session() as session:
            rows = (
                session.execute(
                    select(PredictionBet)
                    .where(PredictionBet.market_id == int(market_id))
                    .order_by(PredictionBet.id.desc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [
                {
                    "id": int(r.id),
                    "market_id": int(r.market_id),
                    "tg_id": int(r.tg_id),
                    "tg_username": str(
                        get_user_name_from_tg_id(int(r.tg_id)) or r.tg_id
                    ),
                    "option": int(r.option),
                    "amount": int(r.amount),
                    "created_at": r.created_at,
                }
                for r in rows
            ]

    def list_prediction_user_positions(self, market_id: int) -> list[dict]:
        """按用户聚合某个预测题目的 YES/NO 持仓。"""
        with get_session() as session:
            rows = session.execute(
                select(
                    PredictionBet.tg_id,
                    PredictionBet.option,
                    func.coalesce(func.sum(PredictionBet.amount), 0),
                )
                .where(PredictionBet.market_id == int(market_id))
                .group_by(PredictionBet.tg_id, PredictionBet.option)
            ).all()

            user_positions: dict[int, dict] = {}
            for tg_id, option, amount in rows:
                uid = int(tg_id)
                if uid not in user_positions:
                    user_positions[uid] = {
                        "tg_id": uid,
                        "yes_amount": 0,
                        "no_amount": 0,
                    }
                if int(option) == 1:
                    user_positions[uid]["yes_amount"] = int(amount or 0)
                else:
                    user_positions[uid]["no_amount"] = int(amount or 0)

            return list(user_positions.values())
