"""大预言家 repository：截止与开奖结算（由 part_N 机械拆分）。"""

import time

from sqlalchemy import func, select

from app.core.db import get_session
from app.core.kv import SystemConfig
from app.domains.credits import repository as credits_repository
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import Statistics
from app.domains.prediction.models import PredictionBet, PredictionMarket


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
                raise ValueError("market not found")
            if int(market.status) != 1:
                raise ValueError("market not open")

            market.status = 2
            session.flush()
            return {"market_id": int(market.id), "status": int(market.status)}

    def resolve_prediction_market(
        self,
        market_id: int,
        result_option: int,
        resolved_by: int,
        resolution_note: str | None = None,
    ) -> dict:
        if int(result_option) not in [0, 1]:
            raise ValueError("invalid result option")

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
                raise ValueError("market not found")
            if int(market.status) in [3, 4]:
                raise ValueError("market already settled")

            total_real_pool = int(market.real_yes_pool) + int(market.real_no_pool)
            fee_burned = int(total_real_pool * int(market.fee_burn_bp) / 10000)
            fee_to_glory = int(total_real_pool * int(market.fee_glory_bp) / 10000)
            total_fee = int(fee_burned + fee_to_glory)
            base_payout_pool = int(total_real_pool - total_fee)

            winner_pool = (
                int(market.real_yes_pool)
                if int(result_option) == 1
                else int(market.real_no_pool)
            )
            loser_pool = int(total_real_pool - winner_pool)

            cfg = (
                session.execute(
                    select(SystemConfig)
                    .where(
                        SystemConfig.config_type == "prediction_market",
                        SystemConfig.config_key == "glory_fund",
                    )
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            # 荣耀奖池为**跨活动共用**的单一余额：除本活动的手续费外，21 点的抽水
            # 亦按比例注入其中（见 blackjack_engine 与 _settle_blackjack_hand）。
            # config_type 沿用 prediction_market 属历史命名，未迁移是为了不改动
            # 已上线的结算逻辑。
            #
            # 余额以**小数**字符串存储：21 点的单手注入天然为小数（注 5 普通胜的
            # 荣耀份额为 0.06），故此处必须用 float 解析——用 int() 会在读到小数
            # 时抛错并把余额静默清零。既有的整数字符串余额亦可被 float() 正常读入。
            if cfg:
                try:
                    current_glory = float(cfg.config_value or "0")
                except Exception:
                    current_glory = 0.0
            else:
                current_glory = 0.0

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
                glory_pool_extra_out = min(
                    int(target_compensation), int(available_glory)
                )
                payout_pool = int(base_payout_pool + glory_pool_extra_out)

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
                    ratio = float(user_amt) / float(winner_pool)
                    payout = round(float(payout_pool) * ratio, 2)
                    payout_map[int(tg_id)] = payout

                if payout_map:
                    stats_rows = (
                        session.execute(
                            select(Statistics)
                            .where(Statistics.tg_id.in_(list(payout_map.keys())))
                            .with_for_update()
                        )
                        .scalars()
                        .all()
                    )
                    stats_map = {int(s.tg_id): s for s in stats_rows}
                    for uid, payout in payout_map.items():
                        stats = stats_map.get(int(uid))
                        if stats:
                            mutation = credits_repository.add_tx(
                                session, CreditAccount.tg(int(uid)), float(payout)
                            )
                            credits_service.register_cache_invalidation(
                                session, mutation
                            )
                        else:
                            session.add(
                                Statistics(
                                    tg_id=int(uid), donation=0, credits=float(payout)
                                )
                            )

            market.status = 3
            market.result_option = int(result_option)
            market.resolution_note = resolution_note
            market.total_fee_collected = int(total_real_pool - payout_pool)
            market.fee_burned = int(fee_burned)
            market.fee_to_glory = int(fee_to_glory)
            market.resolved_by = int(resolved_by)
            market.resolved_at = int(now_ts)

            final_glory_balance = round(
                float(current_glory)
                + float(fee_to_glory)
                + float(glory_pool_extra_in)
                - float(glory_pool_extra_out),
                2,
            )
            if cfg:
                cfg.config_value = str(final_glory_balance)
                cfg.updated_at = int(now_ts)
            else:
                session.add(
                    SystemConfig(
                        config_type="prediction_market",
                        config_key="glory_fund",
                        config_value=str(final_glory_balance),
                        created_at=int(now_ts),
                        updated_at=int(now_ts),
                    )
                )

            session.flush()

            return {
                "market_id": int(market.id),
                "status": int(market.status),
                "result_option": int(result_option),
                "total_real_pool": int(total_real_pool),
                "total_fee": int(total_fee),
                "fee_burned": int(fee_burned),
                "fee_to_glory": int(fee_to_glory),
                "winner_count": int(winner_count),
                "payout_pool": int(payout_pool),
            }
