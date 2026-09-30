"""Read-only database queries for reports and system statistics.

This module is strictly read-only: no writes, no mutations, and no ORM model
instantiations. Queries are limited to wide-table counts/aggregations and
traffic statistics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.core.db import get_session
from app.domains.identity.models import EmbyUser, PlexUser
from app.domains.traffic.models import LineTrafficStats

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def get_plex_users_num_tx(session: Session) -> int:
    """Get total count of Plex users."""
    stmt = select(func.count(PlexUser.plex_id))
    return int(session.execute(stmt).scalar() or 0)


def get_plex_users_num() -> int:
    """Get total count of Plex users in a standalone read session."""
    with get_session() as session:
        return get_plex_users_num_tx(session)


def get_emby_users_num_tx(session: Session) -> int:
    """Get total count of Emby users."""
    stmt = select(func.count(EmbyUser.emby_username))
    return int(session.execute(stmt).scalar() or 0)


def get_emby_users_num() -> int:
    """Get total count of Emby users in a standalone read session."""
    with get_session() as session:
        return get_emby_users_num_tx(session)


def get_total_users_num_tx(session: Session) -> int:
    """Get total deduplicated user count across Plex and Emby accounts.

    1. Counts unique non-null tg_ids across PlexUser and EmbyUser.
    2. Adds accounts where tg_id is NULL for Plex and Emby separately.
    """
    plex_tg_ids = select(PlexUser.tg_id).where(PlexUser.tg_id.isnot(None))
    emby_tg_ids = select(EmbyUser.tg_id).where(EmbyUser.tg_id.isnot(None))
    union_query = plex_tg_ids.union(emby_tg_ids)
    union_subquery = union_query.subquery()
    unique_tg_count = (
        session.execute(select(func.count()).select_from(union_subquery)).scalar() or 0
    )

    plex_no_tg = (
        session.execute(
            select(func.count()).select_from(PlexUser).where(PlexUser.tg_id.is_(None))
        ).scalar()
        or 0
    )

    emby_no_tg = (
        session.execute(
            select(func.count()).select_from(EmbyUser).where(EmbyUser.tg_id.is_(None))
        ).scalar()
        or 0
    )

    return int(unique_tg_count + plex_no_tg + emby_no_tg)


def get_total_users_num() -> int:
    """Get total deduplicated user count across Plex and Emby in a standalone read session."""
    with get_session() as session:
        return get_total_users_num_tx(session)


def get_nsfw_unlocked_users_num_tx(session: Session) -> int:
    """Get total count of NSFW-unlocked users across Plex and Emby."""
    plex_stmt = select(func.count(PlexUser.id)).where(PlexUser.all_lib == 1)
    plex_count = session.execute(plex_stmt).scalar() or 0

    emby_stmt = select(func.count(EmbyUser.emby_username)).where(
        EmbyUser.emby_is_unlock == 1
    )
    emby_count = session.execute(emby_stmt).scalar() or 0

    return int(plex_count + emby_count)


def get_nsfw_unlocked_users_num() -> int:
    """Get total count of NSFW-unlocked users in a standalone read session."""
    with get_session() as session:
        return get_nsfw_unlocked_users_num_tx(session)


def get_line_schedule_unlocked_users_num_tx(session: Session) -> int:
    """Get total count of line schedule unlocked users across Plex and Emby."""
    plex_stmt = select(func.count(PlexUser.id)).where(
        PlexUser.line_schedule_unlocked == 1
    )
    plex_count = session.execute(plex_stmt).scalar() or 0

    emby_stmt = select(func.count(EmbyUser.emby_username)).where(
        EmbyUser.line_schedule_unlocked == 1
    )
    emby_count = session.execute(emby_stmt).scalar() or 0

    return int(plex_count + emby_count)


def get_line_schedule_unlocked_users_num() -> int:
    """Get total count of line schedule unlocked users in a standalone read session."""
    with get_session() as session:
        return get_line_schedule_unlocked_users_num_tx(session)


def get_download_unlocked_users_num_tx(session: Session) -> int:
    """Get total count of download unlocked users across Plex and Emby."""
    plex_stmt = select(func.count(PlexUser.id)).where(PlexUser.sync_unlocked == 1)
    plex_count = session.execute(plex_stmt).scalar() or 0

    emby_stmt = select(func.count(EmbyUser.emby_username)).where(
        EmbyUser.download_unlocked == 1
    )
    emby_count = session.execute(emby_stmt).scalar() or 0

    return int(plex_count + emby_count)


def get_download_unlocked_users_num() -> int:
    """Get total count of download unlocked users in a standalone read session."""
    with get_session() as session:
        return get_download_unlocked_users_num_tx(session)


def get_traffic_period_metrics_tx(
    session: Session, start_time: str
) -> tuple[int, list[tuple[str, int]], list[tuple[str, int]]]:
    """Query raw traffic stats for a single period starting at start_time.

    Returns:
        (total_traffic, service_results, line_results)
    """
    total_stmt = select(func.coalesce(func.sum(LineTrafficStats.send_bytes), 0)).where(
        LineTrafficStats.timestamp >= start_time
    )
    total_traffic = int(session.execute(total_stmt).scalar() or 0)

    service_stmt = (
        select(
            LineTrafficStats.service,
            func.coalesce(func.sum(LineTrafficStats.send_bytes), 0).label(
                "total_traffic"
            ),
        )
        .where(LineTrafficStats.timestamp >= start_time)
        .group_by(LineTrafficStats.service)
    )
    service_results = [
        (str(row[0]), int(row[1])) for row in session.execute(service_stmt).fetchall()
    ]

    line_stmt = (
        select(
            LineTrafficStats.line,
            func.coalesce(func.sum(LineTrafficStats.send_bytes), 0).label(
                "total_traffic"
            ),
        )
        .where(LineTrafficStats.timestamp >= start_time)
        .group_by(LineTrafficStats.line)
        .order_by(func.sum(LineTrafficStats.send_bytes).desc())
    )
    line_results = [
        (str(row[0]), int(row[1])) for row in session.execute(line_stmt).fetchall()
    ]

    return total_traffic, service_results, line_results


def get_raw_traffic_stats(
    periods: list[tuple[str, str]],
) -> dict[str, tuple[int, list[tuple[str, int]], list[tuple[str, int]]]]:
    """Query raw traffic statistics for multiple periods in a single session."""
    result: dict[str, tuple[int, list[tuple[str, int]], list[tuple[str, int]]]] = {}
    with get_session() as session:
        for period_name, start_time in periods:
            result[period_name] = get_traffic_period_metrics_tx(session, start_time)
    return result


__all__ = [
    "get_download_unlocked_users_num",
    "get_download_unlocked_users_num_tx",
    "get_emby_users_num",
    "get_emby_users_num_tx",
    "get_line_schedule_unlocked_users_num",
    "get_line_schedule_unlocked_users_num_tx",
    "get_nsfw_unlocked_users_num",
    "get_nsfw_unlocked_users_num_tx",
    "get_plex_users_num",
    "get_plex_users_num_tx",
    "get_raw_traffic_stats",
    "get_total_users_num",
    "get_total_users_num_tx",
    "get_traffic_period_metrics_tx",
]
