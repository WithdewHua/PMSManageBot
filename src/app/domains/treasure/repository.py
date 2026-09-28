import secrets
import time

from sqlalchemy import case, delete, distinct, func, select

from app.core.db import get_session
from app.core.log import logger
from app.core.number import normalize_external_random_b
from app.domains.credits import repository as credits_repository
from app.domains.credits.types import CreditAccount
from app.domains.identity import repository as identity_repository
from app.domains.identity.models import Statistics
from app.domains.treasure import exceptions as treasure_exceptions
from app.domains.treasure.models import TreasureIssue, TreasureParticipation


class TreasureRepository:
    def create_treasure_issue(
        self,
        title: str,
        prize_credits: int,
        total_credits_required: int,
        credits_per_share: int = 10,
        start_number: int | None = None,
        description: str | None = None,
        created_by: int | None = None,
    ) -> int:
        return create_treasure_issue(
            title=title,
            prize_credits=prize_credits,
            total_credits_required=total_credits_required,
            credits_per_share=credits_per_share,
            start_number=start_number,
            description=description,
            created_by=created_by,
        )

    def get_treasure_issue_by_id(self, issue_id: int) -> dict | None:
        with get_session() as session:
            stmt = select(TreasureIssue).where(TreasureIssue.id == issue_id)
            issue = session.execute(stmt).scalar_one_or_none()
            if not issue:
                return None
            return {
                "id": int(issue.id),
                "title": issue.title,
                "description": issue.description,
                "prize_credits": int(issue.prize_credits),
                "total_credits_required": int(issue.total_credits_required),
                "credits_per_share": int(issue.credits_per_share),
                "total_shares": int(issue.total_shares),
                "start_number": int(issue.start_number),
                "status": int(issue.status),
                "shares_sold": int(issue.shares_sold),
                "external_random_b": int(issue.external_random_b)
                if issue.external_random_b is not None
                else None,
                "winner_number": int(issue.winner_number)
                if issue.winner_number is not None
                else None,
                "winner_tg_id": int(issue.winner_tg_id)
                if issue.winner_tg_id is not None
                else None,
                "settled_at": int(issue.settled_at)
                if issue.settled_at is not None
                else None,
                "created_by": int(issue.created_by)
                if issue.created_by is not None
                else None,
                "created_at": issue.created_at,
            }

    def list_treasure_issues(
        self, limit: int = 50, include_closed: bool = True
    ) -> list[dict]:
        with get_session() as session:
            active_first = case((TreasureIssue.status == 1, 1), else_=0).desc()

            stmt = (
                select(TreasureIssue)
                .order_by(active_first, TreasureIssue.id.desc())
                .limit(limit)
            )
            if not include_closed:
                stmt = (
                    select(TreasureIssue)
                    .where(TreasureIssue.status == 1)
                    .order_by(TreasureIssue.id.desc())
                    .limit(limit)
                )
            issues = session.execute(stmt).scalars().all()
            return [
                {
                    "id": int(i.id),
                    "title": i.title,
                    "prize_credits": int(i.prize_credits),
                    "total_credits_required": int(i.total_credits_required),
                    "credits_per_share": int(i.credits_per_share),
                    "total_shares": int(i.total_shares),
                    "start_number": int(i.start_number),
                    "shares_sold": int(i.shares_sold),
                    "status": int(i.status),
                    "winner_number": int(i.winner_number)
                    if i.winner_number is not None
                    else None,
                    "winner_tg_id": int(i.winner_tg_id)
                    if i.winner_tg_id is not None
                    else None,
                    "created_at": i.created_at,
                }
                for i in issues
            ]

    def list_treasure_participations(
        self, issue_id: int, limit: int = 200
    ) -> list[dict]:
        from app.core.telegram import get_user_name_from_tg_id

        with get_session() as session:
            issue_seq = (
                func.row_number()
                .over(
                    partition_by=TreasureParticipation.issue_id,
                    order_by=TreasureParticipation.id.asc(),
                )
                .label("issue_seq")
            )
            stmt = (
                select(
                    TreasureParticipation.id,
                    TreasureParticipation.issue_id,
                    TreasureParticipation.tg_id,
                    TreasureParticipation.lucky_number,
                    TreasureParticipation.cost_credits,
                    TreasureParticipation.created_at_ms,
                    TreasureParticipation.created_at,
                    issue_seq,
                )
                .where(TreasureParticipation.issue_id == issue_id)
                .order_by(TreasureParticipation.id.desc())
                .limit(limit)
            )
            rows = session.execute(stmt).all()
            return [
                {
                    "id": int(p.id),
                    "issue_id": int(p.issue_id),
                    "issue_seq": int(p.issue_seq),
                    "tg_id": int(p.tg_id),
                    "tg_username": str(
                        get_user_name_from_tg_id(int(p.tg_id)) or p.tg_id
                    ),
                    "lucky_number": int(p.lucky_number),
                    "cost_credits": int(p.cost_credits),
                    "created_at_ms": int(p.created_at_ms),
                    "created_at": p.created_at,
                }
                for p in rows
            ]

    def join_treasure_issue(
        self,
        issue_id: int,
        tg_id: int,
        external_random_b: int | None = None,
        timestamp_ms: int | None = None,
        quantity: int = 1,
        sample_last_n_ratio: float = 0.4,
        sample_last_n_min: int = 10,
        sample_last_n_max: int = 50,
    ) -> dict:
        return join_treasure_issue(
            issue_id=issue_id,
            tg_id=tg_id,
            external_random_b=external_random_b,
            timestamp_ms=timestamp_ms,
            quantity=quantity,
            sample_last_n_ratio=sample_last_n_ratio,
            sample_last_n_min=sample_last_n_min,
            sample_last_n_max=sample_last_n_max,
        )

    def cancel_treasure_issue(self, issue_id: int) -> dict:
        return cancel_treasure_issue(issue_id=int(issue_id))

    def get_user_treasure_stats(self, tg_id: int) -> dict:
        """获取用户个人夺宝统计数据。"""
        try:
            with get_session() as session:
                participated_issues = (
                    session.execute(
                        select(
                            func.count(distinct(TreasureParticipation.issue_id))
                        ).where(TreasureParticipation.tg_id == int(tg_id))
                    ).scalar()
                    or 0
                )

                total_cost_credits = (
                    session.execute(
                        select(func.sum(TreasureParticipation.cost_credits)).where(
                            TreasureParticipation.tg_id == int(tg_id)
                        )
                    ).scalar()
                    or 0
                )

                win_count = (
                    session.execute(
                        select(func.count(TreasureIssue.id)).where(
                            TreasureIssue.winner_tg_id == int(tg_id),
                            TreasureIssue.status == 2,
                        )
                    ).scalar()
                    or 0
                )

                total_prize_credits = (
                    session.execute(
                        select(func.sum(TreasureIssue.prize_credits)).where(
                            TreasureIssue.winner_tg_id == int(tg_id),
                            TreasureIssue.status == 2,
                        )
                    ).scalar()
                    or 0
                )

                recent_rows = session.execute(
                    select(
                        TreasureParticipation.issue_id,
                        TreasureParticipation.cost_credits,
                        TreasureParticipation.lucky_number,
                        TreasureParticipation.created_at,
                        TreasureIssue.winner_tg_id,
                        TreasureIssue.prize_credits,
                        TreasureIssue.status,
                    )
                    .join(
                        TreasureIssue,
                        TreasureIssue.id == TreasureParticipation.issue_id,
                    )
                    .where(TreasureParticipation.tg_id == int(tg_id))
                    .order_by(TreasureParticipation.id.desc())
                    .limit(10)
                ).all()

                recent_participations = []
                for row in recent_rows:
                    is_winner = (
                        int(row.winner_tg_id) == int(tg_id)
                        if row.winner_tg_id is not None
                        else False
                    )
                    recent_participations.append(
                        {
                            "issue_id": int(row.issue_id),
                            "cost_credits": int(row.cost_credits),
                            "lucky_number": int(row.lucky_number),
                            "is_winner": bool(is_winner),
                            "won_credits": int(row.prize_credits)
                            if is_winner and int(row.status) == 2
                            else 0,
                            "created_at": row.created_at,
                        }
                    )

                return {
                    "participated_issues": int(participated_issues),
                    "total_cost_credits": int(total_cost_credits),
                    "win_count": int(win_count),
                    "total_prize_credits": int(total_prize_credits),
                    "recent_participations": recent_participations,
                }
        except Exception as e:
            logger.error(f"Error getting user treasure stats: {e}")
            return {
                "participated_issues": 0,
                "total_cost_credits": 0,
                "win_count": 0,
                "total_prize_credits": 0,
                "recent_participations": [],
            }


