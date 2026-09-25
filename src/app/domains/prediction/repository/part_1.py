import time

from sqlalchemy import case, func, select

from app.core.db import get_session
from app.core.kv import SystemConfig
from app.domains.identity.models import Statistics
from app.domains.prediction.models import (
    PredictionBet,
    PredictionMarket,
    PredictionMarketSubmission,
)


class _PredictionRepositoryPart1:
    def _calc_prediction_odds(
        self,
        real_yes: int,
        real_no: int,
        virtual_yes: int,
        virtual_no: int,
    ) -> tuple[float, float]:
        total_pool = float(real_yes + real_no + virtual_yes + virtual_no)
        yes_den = float(real_yes + virtual_yes)
        no_den = float(real_no + virtual_no)
        yes_odds = round(total_pool / yes_den, 4) if yes_den > 0 else 0.0
        no_odds = round(total_pool / no_den, 4) if no_den > 0 else 0.0
        return yes_odds, no_odds

    def submit_prediction_market(
        self,
        title: str,
        betting_deadline: int,
        submitter_tg_id: int,
        description: str | None = None,
    ) -> int:
        if not str(title or "").strip():
            raise ValueError("title is required")

        now_ts = int(time.time())
        if int(betting_deadline) <= int(now_ts):
            raise ValueError("betting_deadline must be in the future")

        with get_session() as session:
            submission = PredictionMarketSubmission(
                title=str(title).strip(),
                description=description,
                betting_deadline=int(betting_deadline),
                status=0,
                submitter_tg_id=int(submitter_tg_id),
            )
            session.add(submission)
            session.flush()
            return int(submission.id)

    def list_prediction_submissions(
        self,
        status: int | None = None,
        limit: int = 50,
        submitter_tg_id: int | None = None,
    ) -> list[dict]:
        with get_session() as session:
            stmt = select(PredictionMarketSubmission)
            if status is not None:
                stmt = stmt.where(PredictionMarketSubmission.status == int(status))
            if submitter_tg_id is not None:
                stmt = stmt.where(
                    PredictionMarketSubmission.submitter_tg_id == int(submitter_tg_id)
                )
            stmt = stmt.order_by(PredictionMarketSubmission.id.desc()).limit(limit)

            rows = session.execute(stmt).scalars().all()
            return [
                {
                    "id": int(r.id),
                    "title": str(r.title or ""),
                    "description": r.description,
                    "betting_deadline": int(r.betting_deadline),
                    "status": int(r.status),
                    "submitter_tg_id": int(r.submitter_tg_id),
                    "reviewed_by": int(r.reviewed_by)
                    if r.reviewed_by is not None
                    else None,
                    "reviewed_at": int(r.reviewed_at)
                    if r.reviewed_at is not None
                    else None,
                    "review_note": r.review_note,
                    "market_id": int(r.market_id) if r.market_id is not None else None,
                    "created_at": r.created_at,
                }
                for r in rows
            ]

    def review_prediction_submission(
        self,
        submission_id: int,
        admin_tg_id: int,
        approved: bool,
        review_note: str | None = None,
        title: str | None = None,
        description: str | None = None,
        betting_deadline: int | None = None,
    ) -> dict:
        with get_session() as session:
            submission = (
                session.execute(
                    select(PredictionMarketSubmission)
                    .where(PredictionMarketSubmission.id == int(submission_id))
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not submission:
                raise ValueError("submission not found")
            if int(submission.status) != 0:
                raise ValueError("submission already reviewed")

            now_ts = int(time.time())
            final_title = str(
                title if title is not None else submission.title or ""
            ).strip()
            final_description = (
                description if description is not None else submission.description
            )
            final_deadline = int(
                betting_deadline
                if betting_deadline is not None
                else int(submission.betting_deadline)
            )

            if not final_title:
                raise ValueError("title is required")
            if final_deadline <= int(now_ts):
                raise ValueError("betting_deadline must be in the future")

            market_id: int | None = None
            if bool(approved):
                market = PredictionMarket(
                    title=final_title,
                    description=final_description,
                    status=1,
                    betting_deadline=final_deadline,
                    real_yes_pool=0,
                    real_no_pool=0,
                    virtual_yes_pool=500,
                    virtual_no_pool=500,
                    fee_rate_bp=500,
                    fee_burn_bp=300,
                    fee_glory_bp=200,
                    max_bet_per_user=500,
                    created_by=int(admin_tg_id),
                )
                session.add(market)
                session.flush()
                market_id = int(market.id)
                submission.status = 1
                submission.market_id = int(market_id)
            else:
                submission.status = 2

            submission.title = final_title
            submission.description = final_description
            submission.betting_deadline = final_deadline
            submission.reviewed_by = int(admin_tg_id)
            submission.reviewed_at = int(now_ts)
            submission.review_note = review_note

            session.flush()

            return {
                "submission_id": int(submission.id),
                "status": int(submission.status),
                "market_id": int(submission.market_id)
                if submission.market_id is not None
                else None,
                "title": str(submission.title or ""),
                "betting_deadline": int(submission.betting_deadline),
                "submitter_tg_id": int(submission.submitter_tg_id),
            }

    def create_prediction_market(
        self,
        title: str,
        description: str | None = None,
        betting_deadline: int | None = None,
        created_by: int | None = None,
        virtual_yes_pool: int = 500,
        virtual_no_pool: int = 500,
        fee_rate_bp: int = 500,
        fee_burn_bp: int = 300,
        fee_glory_bp: int = 200,
        max_bet_per_user: int = 500,
    ) -> int:
        if not title.strip():
            raise ValueError("title is required")
        if int(fee_burn_bp) + int(fee_glory_bp) != int(fee_rate_bp):
            raise ValueError("invalid fee split")
        if betting_deadline is None:
            raise ValueError("betting_deadline is required")
        now_ts = int(time.time())
        if int(betting_deadline) <= int(now_ts):
            raise ValueError("betting_deadline must be in the future")

        with get_session() as session:
            market = PredictionMarket(
                title=title.strip(),
                description=description,
                status=1,
                betting_deadline=int(betting_deadline) if betting_deadline else None,
                real_yes_pool=0,
                real_no_pool=0,
                virtual_yes_pool=int(max(0, virtual_yes_pool)),
                virtual_no_pool=int(max(0, virtual_no_pool)),
                fee_rate_bp=int(fee_rate_bp),
                fee_burn_bp=int(fee_burn_bp),
                fee_glory_bp=int(fee_glory_bp),
                max_bet_per_user=int(max_bet_per_user),
                created_by=created_by,
            )
            session.add(market)
            session.flush()
            return int(market.id)

    def list_prediction_markets(
        self, limit: int = 50, include_closed: bool = True
    ) -> list[dict]:
        with get_session() as session:
            active_first = case((PredictionMarket.status == 1, 1), else_=0).desc()
            stmt = (
                select(PredictionMarket)
                .order_by(active_first, PredictionMarket.id.desc())
                .limit(limit)
            )
            if not include_closed:
                stmt = (
                    select(PredictionMarket)
                    .where(PredictionMarket.status.in_([1, 2]))
                    .order_by(active_first, PredictionMarket.id.desc())
                    .limit(limit)
                )

            rows = session.execute(stmt).scalars().all()
            items: list[dict] = []
            for m in rows:
                yes_odds, no_odds = self._calc_prediction_odds(
                    int(m.real_yes_pool),
                    int(m.real_no_pool),
                    int(m.virtual_yes_pool),
                    int(m.virtual_no_pool),
                )
                items.append(
                    {
                        "id": int(m.id),
                        "title": m.title,
                        "description": m.description,
                        "status": int(m.status),
                        "result_option": int(m.result_option)
                        if m.result_option is not None
                        else None,
                        "betting_deadline": int(m.betting_deadline)
                        if m.betting_deadline is not None
                        else None,
                        "real_yes_pool": int(m.real_yes_pool),
                        "real_no_pool": int(m.real_no_pool),
                        "virtual_yes_pool": int(m.virtual_yes_pool),
                        "virtual_no_pool": int(m.virtual_no_pool),
                        "yes_odds": yes_odds,
                        "no_odds": no_odds,
                        "max_bet_per_user": int(m.max_bet_per_user),
                        "created_at": m.created_at,
                    }
                )
            return items

    def get_prediction_market_by_id(
        self, market_id: int, tg_id: int | None = None
    ) -> dict | None:
        with get_session() as session:
            m = (
                session.execute(
                    select(PredictionMarket).where(
                        PredictionMarket.id == int(market_id)
                    )
                )
                .scalars()
                .one_or_none()
            )
            if not m:
                return None

            yes_odds, no_odds = self._calc_prediction_odds(
                int(m.real_yes_pool),
                int(m.real_no_pool),
                int(m.virtual_yes_pool),
                int(m.virtual_no_pool),
            )

            my_yes = 0
            my_no = 0
            if tg_id is not None:
                rows = session.execute(
                    select(
                        PredictionBet.option,
                        func.coalesce(func.sum(PredictionBet.amount), 0),
                    )
                    .where(
                        PredictionBet.market_id == int(market_id),
                        PredictionBet.tg_id == int(tg_id),
                    )
                    .group_by(PredictionBet.option)
                ).all()
                for option, total in rows:
                    if int(option) == 1:
                        my_yes = int(total or 0)
                    else:
                        my_no = int(total or 0)

            return {
                "id": int(m.id),
                "title": m.title,
                "description": m.description,
                "status": int(m.status),
                "result_option": int(m.result_option)
                if m.result_option is not None
                else None,
                "betting_deadline": int(m.betting_deadline)
                if m.betting_deadline is not None
                else None,
                "real_yes_pool": int(m.real_yes_pool),
                "real_no_pool": int(m.real_no_pool),
                "virtual_yes_pool": int(m.virtual_yes_pool),
                "virtual_no_pool": int(m.virtual_no_pool),
                "yes_odds": yes_odds,
                "no_odds": no_odds,
                "max_bet_per_user": int(m.max_bet_per_user),
                "fee_rate_bp": int(m.fee_rate_bp),
                "fee_burn_bp": int(m.fee_burn_bp),
                "fee_glory_bp": int(m.fee_glory_bp),
                "resolution_note": m.resolution_note,
                "total_fee_collected": int(m.total_fee_collected),
                "fee_burned": int(m.fee_burned),
                "fee_to_glory": int(m.fee_to_glory),
                "my_yes_amount": int(my_yes),
                "my_no_amount": int(my_no),
                "created_at": m.created_at,
            }

    def place_prediction_bet(
        self,
        market_id: int,
        tg_id: int,
        option: int,
        amount: int,
    ) -> dict:
        if int(option) not in [0, 1]:
            raise ValueError("invalid option")
        if int(amount) <= 0:
            raise ValueError("amount must be > 0")

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
            if int(market.status) != 1:
                raise ValueError("market not open")
            if market.betting_deadline and int(now_ts) >= int(market.betting_deadline):
                raise ValueError("betting closed")

            user_total = session.execute(
                select(func.coalesce(func.sum(PredictionBet.amount), 0)).where(
                    PredictionBet.market_id == int(market.id),
                    PredictionBet.tg_id == int(tg_id),
                )
            ).scalar_one()
            if int(user_total or 0) + int(amount) > int(market.max_bet_per_user):
                raise ValueError("max bet per user exceeded")

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
                raise ValueError("user stats not found")
            if float(stats.credits) < float(amount):
                raise ValueError("insufficient credits")

            stats.credits = round(float(stats.credits) - float(amount), 2)

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
        from app.utils.utils import get_user_name_from_tg_id

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
                            stats.credits = round(
                                float(stats.credits) + float(payout), 2
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
