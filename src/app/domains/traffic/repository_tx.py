"""Caller-owned traffic database operations.

Functions in this module never create, commit, rollback, or close a session.
The public wrappers in :mod:`traffic.repository` provide the complete-session
APIs used by services and legacy compatibility callers.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, select, update

from app.core.config import settings
from app.core.log import logger
from app.domains.identity.models import EmbyUser, PlexUser
from app.domains.traffic.models import LineTrafficMonthlyStats, LineTrafficStats
from app.domains.traffic.rules import normalize_line_domain


def create_line_traffic_entry_tx(
    session,
    *,
    line: str,
    send_bytes: int,
    service: str,
    username: str,
    user_id: str | None,
    timestamp: str,
    event_hash: str,
    request_uri: str | None = None,
    upstream: str | None = None,
    upstream_response_time: str | None = None,
) -> tuple[bool, bool]:
    """Insert one event in the caller's transaction."""
    existing = session.execute(
        select(LineTrafficStats.id).where(LineTrafficStats.event_hash == event_hash)
    ).scalar_one_or_none()
    if existing is not None:
        return False, True
    session.add(
        LineTrafficStats(
            line=line,
            send_bytes=send_bytes,
            service=service,
            username=username,
            user_id=user_id,
            timestamp=timestamp,
            event_hash=event_hash,
            request_uri=request_uri,
            upstream=upstream,
            upstream_response_time=upstream_response_time,
        )
    )
    return True, False


def bulk_create_line_traffic_entries_tx(
    session,
    rows: list[dict],
    *,
    query_chunk: int = 500,
    insert_chunk: int = 500,
) -> dict[str, str]:
    """Insert a batch, retaining per-chunk retry/rollback semantics."""
    if not rows:
        return {}
    unique: dict[str, dict] = {}
    for row in rows:
        unique.setdefault(row["event_hash"], row)
    result = {event_hash: "failed" for event_hash in unique}
    hashes = list(unique)
    existing: set[str] = set()
    for index in range(0, len(hashes), query_chunk):
        existing.update(
            session.execute(
                select(LineTrafficStats.event_hash).where(
                    LineTrafficStats.event_hash.in_(hashes[index : index + query_chunk])
                )
            ).scalars()
        )
    for event_hash in existing:
        result[event_hash] = "duplicate"

    pending_by_service: dict[str, list[dict]] = {}
    for event_hash in hashes:
        if event_hash not in existing:
            row = unique[event_hash]
            pending_by_service.setdefault(row["service"], []).append(row)

    for service_rows in pending_by_service.values():
        for index in range(0, len(service_rows), insert_chunk):
            chunk = service_rows[index : index + insert_chunk]
            savepoint = session.begin_nested()
            try:
                session.add_all(LineTrafficStats(**row) for row in chunk)
                session.flush()
                savepoint.commit()
                for row in chunk:
                    result[row["event_hash"]] = "inserted"
            except Exception as error:
                savepoint.rollback()
                logger.error(
                    "批量插入流量日志失败，本块 %s 条将重试: %s", len(chunk), error
                )
    return result


def _month_bounds(target_month: str) -> tuple[str, str]:
    month_start = datetime.strptime(f"{target_month}-01", "%Y-%m-%d").replace(
        tzinfo=settings.TZ
    )
    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)
    return month_start.isoformat(), next_month.isoformat()