def count_participated_issues_tx(session, tg_id: int, since: int, until: int) -> int:
    """指定时间窗内参与过的夺宝期数（按 issue 去重，闭区间，毫秒时间戳）。"""
    return int(
        session.execute(
            select(func.count(distinct(TreasureParticipation.issue_id))).where(
                TreasureParticipation.tg_id == int(tg_id),
                TreasureParticipation.created_at_ms >= int(since) * 1000,
                TreasureParticipation.created_at_ms <= int(until) * 1000,
            )
        ).scalar_one()
    )


# Module-level repository API used by the promoted service.  The transitional
# TreasureRepository facade above remains until the final facade-removal task.
_repository = TreasureRepository()


def create_treasure_issue_tx(
    session,
    *,
    title: str,
    prize_credits: int,
    total_credits_required: int,
    credits_per_share: int = 10,
    start_number: int | None = None,
    description: str | None = None,
    created_by: int | None = None,
) -> int:
    """Create an issue in the caller-owned transaction."""
    total_shares = int(total_credits_required // credits_per_share)
    if total_shares <= 0:
        raise treasure_exceptions.create_total_shares_invalid()
    if total_credits_required % credits_per_share != 0:
        raise treasure_exceptions.create_not_divisible()
    if prize_credits <= 0 or total_credits_required < prize_credits:
        raise treasure_exceptions.create_credits_invalid()

    if start_number is None:
        lower = 10_000_001
        upper = 99_999_999 - int(total_shares) + 1
        if upper < lower:
            start_number = lower
        else:
            used = {
                int(number)
                for (number,) in session.execute(
                    select(TreasureIssue.start_number)
                    .order_by(TreasureIssue.id.desc())
                    .limit(500)
                ).all()
            }
            for _ in range(30):
                candidate = lower + secrets.randbelow(int(upper - lower + 1))
                if int(candidate) not in used:
                    start_number = int(candidate)
                    break
            else:
                start_number = lower + secrets.randbelow(int(upper - lower + 1))
    else:
        start_number = int(start_number)
        if start_number <= 0:
            raise treasure_exceptions.start_number_invalid()

    number_low = int(start_number)
    number_high = number_low + int(total_shares) - 1
    if number_high < number_low:
        raise treasure_exceptions.invalid_number_range()

    issue = TreasureIssue(
        title=title,
        description=description,
        prize_credits=int(prize_credits),
        total_credits_required=int(total_credits_required),
        credits_per_share=int(credits_per_share),
        total_shares=int(total_shares),
        start_number=number_low,
        status=1,
        shares_sold=0,
        created_by=created_by,
    )
    session.add(issue)
    session.flush()
    return int(issue.id)


def create_treasure_issue(
    *,
    title: str,
    prize_credits: int,
    total_credits_required: int,
    credits_per_share: int = 10,
    start_number: int | None = None,
    description: str | None = None,
    created_by: int | None = None,
) -> int:
    with get_session() as session:
        return create_treasure_issue_tx(
            session,
            title=title,
            prize_credits=prize_credits,
            total_credits_required=total_credits_required,
            credits_per_share=credits_per_share,
            start_number=start_number,
            description=description,
            created_by=created_by,
        )


def get_treasure_issue_by_id(issue_id: int) -> dict | None:
    return _repository.get_treasure_issue_by_id(int(issue_id))


def list_treasure_issues(*, limit: int = 50, include_closed: bool = True) -> list[dict]:
    return _repository.list_treasure_issues(
        limit=int(limit), include_closed=bool(include_closed)
    )


def list_treasure_participations(issue_id: int, *, limit: int = 100) -> list[dict]:
    return _repository.list_treasure_participations(int(issue_id), limit=int(limit))


def join_treasure_issue_tx(
    session,
    *,
    issue_id: int,
    tg_id: int,
    external_random_b: int | None = None,
    timestamp_ms: int | None = None,
    quantity: int = 1,
    sample_last_n_ratio: float = 0.4,
    sample_last_n_min: int = 10,
    sample_last_n_max: int = 50,
) -> dict:
    """Join and, when full, settle an issue in one caller-owned transaction."""
    if int(quantity) <= 0:
        raise treasure_exceptions.quantity_invalid()
    if int(quantity) > 100:
        raise treasure_exceptions.quantity_too_large()
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)

    issue = (
        session.execute(
            select(TreasureIssue)
            .where(TreasureIssue.id == int(issue_id))
            .with_for_update()
        )
        .scalars()
        .one_or_none()
    )
    if issue is None:
        raise treasure_exceptions.issue_not_found()
    if int(issue.status) != 1:
        raise treasure_exceptions.issue_not_active()
    if int(issue.shares_sold) >= int(issue.total_shares):
        raise treasure_exceptions.issue_full()

    remaining = int(issue.total_shares) - int(issue.shares_sold)
    buy_qty = min(int(quantity), remaining)
    if buy_qty <= 0:
        raise treasure_exceptions.issue_full()

    max_per_user = max(1, int(int(issue.total_shares) * 0.2))
    user_bought = session.execute(
        select(func.count(TreasureParticipation.id)).where(
            TreasureParticipation.issue_id == int(issue.id),
            TreasureParticipation.tg_id == int(tg_id),
        )
    ).scalar_one()
    if int(user_bought) + int(buy_qty) > int(max_per_user):
        raise treasure_exceptions.purchase_limit_exceeded(max_per_user)

    cost_per_share = int(issue.credits_per_share)
    total_cost = cost_per_share * int(buy_qty)
    stats = (
        session.execute(
            select(Statistics).where(Statistics.tg_id == int(tg_id)).with_for_update()
        )
        .scalars()
        .one_or_none()
    )
    if stats is None:
        raise treasure_exceptions.user_stats_not_found()
    if float(stats.credits) < float(total_cost):
        raise treasure_exceptions.insufficient_credits()
    credits_repository.deduct_tx(session, CreditAccount.tg(int(tg_id)), total_cost)

    import random

    number_low = int(issue.start_number)
    number_high = number_low + int(issue.total_shares) - 1
    if number_high < number_low:
        raise treasure_exceptions.invalid_number_range()

    existing_numbers = {
        number
        for (number,) in session.execute(
            select(TreasureParticipation.lucky_number).where(
                TreasureParticipation.issue_id == int(issue.id)
            )
        ).all()
    }
    available = [
        number
        for number in range(number_low, number_high + 1)
        if number not in existing_numbers
    ]
    if len(available) < int(buy_qty):
        raise treasure_exceptions.issue_full()

    chosen_numbers = random.sample(available, k=int(buy_qty))
    participations: list[TreasureParticipation] = []
    lucky_numbers: list[int] = []
    for index, lucky_number in enumerate(chosen_numbers):
        participation = TreasureParticipation(
            issue_id=int(issue.id),
            tg_id=int(tg_id),
            lucky_number=int(lucky_number),
            cost_credits=cost_per_share,
            created_at_ms=int(timestamp_ms) + index,
        )
        session.add(participation)
        participations.append(participation)
        lucky_numbers.append(int(lucky_number))
        issue.shares_sold = int(issue.shares_sold) + 1

    settled = False
    winner_number = None
    winner_tg_id = None
    if int(issue.shares_sold) >= int(issue.total_shares) and int(issue.status) == 1:
        settled = True
        total = int(issue.total_shares)
        sample_size = int(
            max(
                sample_last_n_min,
                min(sample_last_n_max, round(total * sample_last_n_ratio)),
            )
        )
        sample_size = min(sample_size, total)
        last_rows = session.execute(
            select(
                TreasureParticipation.created_at_ms,
                TreasureParticipation.tg_id,
            )
            .where(TreasureParticipation.issue_id == int(issue.id))
            .order_by(TreasureParticipation.id.desc())
            .limit(sample_size)
        ).all()
        a = sum(int(row[0]) for row in last_rows)
        b = normalize_external_random_b(
            int(external_random_b)
            if external_random_b is not None
            else int(issue.external_random_b or 0),
            default=0,
        )
        offset = (a + b) % total
        winner_number = int(issue.start_number) + int(offset)
        winning_participation = (
            session.execute(
                select(TreasureParticipation).where(
                    TreasureParticipation.issue_id == int(issue.id),
                    TreasureParticipation.lucky_number == int(winner_number),
                )
            )
            .scalars()
            .one()
        )
        winner_tg_id = int(winning_participation.tg_id)
        identity_repository.ensure_statistics_tx(session, winner_tg_id)
        credits_repository.add_tx(
            session,
            CreditAccount.tg(winner_tg_id),
            float(issue.prize_credits),
        )
        issue.status = 2
        issue.external_random_b = b
        issue.winner_number = int(winner_number)
        issue.winner_tg_id = int(winner_tg_id)
        issue.settled_at = int(time.time())

    session.flush()
    return {
        "participation": {
            "id": int(participations[-1].id),
            "issue_id": int(issue.id),
            "tg_id": int(tg_id),
            "lucky_number": int(lucky_numbers[-1]),
            "cost_credits": cost_per_share,
            "created_at_ms": int(timestamp_ms) + int(buy_qty) - 1,
        },
        "participations": [
            {
                "id": int(participation.id),
                "issue_id": int(issue.id),
                "tg_id": int(tg_id),
                "lucky_number": int(number),
                "cost_credits": cost_per_share,
                "created_at_ms": int(timestamp_ms) + index,
            }
            for index, (participation, number) in enumerate(
                zip(participations, lucky_numbers)
            )
        ],
        "issue": {
            "id": int(issue.id),
            "shares_sold": int(issue.shares_sold),
            "total_shares": int(issue.total_shares),
            "status": int(issue.status),
            "winner_number": int(issue.winner_number)
            if issue.winner_number is not None
            else None,
            "winner_tg_id": int(issue.winner_tg_id)
            if issue.winner_tg_id is not None
            else None,
        },
        "settled": settled,
        "winner_number": int(winner_number) if winner_number is not None else None,
        "winner_tg_id": int(winner_tg_id) if winner_tg_id is not None else None,
    }


