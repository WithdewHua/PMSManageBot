"""大预言家 repository：截止与开奖结算。

派奖数学是纯函数（`rules.settle_market` / `rules.payout_for`）；本模块只负责
加锁、读写账本与荣耀奖池、以及把结果落库。
"""

import time

from sqlalchemy import func, select

from app.core import kv as core_kv
from app.core.db import get_session
from app.domains.credits import repository as credits_repository
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.identity import repository as identity_repository
from app.domains.prediction import exceptions as prediction_exceptions
from app.domains.prediction import rules as prediction_rules
from app.domains.prediction.models import PredictionBet, PredictionMarket

#: 荣耀奖池是**跨活动共用**的单一余额：除本活动的手续费外，21 点的抽水亦按比例
#: 注入其中（见 blackjack 的结算）。config_type 沿用 prediction_market 属历史命名，
#: 未迁移是为了不改动已上线的结算逻辑。余额以**小数字符串**存储：21 点的单手注入
#: 天然为小数，故读取端必须用 float 解析——用 int() 会在读到小数时抛错并把余额
#: 静默清零。既有的整数字符串余额亦可被 float() 正常读入。
GLORY_FUND_TYPE = "prediction_market"
GLORY_FUND_KEY = "glory_fund"


class _PredictionRepositorySettlement:
    def close_prediction_market_betting(self, market_id: int) -> dict:
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

            market.status = 2
            session.flush()
            return {"market_id": int(market.id), "status": int(market.status)}

    def resolve_prediction_market(
        self,
        market_id: int,
        result_option: int,
        resolved_by: int,
        resolution_note: str | None = None,
        *,
        _include_payouts: bool = False,
    ) -> dict:
        if int(result_option) not in [0, 1]:
            raise prediction_exceptions.invalid_result_option()

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
            if int(market.status) in [3, 4]:
                raise prediction_exceptions.market_already_settled()

            raw_glory = core_kv.get_tx(
                session, GLORY_FUND_TYPE, GLORY_FUND_KEY, for_update=True
            )
            try:
                current_glory = float(raw_glory or "0")
            except Exception:
                current_glory = 0.0

            settled = prediction_rules.settle_market(
                real_yes_pool=int(market.real_yes_pool),
                real_no_pool=int(market.real_no_pool),
                result_option=int(result_option),
                fee_burn_bp=int(market.fee_burn_bp),
                fee_glory_bp=int(market.fee_glory_bp),
                current_glory=current_glory,
            )

            total_real_pool = int(settled["total_real_pool"])
            payout_pool = int(settled["payout_pool"])
            winner_pool = int(settled["winner_pool"])

            payout_map: dict[int, float] = {}
            winner_count = 0
            if winner_pool > 0 and payout_pool > 0:
                winner_rows = session.execute(
                    select(
                        PredictionBet.tg_id,
                        func.coalesce(func.sum(PredictionBet.amount), 0),
                    )
                    .where(
                        PredictionBet.market_id == int(market.id),
                        PredictionBet.option == int(result_option),
                    )
                    .group_by(PredictionBet.tg_id)
                ).all()

                winner_count = len(winner_rows)
                for tg_id, user_amt in winner_rows:
                    payout_map[int(tg_id)] = prediction_rules.payout_for(
                        amount=int(user_amt),
                        winner_pool=winner_pool,
                        payout_pool=payout_pool,
                    )

                # 统计行按 tg_id 升序逐个加锁（与 credits 转账的锁顺序一致），
                # 缺失的行在调用方事务里就地建档，避免并发结算互相死锁。
                for uid in sorted(payout_map):
                    identity_repository.ensure_statistics_tx(session, uid)
                    mutation = credits_repository.add_tx(
                        session, CreditAccount.tg(uid), float(payout_map[uid])
                    )
                    credits_service.register_cache_invalidation(session, mutation)

            market.status = 3
            market.result_option = int(result_option)
            market.resolution_note = resolution_note
            market.total_fee_collected = int(total_real_pool - payout_pool)
            market.fee_burned = int(settled["fee_burned"])
            market.fee_to_glory = int(settled["fee_to_glory"])
            market.resolved_by = int(resolved_by)
            market.resolved_at = int(now_ts)

            core_kv.upsert_tx(
                session,
                GLORY_FUND_TYPE,
                GLORY_FUND_KEY,
                str(settled["final_glory_balance"]),
            )

            session.flush()

            result: dict[str, object] = {
                "market_id": int(market.id),
                "status": int(market.status),
                "result_option": int(result_option),
                "total_real_pool": int(total_real_pool),
                "total_fee": int(settled["total_fee"]),
                "fee_burned": int(settled["fee_burned"]),
                "fee_to_glory": int(settled["fee_to_glory"]),
                "winner_count": int(winner_count),
                "payout_pool": int(payout_pool),
            }
            if _include_payouts:
                result["payouts"] = dict(payout_map)
            return result


def reward_prediction_submission(submitter_tg_id: int) -> int:
    """审核通过后的 1 积分奖励；调用方在提交审核后尽力执行。"""
    from app.domains.credits import repository as credits_repository
    from app.domains.credits import service as credits_service
    from app.domains.credits.types import CreditAccount
    from app.domains.identity import repository as identity_repository

    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, int(submitter_tg_id))
        mutation = credits_repository.add_tx(
            session, CreditAccount.tg(int(submitter_tg_id)), 1
        )
        credits_service.register_cache_invalidation(session, mutation)
        return 1