def aggregate_monthly_traffic_data_tx(
    session, target_month: str | None = None
) -> tuple[bool, str]:
    """Aggregate raw events into monthly rows in the caller's transaction."""
    if target_month is None:
        now = datetime.now(settings.TZ)
        if now.day != 1:
            return False, "只能在每月1号自动处理上个月数据"
        target_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    try:
        datetime.strptime(f"{target_month} +0000", "%Y-%m %z")
    except ValueError:
        return False, f"月份格式错误: {target_month}，应为 YYYY-MM 格式"

    month_start, next_month = _month_bounds(target_month)
    rows = session.execute(
        select(
            LineTrafficStats.line,
            LineTrafficStats.service,
            LineTrafficStats.username,
            LineTrafficStats.user_id,
            func.sum(LineTrafficStats.send_bytes).label("total_bytes"),
        )
        .where(
            LineTrafficStats.timestamp >= month_start,
            LineTrafficStats.timestamp < next_month,
        )
        .group_by(
            LineTrafficStats.line,
            LineTrafficStats.service,
            LineTrafficStats.username,
            LineTrafficStats.user_id,
        )
        .having(func.sum(LineTrafficStats.send_bytes) > 0)
        .order_by(func.sum(LineTrafficStats.send_bytes).desc())
    ).all()
    if not rows:
        return False, f"月份 {target_month} 没有找到需要聚合的数据"

    inserted = updated = skipped = 0
    current_time = datetime.now(settings.TZ).isoformat()
    for line, service, username, user_id, total_bytes in rows:
        savepoint = session.begin_nested()
        try:
            existing = session.execute(
                select(LineTrafficMonthlyStats).where(
                    LineTrafficMonthlyStats.line == line,
                    LineTrafficMonthlyStats.service == service,
                    LineTrafficMonthlyStats.username == username,
                    LineTrafficMonthlyStats.year_month == target_month,
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    LineTrafficMonthlyStats(
                        line=line,
                        service=service,
                        username=username,
                        user_id=user_id,
                        year_month=target_month,
                        total_bytes=total_bytes,
                        created_at=current_time,
                    )
                )
                inserted += 1
            elif existing.total_bytes != total_bytes:
                existing.total_bytes = total_bytes
                existing.created_at = current_time
                updated += 1
            else:
                skipped += 1
            savepoint.commit()
        except Exception as error:
            savepoint.rollback()
            skipped += 1
            logger.warning("处理月度聚合数据失败: %s", error)
    message = (
        f"成功聚合 {target_month} 月份数据: 插入了 {inserted} 条新记录，"
        f"更新了 {updated} 条记录，跳过了 {skipped} 条重复记录"
    )
    return True, message


def cleanup_monthly_traffic_data_tx(session, target_month: str) -> tuple[bool, str]:
    """Delete raw events after a successful monthly aggregation."""
    try:
        datetime.strptime(f"{target_month} +0000", "%Y-%m %z")
    except ValueError:
        return False, f"月份格式错误: {target_month}，应为 YYYY-MM 格式"
    monthly_count = session.execute(
        select(func.count(LineTrafficMonthlyStats.id)).where(
            LineTrafficMonthlyStats.year_month == target_month
        )
    ).scalar_one()
    if monthly_count == 0:
        return False, f"月份 {target_month} 的聚合数据不存在，不能清理原始数据"
    month_start, next_month = _month_bounds(target_month)
    count = session.execute(
        select(func.count(LineTrafficStats.id)).where(
            LineTrafficStats.timestamp >= month_start,
            LineTrafficStats.timestamp < next_month,
        )
    ).scalar_one()
    if count == 0:
        return True, f"月份 {target_month} 没有需要清理的原始数据"
    session.execute(
        delete(LineTrafficStats).where(
            LineTrafficStats.timestamp >= month_start,
            LineTrafficStats.timestamp < next_month,
        )
    )
    return True, f"成功清理 {target_month} 月份的 {count} 条原始流量数据"


def update_traffic_username_tx(session, old_username: str, new_username: str) -> bool:
    """Rename raw rows and merge colliding monthly rows."""
    if not old_username or not new_username:
        return False
    session.execute(
        update(LineTrafficStats)
        .where(func.lower(LineTrafficStats.username) == old_username.lower())
        .values(username=new_username)
    )
    records = session.execute(
        select(LineTrafficMonthlyStats).where(
            func.lower(LineTrafficMonthlyStats.username) == old_username.lower(),
            LineTrafficMonthlyStats.username != new_username,
        )
    ).scalars()
    for record in records:
        existing = session.execute(
            select(LineTrafficMonthlyStats).where(
                LineTrafficMonthlyStats.line == record.line,
                LineTrafficMonthlyStats.service == record.service,
                LineTrafficMonthlyStats.username == new_username,
                LineTrafficMonthlyStats.year_month == record.year_month,
                LineTrafficMonthlyStats.id != record.id,
            )
        ).scalar_one_or_none()
        if existing:
            existing.total_bytes += record.total_bytes
            if not existing.user_id and record.user_id:
                existing.user_id = record.user_id
            session.delete(record)
        else:
            record.username = new_username
    return True


def get_user_daily_traffic_tx(
    session,
    *,
    username: str | None = None,
    user_id: str | None = None,
    service: str | None = None,
    date: datetime | None = None,
    premium_only: bool = False,
    premium_lines: list[str] | None = None,
) -> int:
    if not username and not user_id:
        return 0
    current = date or datetime.now(settings.TZ)
    current = (
        current.replace(tzinfo=settings.TZ)
        if current.tzinfo is None
        else current.astimezone(settings.TZ)
    )
    start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    end = current.replace(hour=23, minute=59, second=59, microsecond=999999)
    conditions = [
        (LineTrafficStats.user_id == user_id)
        if user_id
        else func.lower(LineTrafficStats.username) == username.lower(),
        LineTrafficStats.service == service,
        LineTrafficStats.timestamp >= start.isoformat(),
        LineTrafficStats.timestamp <= end.isoformat(),
    ]
    if premium_only:
        if not premium_lines:
            return 0
        conditions.append(LineTrafficStats.line.in_(premium_lines))
    return int(
        session.execute(
            select(func.coalesce(func.sum(LineTrafficStats.send_bytes), 0)).where(
                *conditions
            )
        ).scalar()
        or 0
    )


def _rank_tx(session, service: str, user_model, username_column, start_date, end_date):
    now = datetime.now(settings.TZ)
    start_date = start_date or now.replace(hour=0, minute=0, second=0, microsecond=0)
    if start_date is not None:
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start_date = max(start_date, month_start)
    end_date = end_date or now.replace(
        hour=23, minute=59, second=59, microsecond=999999
    )
    end_date = min(
        end_date, now.replace(hour=23, minute=59, second=59, microsecond=999999)
    )
    statement = (
        select(
            username_column,
            LineTrafficStats.user_id,
            func.sum(LineTrafficStats.send_bytes).label("total_traffic"),
            func.coalesce(user_model.is_premium, 0).label("is_premium"),
            user_model.tg_id,
        )
        .select_from(LineTrafficStats)
        .outerjoin(
            user_model,
            func.lower(LineTrafficStats.username) == func.lower(username_column),
        )
        .where(
            LineTrafficStats.service == service,
            LineTrafficStats.timestamp >= start_date.isoformat(),
            LineTrafficStats.timestamp <= end_date.isoformat(),
            LineTrafficStats.username.isnot(None),
            LineTrafficStats.username != "",
        )
        .group_by(
            func.lower(LineTrafficStats.username),
            LineTrafficStats.user_id,
            user_model.is_premium,
            user_model.tg_id,
            username_column,
        )
        .order_by(func.sum(LineTrafficStats.send_bytes).desc())
        .limit(50)
    )
    return [tuple(row) for row in session.execute(statement).all()]


def get_plex_traffic_rank_tx(session, start_date=None, end_date=None) -> list:
    return _rank_tx(
        session, "plex", PlexUser, PlexUser.plex_username, start_date, end_date
    )


def get_emby_traffic_rank_tx(session, start_date=None, end_date=None) -> list:
    return _rank_tx(
        session, "emby", EmbyUser, EmbyUser.emby_username, start_date, end_date
    )


def get_premium_line_traffic_statistics_tx(
    session, premium_lines: list[str], *, now: datetime | None = None
) -> list[dict]:
    current = now or datetime.now(settings.TZ)
    today = current.replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=current.weekday())
    month = today.replace(day=1)
    output = []
    for line in premium_lines:

        def total(since: datetime, line_name: str = line) -> int:
            return int(
                session.execute(
                    select(
                        func.coalesce(func.sum(LineTrafficStats.send_bytes), 0)
                    ).where(
                        LineTrafficStats.line == line_name,
                        LineTrafficStats.timestamp >= since.isoformat(),
                    )
                ).scalar()
                or 0
            )

        top = session.execute(
            select(
                LineTrafficStats.username,
                func.sum(LineTrafficStats.send_bytes).label("total_traffic"),
            )
            .where(
                LineTrafficStats.line == line,
                LineTrafficStats.timestamp >= today.isoformat(),
            )
            .group_by(LineTrafficStats.username)
            .order_by(func.sum(LineTrafficStats.send_bytes).desc())
            .limit(5)
        ).all()
        output.append(
            {
                "line": line,
                "today_traffic": total(today),
                "week_traffic": total(week),
                "month_traffic": total(month),
                "top_users": [
                    {"username": name, "traffic": value} for name, value in top
                ],
            }
        )
    return output