def join_treasure_issue(
    *,
    issue_id: int,
    tg_id: int,
    external_random_b: int | None = None,
    timestamp_ms: int | None = None,
    quantity: int = 1,
    sample_last_n_ratio: float = 0.4,
    sample_last_n_min: int = 10,
    sample_last_n_max: int = 50,
) -> dict:
    with get_session() as session:
        return join_treasure_issue_tx(
            session,
            issue_id=int(issue_id),
            tg_id=int(tg_id),
            external_random_b=external_random_b,
            timestamp_ms=timestamp_ms,
            quantity=int(quantity),
            sample_last_n_ratio=float(sample_last_n_ratio),
            sample_last_n_min=int(sample_last_n_min),
            sample_last_n_max=int(sample_last_n_max),
        )


def cancel_treasure_issue_tx(session, *, issue_id: int) -> dict:
    """Cancel an issue and refund all participants in the caller transaction."""
    issue = (
        session.execute(
            select(TreasureIssue)
            .where(TreasureIssue.id == int(issue_id))
            .with_for_update()
        )
        .scalars()
        .one_or_none()
    )
    if issue is None:
        raise treasure_exceptions.issue_not_found()
    if int(issue.status) != 1:
        raise treasure_exceptions.cancel_not_active()

    rows = session.execute(
        select(
            TreasureParticipation.tg_id,
            func.count(TreasureParticipation.id),
            func.coalesce(func.sum(TreasureParticipation.cost_credits), 0),
        )
        .where(TreasureParticipation.issue_id == int(issue.id))
        .group_by(TreasureParticipation.tg_id)
        .order_by(TreasureParticipation.tg_id)
    ).all()
    refunded_total = 0.0
    refunded_users = 0
    participation_count = 0
    for tg_id, count, sum_cost in rows:
        refund = float(sum_cost or 0)
        refunded_total += refund
        participation_count += int(count or 0)
        if refund <= 0:
            continue
        identity_repository.ensure_statistics_tx(session, int(tg_id))
        credits_repository.add_tx(session, CreditAccount.tg(int(tg_id)), refund)
        refunded_users += 1

    session.execute(
        delete(TreasureParticipation).where(
            TreasureParticipation.issue_id == int(issue.id)
        )
    )
    issue.status = 3
    issue.shares_sold = 0
    issue.external_random_b = None
    issue.winner_number = None
    issue.winner_tg_id = None
    issue.settled_at = None
    session.flush()
    return {
        "issue_id": int(issue.id),
        "refunded_total": round(float(refunded_total), 2),
        "refunded_users": int(refunded_users),
        "participation_count": int(participation_count),
    }


def cancel_treasure_issue(*, issue_id: int) -> dict:
    with get_session() as session:
        return cancel_treasure_issue_tx(session, issue_id=int(issue_id))


def get_user_treasure_stats(tg_id: int) -> dict:
    return _repository.get_user_treasure_stats(int(tg_id))


__all__ = [
    "TreasureRepository",
    "cancel_treasure_issue",
    "cancel_treasure_issue_tx",
    "count_participated_issues_tx",
    "create_treasure_issue",
    "create_treasure_issue_tx",
    "get_treasure_issue_by_id",
    "get_user_treasure_stats",
    "join_treasure_issue",
    "join_treasure_issue_tx",
    "list_treasure_issues",
    "list_treasure_participations",
]
