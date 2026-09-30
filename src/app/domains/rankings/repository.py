import time

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.core.db import get_session
from app.domains.badges.models import UserBadge
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
from app.domains.luckywheel.models import WheelStats


def _rank_user_badge(row: UserBadge) -> dict:
    """Read-model-local conversion: do not depend on facade MRO helpers."""
    result = {
        key: getattr(row, key)
        for key in (
            "id",
            "tg_id",
            "badge_id",
            "credits_cost",
            "redeemed_at",
            "expires_at",
            "is_active",
        )
    }
    result["bonus_active"] = row.expires_at > int(time.time())
    result["badge"] = (
        {
            key: getattr(row.badge, key)
            for key in (
                "id",
                "badge_type",
                "name",
                "description",
                "icon_url",
                "credits_cost",
                "bonus_percentage",
                "valid_days",
                "is_enabled",
                "created_at",
                "updated_at",
            )
        }
        if row.badge
        else None
    )
    return result


def get_credits_rank() -> list[tuple[int, float]]:
    """获取积分排行"""
    with get_session() as session:
        stmt = select(Statistics.tg_id, Statistics.credits).order_by(
            Statistics.credits.desc()
        )
        results = session.execute(stmt).fetchall()
        return [(int(r[0]), float(r[1] or 0)) for r in results]


def get_donation_rank() -> list[tuple[int, float]]:
    """获取捐赠排行"""
    with get_session() as session:
        stmt = select(Statistics.tg_id, Statistics.donation).order_by(
            Statistics.donation.desc()
        )
        results = session.execute(stmt).fetchall()
        return [(int(r[0]), float(r[1] or 0)) for r in results]


def get_plex_watched_time_rank() -> list[
    tuple[int, int | None, str, float, bool | None]
]:
    """获取 Plex 观看时长排行"""
    with get_session() as session:
        stmt = select(
            PlexUser.plex_id,
            PlexUser.tg_id,
            PlexUser.plex_username,
            PlexUser.watched_time,
            PlexUser.is_premium,
        ).order_by(PlexUser.watched_time.desc())
        results = session.execute(stmt).fetchall()
        return [
            (
                int(r[0]),
                int(r[1]) if r[1] is not None else None,
                str(r[2] or ""),
                float(r[3] or 0),
                bool(r[4]) if r[4] is not None else False,
            )
            for r in results
        ]


def get_emby_watched_time_rank() -> list[
    tuple[str, str, float, bool | None, int | None]
]:
    """获取 Emby 观看时长排行"""
    with get_session() as session:
        stmt = select(
            EmbyUser.emby_id,
            EmbyUser.emby_username,
            EmbyUser.emby_watched_time,
            EmbyUser.is_premium,
            EmbyUser.tg_id,
        ).order_by(EmbyUser.emby_watched_time.desc())
        results = session.execute(stmt).fetchall()
        return [
            (
                str(r[0]),
                str(r[1] or ""),
                float(r[2] or 0),
                bool(r[3]) if r[3] is not None else False,
                int(r[4]) if r[4] is not None else None,
            )
            for r in results
        ]


def get_wheel_credits_rank() -> list[tuple[int, float, int]]:
    """获取幸运大转盘积分变动排行榜（统计所有游戏结果）"""
    with get_session() as session:
        total_credits_change = func.sum(WheelStats.credits_change).label(
            "total_credits_change"
        )
        play_count = func.count(WheelStats.id).label("play_count")
        stmt = (
            select(WheelStats.tg_id, total_credits_change, play_count)
            .group_by(WheelStats.tg_id)
            .order_by(total_credits_change.desc())
        )
        results = session.execute(stmt).fetchall()
        return [(int(r[0]), float(r[1] or 0), int(r[2] or 0)) for r in results]


def get_badge_rank() -> list[dict]:
    """
    获取勋章排行榜数据（按用户拥有的勋章数量排序）

    Returns:
        用户勋章排行数据列表，包含 tg_id, badge_count, badges 信息
    """
    with get_session() as session:
        stmt = (
            select(
                UserBadge.tg_id,
                func.count(UserBadge.id).label("badge_count"),
            )
            .where(UserBadge.is_active == 1)
            .group_by(UserBadge.tg_id)
            .order_by(func.count(UserBadge.id).desc())
        )
        results = session.execute(stmt).fetchall()

        rank_data = []
        for row in results:
            tg_id = int(row[0])
            badge_count = int(row[1])

            badges_stmt = (
                select(UserBadge)
                .options(joinedload(UserBadge.badge))
                .where(UserBadge.tg_id == tg_id, UserBadge.is_active == 1)
                .order_by(UserBadge.redeemed_at.desc())
            )
            user_badges = session.execute(badges_stmt).scalars().unique().all()

            rank_data.append(
                {
                    "tg_id": tg_id,
                    "badge_count": badge_count,
                    "badges": [_rank_user_badge(ub) for ub in user_badges],
                }
            )

        return rank_data


__all__ = [
    "get_badge_rank",
    "get_credits_rank",
    "get_donation_rank",
    "get_emby_watched_time_rank",
    "get_plex_watched_time_rank",
    "get_wheel_credits_rank",
]