def get_line_monthly_traffic_tx(
    session,
    line_domain: str,
    year_month: str,
    owner_tg_id: int | None = None,
    from_raw_table: bool = False,
    owner_usernames: set[str] | None = None,
) -> float:
    normalized = normalize_line_domain(line_domain)
    owner_usernames = set(owner_usernames or ())
    if owner_tg_id is not None and not owner_usernames:
        plex_user = session.execute(
            select(PlexUser.plex_username).where(PlexUser.tg_id == owner_tg_id)
        ).scalar()
        if plex_user:
            owner_usernames.add(plex_user.lower())
        emby_user = session.execute(
            select(EmbyUser.emby_username).where(EmbyUser.tg_id == owner_tg_id)
        ).scalar()
        if emby_user:
            owner_usernames.add(emby_user.lower())
    month_start, next_month = _month_bounds(year_month)
    model = LineTrafficStats if from_raw_table else LineTrafficMonthlyStats
    time_conditions = (
        [model.timestamp >= month_start, model.timestamp < next_month]
        if from_raw_table
        else [model.year_month == year_month]
    )
    conditions = [model.line == normalized, *time_conditions]
    if owner_usernames:
        conditions.append(func.lower(model.username).not_in(list(owner_usernames)))
    value = (
        session.execute(
            select(
                func.sum(model.send_bytes if from_raw_table else model.total_bytes)
            ).where(and_(*conditions))
        ).scalar()
        or 0
    )
    return float(value) / (1024**3)


__all__ = [name for name in globals() if name.endswith("_tx")]
