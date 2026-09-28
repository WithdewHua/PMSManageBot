"""大预言家 repository：题目与投稿的创建、审核、列表与详情（由 part_N 机械拆分）。"""

import time

from sqlalchemy import case, func, select

from app.core.db import get_session
from app.domains.prediction import exceptions as prediction_exceptions
from app.domains.prediction.models import (
    PredictionBet,
    PredictionMarket,
    PredictionMarketSubmission,
)


class _PredictionRepositoryMarkets:
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
            raise prediction_exceptions.title_required()

        now_ts = int(time.time())
        if int(betting_deadline) <= int(now_ts):
            raise prediction_exceptions.deadline_invalid()

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
                raise prediction_exceptions.submission_not_found()
            if int(submission.status) != 0:
                raise prediction_exceptions.submission_already_reviewed()

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
                raise prediction_exceptions.title_required()
            if final_deadline <= int(now_ts):
                raise prediction_exceptions.review_deadline_invalid()

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
            raise prediction_exceptions.title_required()
        if int(fee_burn_bp) + int(fee_glory_bp) != int(fee_rate_bp):
            raise prediction_exceptions.invalid_fee_split()
        if betting_deadline is None:
            raise prediction_exceptions.deadline_missing()
        now_ts = int(time.time())
        if int(betting_deadline) <= int(now_ts):
            raise prediction_exceptions.deadline_invalid()

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


def list_prediction_markets_closing_soon(
    now_ts: int, deadline_upper_ts: int
) -> list[dict]:
    """读取未来窗口内仍可下注的题目，供截止提醒 service 使用。"""
    with get_session() as session:
        rows = (
            session.execute(
                select(PredictionMarket)
                .where(
                    PredictionMarket.status == 1,
                    PredictionMarket.betting_deadline.is_not(None),
                    PredictionMarket.betting_deadline > int(now_ts),
                    PredictionMarket.betting_deadline <= int(deadline_upper_ts),
                )
                .order_by(PredictionMarket.betting_deadline.asc())
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": int(m.id),
                "title": str(m.title or ""),
                "betting_deadline": int(m.betting_deadline),
            }
            for m in rows
            if m.betting_deadline is not None
        ]
