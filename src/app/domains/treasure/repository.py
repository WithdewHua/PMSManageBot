import secrets
import time

from sqlalchemy import case, delete, distinct, func, select

from app.core.db import get_session
from app.core.log import logger
from app.core.number import normalize_external_random_b
from app.domains.identity.models import Statistics
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
        """创建夺宝期数，返回 issue_id。"""
        total_shares = int(total_credits_required // credits_per_share)
        if total_shares <= 0:
            raise ValueError("total_shares must be > 0")
        if total_credits_required % credits_per_share != 0:
            raise ValueError(
                "total_credits_required must be divisible by credits_per_share"
            )
        if prize_credits <= 0 or total_credits_required < prize_credits:
            raise ValueError("invalid credits settings")

        with get_session() as session:
            # 起始幸运号：如果前端未传，则随机生成一个 8 位起始号。
            # 需要保证号段长度为 total_shares，且 number_high >= number_low。
            if start_number is None:
                lower = 10_000_001
                upper = 99_999_999 - int(total_shares) + 1
                if upper < lower:
                    # 极端情况下（总份数过大）退化为固定起点
                    start_number = lower
                else:
                    # 尝试避免与历史期数 start_number 完全重复（非强需求，尽量即可）
                    used = {
                        n
                        for (n,) in session.execute(
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
                    raise ValueError("start_number must be > 0")

            # 最终范围校验
            number_low = int(start_number)
            number_high = int(start_number) + int(total_shares) - 1
            if number_high < number_low:
                raise ValueError("invalid number range")

            issue = TreasureIssue(
                title=title,
                description=description,
                prize_credits=int(prize_credits),
                total_credits_required=int(total_credits_required),
                credits_per_share=int(credits_per_share),
                total_shares=int(total_shares),
                start_number=int(start_number),
                status=1,
                shares_sold=0,
                created_by=created_by,
            )
            session.add(issue)
            session.flush()
            return int(issue.id)

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
        from app.utils.utils import get_user_name_from_tg_id

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
        """参与夺宝：扣积分 -> 分配幸运号码 -> 若满员则开奖结算。

        并发安全：对 issue 行加 FOR UPDATE 锁，确保 shares_sold 增量与号码分配唯一。

        Returns: {participation, issue, settled(bool), winner_number?, winner_tg_id?}
        """
        if quantity <= 0:
            raise ValueError("quantity must be > 0")
        if quantity > 100:
            raise ValueError("quantity too large")

        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)

        with get_session() as session:
            issue = (
                session.execute(
                    select(TreasureIssue)
                    .where(TreasureIssue.id == issue_id)
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not issue:
                raise ValueError("issue not found")
            if int(issue.status) != 1:
                raise ValueError("issue not active")
            if int(issue.shares_sold) >= int(issue.total_shares):
                raise ValueError("issue already full")

            remaining = int(issue.total_shares) - int(issue.shares_sold)
            buy_qty = min(int(quantity), int(remaining))
            if buy_qty <= 0:
                raise ValueError("issue already full")

            # 单用户累计购买上限：不超过总份数的 20%（分批/单次都限制）
            max_per_user = max(1, int(int(issue.total_shares) * 0.2))
            user_bought = session.execute(
                select(func.count(TreasureParticipation.id)).where(
                    TreasureParticipation.issue_id == int(issue.id),
                    TreasureParticipation.tg_id == int(tg_id),
                )
            ).scalar_one()
            if int(user_bought) + int(buy_qty) > int(max_per_user):
                raise ValueError(
                    f"purchase limit exceeded: max {max_per_user} shares per user"
                )

            # 费用
            cost_per_share = int(issue.credits_per_share)
            total_cost = int(cost_per_share) * int(buy_qty)

            # 扣用户积分（仅 tg 用户体系）
            stats = (
                session.execute(
                    select(Statistics)
                    .where(Statistics.tg_id == tg_id)
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not stats:
                raise ValueError("user stats not found")
            if float(stats.credits) < float(total_cost):
                raise ValueError("insufficient credits")
            stats.credits = round(float(stats.credits) - float(total_cost), 2)

            participations: list[TreasureParticipation] = []
            lucky_numbers: list[int] = []

            # 分配幸运号码（随机，从剩余未占用号码中选，事务内保证并发安全）
            import random

            number_low = int(issue.start_number)
            number_high = int(issue.start_number) + int(issue.total_shares) - 1
            if number_high < number_low:
                raise ValueError("invalid number range")

            # 当前已占用号码集合（在 issue FOR UPDATE 锁下读取即可）
            existing_numbers = {
                n
                for (n,) in session.execute(
                    select(TreasureParticipation.lucky_number).where(
                        TreasureParticipation.issue_id == int(issue.id)
                    )
                ).all()
            }

            available = [
                n
                for n in range(number_low, number_high + 1)
                if n not in existing_numbers
            ]
            if len(available) < int(buy_qty):
                raise ValueError("issue already full")

            chosen_numbers = random.sample(available, k=int(buy_qty))

            for i, lucky_number in enumerate(chosen_numbers):
                p = TreasureParticipation(
                    issue_id=int(issue.id),
                    tg_id=int(tg_id),
                    lucky_number=int(lucky_number),
                    cost_credits=int(cost_per_share),
                    created_at_ms=int(timestamp_ms) + i,
                )
                session.add(p)
                participations.append(p)
                lucky_numbers.append(int(lucky_number))
                issue.shares_sold = int(issue.shares_sold) + 1

            participation = participations[-1]  # 兼容旧字段
            settled = False
            winner_number = None
            winner_tg_id = None

            # 满员且尚未开奖时结算（status 检查保证幂等）
            if (
                int(issue.shares_sold) >= int(issue.total_shares)
                and int(issue.status) == 1
            ):
                settled = True

                # 计算采样数 N：按参与人数百分比，限定 [min,max]
                total = int(issue.total_shares)
                n = int(
                    max(
                        sample_last_n_min,
                        min(sample_last_n_max, round(total * sample_last_n_ratio)),
                    )
                )
                n = min(n, total)

                # 取最后 N 条参与记录的 created_at_ms
                last_rows = session.execute(
                    select(
                        TreasureParticipation.created_at_ms,
                        TreasureParticipation.tg_id,
                    )
                    .where(TreasureParticipation.issue_id == int(issue.id))
                    .order_by(TreasureParticipation.id.desc())
                    .limit(n)
                ).all()
                a = sum(int(r[0]) for r in last_rows)
                b = normalize_external_random_b(
                    int(external_random_b)
                    if external_random_b is not None
                    else int(issue.external_random_b or 0),
                    default=0,
                )

                # 中奖号码：((A+B) % total_shares) + start_number
                offset = (a + b) % int(issue.total_shares)
                winner_number = int(issue.start_number) + int(offset)

                # 找到赢家（号码唯一）
                win_part = (
                    session.execute(
                        select(TreasureParticipation).where(
                            TreasureParticipation.issue_id == int(issue.id),
                            TreasureParticipation.lucky_number == int(winner_number),
                        )
                    )
                    .scalars()
                    .one()
                )
                winner_tg_id = int(win_part.tg_id)

                # 发奖：给中奖者加 prize_credits
                winner_stats = (
                    session.execute(
                        select(Statistics)
                        .where(Statistics.tg_id == winner_tg_id)
                        .with_for_update()
                    )
                    .scalars()
                    .one_or_none()
                )
                if winner_stats:
                    winner_stats.credits = round(
                        float(winner_stats.credits) + float(issue.prize_credits), 2
                    )
                else:
                    # 如果赢家没有统计记录，创建一条（兼容极端情况）
                    session.add(
                        Statistics(
                            tg_id=winner_tg_id,
                            donation=0,
                            credits=float(issue.prize_credits),
                        )
                    )

                # 写回期数结果
                issue.status = 2
                issue.external_random_b = b
                issue.winner_number = int(winner_number)
                issue.winner_tg_id = int(winner_tg_id)
                issue.settled_at = int(time.time())

            session.flush()

            return {
                "participation": {
                    "id": int(participation.id) if participation.id else None,
                    "issue_id": int(issue.id),
                    "tg_id": int(tg_id),
                    "lucky_number": int(lucky_numbers[-1]),
                    "cost_credits": int(cost_per_share),
                    "created_at_ms": int(timestamp_ms) + (buy_qty - 1),
                },
                "participations": [
                    {
                        "id": int(p.id) if p.id else None,
                        "issue_id": int(issue.id),
                        "tg_id": int(tg_id),
                        "lucky_number": int(n),
                        "cost_credits": int(cost_per_share),
                        "created_at_ms": int(timestamp_ms) + idx,
                    }
                    for idx, (p, n) in enumerate(zip(participations, lucky_numbers))
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
                "winner_number": int(winner_number)
                if winner_number is not None
                else None,
                "winner_tg_id": int(winner_tg_id) if winner_tg_id is not None else None,
            }

    def cancel_treasure_issue(self, issue_id: int) -> dict:
        """管理员取消进行中的夺宝期数，并退还参与者积分。

        规则：
        - 仅 status==1（进行中）允许取消
        - 退还每位参与者已支付的 cost_credits 之和
        - 删除所有参与记录
        - 将期数标记为 status=3（已取消），shares_sold 置 0（便于展示）

        返回：{issue_id, refunded_total, refunded_users, participation_count}
        """
        with get_session() as session:
            issue = (
                session.execute(
                    select(TreasureIssue)
                    .where(TreasureIssue.id == issue_id)
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not issue:
                raise ValueError("issue not found")
            if int(issue.status) != 1:
                raise ValueError("issue not active")

            # 统计需要退还的积分（按 tg_id 聚合）
            rows = session.execute(
                select(
                    TreasureParticipation.tg_id,
                    func.count(TreasureParticipation.id),
                    func.coalesce(func.sum(TreasureParticipation.cost_credits), 0),
                )
                .where(TreasureParticipation.issue_id == int(issue.id))
                .group_by(TreasureParticipation.tg_id)
            ).all()

            refunded_total = 0.0
            refunded_users = 0
            participation_count = 0

            for tg_id, cnt, sum_cost in rows:
                refund = float(sum_cost or 0)
                refunded_total += refund
                participation_count += int(cnt or 0)
                if refund <= 0:
                    continue

                stats = (
                    session.execute(
                        select(Statistics)
                        .where(Statistics.tg_id == int(tg_id))
                        .with_for_update()
                    )
                    .scalars()
                    .one_or_none()
                )
                if stats:
                    stats.credits = round(float(stats.credits) + refund, 2)
                else:
                    session.add(
                        Statistics(
                            tg_id=int(tg_id),
                            donation=0,
                            credits=float(refund),
                        )
                    )
                refunded_users += 1

            # 删除参与记录
            session.execute(
                delete(TreasureParticipation).where(
                    TreasureParticipation.issue_id == int(issue.id)
                )
            )

            # 标记取消
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
