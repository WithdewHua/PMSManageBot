import time
from datetime import datetime

from sqlalchemy import func, or_, select, update

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.credits import repository as credits_repository
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import EmbyUser, PlexUser
from app.domains.identity.types import TgIdReassignIssue
from app.domains.lines.models import LineSchedule
from app.domains.lines.repository.lines import set_emby_line_tx, set_plex_line_tx


def check_schedule_conflict(
    tg_id: int,
    service: str,
    days_of_week: list[int],
    start_time: str,
    end_time: str,
    exclude_id: int | None = None,
) -> bool:
    """
    检查时间段是否冲突

    Args:
        tg_id: 用户的 Telegram ID
        service: 服务类型
        days_of_week: 星期几列表
        start_time: 开始时间 HH:MM
        end_time: 结束时间 HH:MM
        exclude_id: 要排除的调度 ID（用于更新时）

    Returns:
        是否存在冲突
    """
    try:
        schedules = get_user_line_schedules(tg_id, service, enabled_only=True)

        # 转换时间为分钟数便于比较
        def time_to_minutes(t: str) -> int:
            h, m = map(int, t.split(":"))
            return h * 60 + m

        new_start = time_to_minutes(start_time)
        new_end = time_to_minutes(end_time)

        # 处理跨天的情况
        if new_end <= new_start:
            new_end += 24 * 60

        new_days_set = set(days_of_week)

        for schedule in schedules:
            # 排除指定的调度
            if exclude_id and schedule["id"] == exclude_id:
                continue

            # 检查星期几是否有交集
            schedule_days_set = set(schedule["days_of_week"])
            if not new_days_set & schedule_days_set:
                continue

            # 检查时间段是否重叠
            sched_start = time_to_minutes(schedule["start_time"])
            sched_end = time_to_minutes(schedule["end_time"])

            # 处理跨天
            if sched_end <= sched_start:
                sched_end += 24 * 60

            # 检查是否重叠
            if not (new_end <= sched_start or new_start >= sched_end):
                logger.info(
                    f"发现时间冲突: 新调度 {start_time}-{end_time} 与 "
                    f"调度 {schedule['id']} {schedule['start_time']}-{schedule['end_time']} 冲突"
                )
                return True

        return False

    except Exception as e:
        logger.error(f"检查时间冲突失败: {e}")
        return True  # 出错时保守处理，返回冲突


def disable_schedules_by_line(
    line_name: str, only_non_premium: bool = False
) -> tuple[bool, int, list[dict]]:
    """
    禁用指定线路的所有调度，并返回受影响的用户信息

    Args:
        line_name: 线路名称
        only_non_premium: 是否只禁用非 premium 用户的调度

    Returns:
        (是否成功, 禁用的调度数量, 受影响的用户列表)
        用户列表格式: [{"tg_id": int, "service": str, "schedule_count": int}, ...]
    """
    try:
        with get_session() as session:
            # 查找所有使用该线路且已启用的调度
            stmt = select(LineSchedule).where(
                LineSchedule.line == line_name, LineSchedule.is_enabled == 1
            )
            schedules = session.execute(stmt).scalars().all()

            if not schedules:
                logger.info(f"没有找到使用线路 {line_name} 的已启用调度")
                return True, 0, []

            # 如果需要过滤 premium 用户，先查询用户的 premium 状态
            premium_users = set()
            if only_non_premium:
                # 获取所有相关用户的 tg_id
                tg_ids = list({schedule.tg_id for schedule in schedules})

                # 查询 Plex 用户的 premium 状态
                plex_stmt = select(PlexUser.tg_id).where(
                    PlexUser.tg_id.in_(tg_ids), PlexUser.is_premium == 1
                )
                plex_premium = session.execute(plex_stmt).scalars().all()
                premium_users.update(plex_premium)

                # 查询 Emby 用户的 premium 状态
                emby_stmt = select(EmbyUser.tg_id).where(
                    EmbyUser.tg_id.in_(tg_ids), EmbyUser.is_premium == 1
                )
                emby_premium = session.execute(emby_stmt).scalars().all()
                premium_users.update(emby_premium)

            # 统计受影响的用户（在禁用前）
            user_service_map = {}
            schedules_to_disable = []
            for schedule in schedules:
                # 如果只禁用非 premium 用户，跳过 premium 用户
                if only_non_premium and schedule.tg_id in premium_users:
                    continue

                schedules_to_disable.append(schedule)
                key = (schedule.tg_id, schedule.service)
                if key not in user_service_map:
                    user_service_map[key] = {
                        "tg_id": schedule.tg_id,
                        "service": schedule.service,
                        "schedule_count": 0,
                    }
                user_service_map[key]["schedule_count"] += 1

            if not schedules_to_disable:
                logger.info(f"没有需要禁用的调度（线路: {line_name}）")
                return True, 0, []

            # 禁用所有调度
            count = 0
            current_time = int(time.time())
            for schedule in schedules_to_disable:
                schedule.is_enabled = 0
                schedule.updated_at = current_time
                count += 1

            affected_users = list(user_service_map.values())
            logger.info(
                f"已禁用 {count} 个使用线路 {line_name} 的调度，"
                f"影响 {len(affected_users)} 位用户"
                + (" (仅非 premium 用户)" if only_non_premium else "")
            )
            return True, count, affected_users

    except Exception as e:
        logger.error(f"禁用线路 {line_name} 的调度失败: {e}")
        return False, 0, []


def get_users_with_line_schedule(line_name: str) -> list[dict]:
    """
    获取所有使用指定线路调度的用户信息

    Args:
        line_name: 线路名称

    Returns:
        用户信息列表 [{"tg_id": int, "service": str, "schedule_count": int}, ...]
    """
    try:
        with get_session() as session:
            # 查找所有使用该线路且已启用的调度
            stmt = select(LineSchedule).where(
                LineSchedule.line == line_name, LineSchedule.is_enabled == 1
            )
            schedules = session.execute(stmt).scalars().all()

            # 按用户和服务分组统计
            user_service_map = {}
            for schedule in schedules:
                key = (schedule.tg_id, schedule.service)
                if key not in user_service_map:
                    user_service_map[key] = {
                        "tg_id": schedule.tg_id,
                        "service": schedule.service,
                        "schedule_count": 0,
                    }
                user_service_map[key]["schedule_count"] += 1

            return list(user_service_map.values())

    except Exception as e:
        logger.error(f"获取使用线路 {line_name} 的用户失败: {e}")
        return []


# Schedule workflows below are module-level helpers. The legacy class above remains
# available until the broader lines repository migration removes the facade.


def _schedule_dict(schedule: LineSchedule) -> dict:
    return {
        "id": int(schedule.id),
        "service": schedule.service,
        "line": schedule.line,
        "days_of_week": [int(day) for day in schedule.days_of_week.split(",")]
        if schedule.days_of_week
        else [],
        "start_time": schedule.start_time,
        "end_time": schedule.end_time,
        "priority": int(schedule.priority),
        "is_enabled": schedule.is_enabled == 1,
        "created_at": int(schedule.created_at),
        "updated_at": int(schedule.updated_at),
    }


def _schedule_model(service: str):
    if service == "plex":
        return PlexUser
    if service == "emby":
        return EmbyUser
    raise ValueError(f"不支持的服务类型: {service}")


def _line_schedule_account_tx(session, tg_id: int, service: str):
    model = _schedule_model(service)
    return session.execute(
        select(model).where(model.tg_id == int(tg_id))
    ).scalar_one_or_none()


def get_line_schedule_account(tg_id: int, service: str) -> dict | None:
    """Read the bound media account needed by schedule endpoints."""
    with get_session() as session:
        account = _line_schedule_account_tx(session, tg_id, service)
        if account is None:
            return None
        username = getattr(account, f"{service}_username")
        return {"is_premium": account.is_premium == 1, "username": username}


def check_line_schedule_unlock(tg_id: int, service: str) -> dict:
    """Return the legacy unlock response without exposing a session to callers."""
    try:
        with get_session() as session:
            account = _line_schedule_account_tx(session, tg_id, service)
            if account is None:
                return {
                    "is_unlocked": False,
                    "is_premium": False,
                    "unlock_time": None,
                }

            is_premium = account.is_premium == 1
            if is_premium and account.premium_expiry_time:
                is_premium = datetime.fromisoformat(
                    account.premium_expiry_time
                ) > datetime.now(settings.TZ)
            unlock_time = (
                account.line_schedule_unlock_time
                if account.line_schedule_unlocked == 1
                else None
            )
            return {
                "is_unlocked": is_premium or unlock_time is not None,
                "is_premium": is_premium,
                "unlock_time": unlock_time,
            }
    except Exception as error:
        logger.error(f"检查用户 {tg_id!s} 的 {service} 线路调度解锁状态失败: {error}")
        return {"is_unlocked": False, "is_premium": False, "unlock_time": None}


def get_user_line_schedules(
    tg_id: int, service: str | None = None, enabled_only: bool = False
) -> list[dict]:
    """Read schedules and return the public response shape."""
    try:
        with get_session() as session:
            statement = select(LineSchedule).where(LineSchedule.tg_id == int(tg_id))
            if service is not None:
                statement = statement.where(LineSchedule.service == service)
            if enabled_only:
                statement = statement.where(LineSchedule.is_enabled == 1)
            schedules = session.execute(
                statement.order_by(
                    LineSchedule.priority,
                    LineSchedule.created_at,
                    LineSchedule.id,
                )
            ).scalars()
            return [_schedule_dict(schedule) for schedule in schedules]
    except Exception as error:
        logger.error(f"获取用户 {tg_id} 的线路调度列表失败: {error}")
        return []


def list_line_cache_rows() -> tuple[list[tuple], list[tuple]]:
    """Read gateway cache rows before the service writes Redis."""
    with get_session() as session:
        plex_users = session.execute(
            select(PlexUser.plex_id, PlexUser.plex_username, PlexUser.plex_line)
        ).all()
        emby_users = session.execute(
            select(EmbyUser.emby_username, EmbyUser.emby_line)
        ).all()
    return plex_users, emby_users


def get_auto_switch_candidates(
    tg_id: int | None = None, service: str | None = None
) -> list[dict]:
    """Read eligible users before opening per-user mutation transactions."""
    if service not in (None, "plex", "emby"):
        raise ValueError(f"不支持的服务类型: {service}")

    with get_session() as session:
        candidates: list[dict] = []
        if service in (None, "plex"):
            statement = (
                select(PlexUser.tg_id, PlexUser.plex_line, PlexUser.plex_username)
                .where(
                    PlexUser.tg_id.is_not(None),
                    or_(
                        PlexUser.line_schedule_unlocked == 1,
                        PlexUser.is_premium == 1,
                    ),
                )
                .order_by(PlexUser.tg_id)
            )
            if tg_id is not None:
                statement = statement.where(PlexUser.tg_id == int(tg_id))
            candidates.extend(
                {
                    "tg_id": row.tg_id,
                    "service": "plex",
                    "line": row.plex_line,
                    "username": row.plex_username,
                }
                for row in session.execute(statement)
            )
        if service in (None, "emby"):
            statement = (
                select(EmbyUser.tg_id, EmbyUser.emby_line, EmbyUser.emby_username)
                .where(
                    EmbyUser.tg_id.is_not(None),
                    or_(
                        EmbyUser.line_schedule_unlocked == 1,
                        EmbyUser.is_premium == 1,
                    ),
                )
                .order_by(EmbyUser.tg_id, EmbyUser.emby_username)
            )
            if tg_id is not None:
                statement = statement.where(EmbyUser.tg_id == int(tg_id))
            candidates.extend(
                {
                    "tg_id": row.tg_id,
                    "service": "emby",
                    "line": row.emby_line,
                    "username": row.emby_username,
                }
                for row in session.execute(statement)
            )
        return candidates


def get_current_active_schedule_tx(
    session, tg_id: int, service: str, *, now: datetime | None = None
) -> dict | None:
    """Select one active schedule deterministically inside the caller transaction."""
    current = now or datetime.now(settings.TZ)
    current_day = current.weekday()
    current_minutes = current.hour * 60 + current.minute
    schedules = session.execute(
        select(LineSchedule)
        .where(
            LineSchedule.tg_id == int(tg_id),
            LineSchedule.service == service,
            LineSchedule.is_enabled == 1,
        )
        .order_by(LineSchedule.priority, LineSchedule.created_at, LineSchedule.id)
    ).scalars()

    for schedule in schedules:
        days = {int(day) for day in schedule.days_of_week.split(",") if day != ""}
        start_hour, start_minute = map(int, schedule.start_time.split(":"))
        end_hour, end_minute = map(int, schedule.end_time.split(":"))
        start = start_hour * 60 + start_minute
        end = end_hour * 60 + end_minute

        if start == end:
            active = current_day in days
        elif end < start:
            active = (current_day in days and current_minutes >= start) or (
                (current_day - 1) % 7 in days and current_minutes < end
            )
        else:
            active = current_day in days and start <= current_minutes < end

        if active:
            return _schedule_dict(schedule)
    return None


def apply_active_schedule_tx(session, tg_id: int, service: str) -> dict | None:
    """Read and persist one user's active schedule in the caller transaction."""
    model = _schedule_model(service)
    account = session.execute(
        select(model).where(model.tg_id == int(tg_id)).with_for_update()
    ).scalar_one_or_none()
    if account is None:
        return None

    schedule = get_current_active_schedule_tx(session, tg_id, service)
    if schedule is None or schedule["line"] == "auto":
        return None

    line_attribute = f"{service}_line"
    old_line = getattr(account, line_attribute)
    if old_line == schedule["line"]:
        return None
    setattr(account, line_attribute, schedule["line"])
    return {
        "tg_id": int(tg_id),
        "service": service,
        "username": getattr(account, f"{service}_username"),
        "old_line": old_line,
        "line": schedule["line"],
    }


def apply_active_schedule(tg_id: int, service: str) -> dict | None:
    """Read and persist one user's active schedule in one transaction.

    A missing schedule and the literal ``auto`` are intentional no-ops. In
    particular, neither case falls back to a previous line or writes a cache.
    """
    with get_session() as session:
        return apply_active_schedule_tx(session, tg_id, service)


def create_line_schedule_tx(
    session,
    tg_id: int,
    service: str,
    line: str,
    days_of_week: list[int],
    start_time: str,
    end_time: str,
    priority: int = 0,
) -> int:
    """Create a schedule in the caller-owned transaction."""
    timestamp = int(time.time())
    schedule_id = None
    if session.bind is not None and session.bind.dialect.name == "sqlite":
        schedule_id = session.execute(
            select(func.coalesce(func.max(LineSchedule.id), 0) + 1)
        ).scalar_one()

    schedule = LineSchedule(
        id=int(schedule_id) if schedule_id is not None else None,
        tg_id=int(tg_id),
        service=service,
        line=line,
        days_of_week=",".join(map(str, sorted(days_of_week))) if days_of_week else "",
        start_time=start_time,
        end_time=end_time,
        priority=priority,
        is_enabled=1,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(schedule)
    session.flush()
    return int(schedule.id)


def create_line_schedule(
    tg_id: int,
    service: str,
    line: str,
    days_of_week: list[int],
    start_time: str,
    end_time: str,
    priority: int = 0,
) -> int | None:
    try:
        with get_session() as session:
            return create_line_schedule_tx(
                session,
                tg_id,
                service,
                line,
                days_of_week,
                start_time,
                end_time,
                priority,
            )
    except Exception as error:
        logger.error(f"创建线路调度失败: {error}")
        return None


def update_line_schedule_tx(session, schedule_id: int, tg_id: int, **kwargs) -> bool:
    """Update a schedule row in place, preserving its ID."""
    schedule = session.execute(
        select(LineSchedule).where(
            LineSchedule.id == int(schedule_id), LineSchedule.tg_id == int(tg_id)
        )
    ).scalar_one_or_none()
    if schedule is None:
        return False
    if "line" in kwargs:
        schedule.line = kwargs["line"]
    if "days_of_week" in kwargs:
        schedule.days_of_week = ",".join(map(str, sorted(kwargs["days_of_week"])))
    if "start_time" in kwargs:
        schedule.start_time = kwargs["start_time"]
    if "end_time" in kwargs:
        schedule.end_time = kwargs["end_time"]
    if "priority" in kwargs:
        schedule.priority = kwargs["priority"]
    if "is_enabled" in kwargs:
        schedule.is_enabled = 1 if kwargs["is_enabled"] else 0
    schedule.updated_at = int(time.time())
    return True


def update_line_schedule(schedule_id: int, tg_id: int, **kwargs) -> bool:
    try:
        with get_session() as session:
            return update_line_schedule_tx(session, schedule_id, tg_id, **kwargs)
    except Exception as error:
        logger.error(f"更新线路调度 {schedule_id} 失败: {error}")
        return False


def delete_line_schedule_tx(session, schedule_id: int, tg_id: int) -> bool:
    """Delete a schedule row in the caller-owned transaction."""
    schedule = session.execute(
        select(LineSchedule).where(
            LineSchedule.id == int(schedule_id), LineSchedule.tg_id == int(tg_id)
        )
    ).scalar_one_or_none()
    if schedule is None:
        return False
    session.delete(schedule)
    return True


def delete_line_schedule(schedule_id: int, tg_id: int) -> bool:
    try:
        with get_session() as session:
            return delete_line_schedule_tx(session, schedule_id, tg_id)
    except Exception as error:
        logger.error(f"删除线路调度 {schedule_id} 失败: {error}")
        return False


def get_current_active_schedule(tg_id: int, service: str) -> dict | None:
    try:
        with get_session() as session:
            return get_current_active_schedule_tx(session, tg_id, service)
    except Exception as error:
        logger.error(f"获取当前生效的调度失败: {error}")
        return None


# 线路调度解锁列属于 lines（见 docs/architecture.md 宽表列归属），礼包只调这里。
_LINE_SCHEDULE_UNLOCK_COLUMNS = {
    "plex": (PlexUser, "line_schedule_unlocked", "line_schedule_unlock_time"),
    "emby": (EmbyUser, "line_schedule_unlocked", "line_schedule_unlock_time"),
}


def lock_media_account_tx(session, tg_id: int, /, *, service: str) -> bool:
    """按固定顺序预锁已绑定的媒体账号行，返回是否锁到了行。

    预锁本身不写任何列：调用方（礼包领取）先按 statistics → plex → emby 的
    顺序把所有要写的行锁住，再按奖励配置顺序发放，各写入方的 FOR UPDATE
    只是同一把锁，因此奖励顺序不会改变加锁顺序。
    """
    if service not in _LINE_SCHEDULE_UNLOCK_COLUMNS:
        raise ValueError(f"不支持的媒体账号: {service}")
    model, _, _ = _LINE_SCHEDULE_UNLOCK_COLUMNS[service]
    return (
        session.execute(
            select(model).where(model.tg_id == int(tg_id)).with_for_update()
        ).scalar_one_or_none()
        is not None
    )


def unlock_line_schedule_tx(session, tg_id: int, service: str) -> dict:
    """在调用方事务内永久解锁线路调度，返回“已解锁”或“已跳过”。

    「已拥有」直接读永久解锁标记列，而不是把 Premium 也算作已解锁；已经永久
    解锁过的服务记为 skipped，由调用方决定怎么告知用户。
    """
    if service not in _LINE_SCHEDULE_UNLOCK_COLUMNS:
        raise ValueError(f"不支持的解锁类型: line_schedule/{service}")
    model, flag_col, time_col = _LINE_SCHEDULE_UNLOCK_COLUMNS[service]
    user = (
        session.execute(
            select(model).where(model.tg_id == int(tg_id)).with_for_update()
        )
        .scalars()
        .one_or_none()
    )
    if user is None:
        raise ValueError(f"未找到绑定的 {service.capitalize()} 账号")
    if int(getattr(user, flag_col) or 0) == 1:
        return {"unlocked": False, "skipped": "already_unlocked", "service": service}
    setattr(user, flag_col, 1)
    setattr(user, time_col, int(time.time()))
    return {"unlocked": True, "skipped": None, "service": service}


# Caller-owned transaction helpers. Repository-owned functions above retain the
# legacy return/error contracts; these helpers compose into larger workflows.
def set_line_tx(
    session,
    service: str,
    line: str | None,
    *,
    tg_id: int | None = None,
    account_id: int | str | None = None,
) -> None:
    if service == "plex":
        set_plex_line_tx(session, line, tg_id=tg_id, plex_id=account_id)
    elif service == "emby":
        set_emby_line_tx(session, line, tg_id=tg_id, emby_id=account_id)
    else:
        raise ValueError(f"未知的服务类型: {service}")


def check_line_schedule_unlock_tx(session, tg_id: int, service: str) -> dict:
    if service == "plex":
        model = PlexUser
    elif service == "emby":
        model = EmbyUser
    else:
        raise ValueError(f"未知的服务类型: {service}")
    result = session.execute(
        select(
            model.is_premium,
            model.premium_expiry_time,
            model.line_schedule_unlocked,
            model.line_schedule_unlock_time,
        ).where(model.tg_id == tg_id)
    ).fetchone()
    is_premium = False
    unlock_time = None
    if result:
        if result[0] == 1 and (
            not result[1]
            or datetime.fromisoformat(result[1]) > datetime.now(settings.TZ)
        ):
            is_premium = True
        if result[2] == 1:
            unlock_time = result[3]
    return {
        "is_unlocked": is_premium or unlock_time is not None,
        "is_premium": is_premium,
        "unlock_time": unlock_time,
    }


def unlock_line_schedule_with_credit_tx(
    session, tg_id: int, service: str, cost: float
) -> None:
    credits_repository.deduct_tx(session, CreditAccount.tg(int(tg_id)), cost)
    if service == "plex":
        model = PlexUser
    elif service == "emby":
        model = EmbyUser
    else:
        raise ValueError(f"未知的服务类型: {service}")
    result = session.execute(
        update(model)
        .where(model.tg_id == tg_id)
        .values(line_schedule_unlocked=1, line_schedule_unlock_time=int(time.time()))
    )
    if result.rowcount != 1:
        raise ValueError(f"用户未绑定 {service} 账户")


def get_user_line_schedules_tx(
    session,
    tg_id: int,
    service: str | None = None,
    enabled_only: bool = False,
) -> list[dict]:
    stmt = select(LineSchedule).where(LineSchedule.tg_id == tg_id)
    if service:
        stmt = stmt.where(LineSchedule.service == service)
    if enabled_only:
        stmt = stmt.where(LineSchedule.is_enabled == 1)
    schedules = (
        session.execute(stmt.order_by(LineSchedule.priority, LineSchedule.created_at))
        .scalars()
        .all()
    )
    return [
        {
            "id": schedule.id,
            "service": schedule.service,
            "line": schedule.line,
            "days_of_week": [int(day) for day in schedule.days_of_week.split(",")]
            if schedule.days_of_week
            else [],
            "start_time": schedule.start_time,
            "end_time": schedule.end_time,
            "priority": schedule.priority,
            "is_enabled": schedule.is_enabled == 1,
            "created_at": schedule.created_at,
            "updated_at": schedule.updated_at,
        }
        for schedule in schedules
    ]


def check_schedule_conflict_tx(
    session,
    tg_id: int,
    service: str,
    days_of_week: list[int],
    start_time: str,
    end_time: str,
    exclude_id: int | None = None,
) -> bool:
    def time_to_minutes(value: str) -> int:
        hours, minutes = map(int, value.split(":"))
        return hours * 60 + minutes

    new_start = time_to_minutes(start_time)
    new_end = time_to_minutes(end_time)
    if new_end <= new_start:
        new_end += 24 * 60
    new_days = set(days_of_week)
    for schedule in get_user_line_schedules_tx(
        session, tg_id, service, enabled_only=True
    ):
        if exclude_id and schedule["id"] == exclude_id:
            continue
        if not new_days & set(schedule["days_of_week"]):
            continue
        schedule_start = time_to_minutes(schedule["start_time"])
        schedule_end = time_to_minutes(schedule["end_time"])
        if schedule_end <= schedule_start:
            schedule_end += 24 * 60
        if not (new_end <= schedule_start or new_start >= schedule_end):
            return True
    return False


def disable_schedules_by_line_tx(
    session, line_name: str, only_non_premium: bool = False
) -> tuple[bool, int, list[dict]]:
    schedules = (
        session.execute(
            select(LineSchedule).where(
                LineSchedule.line == line_name, LineSchedule.is_enabled == 1
            )
        )
        .scalars()
        .all()
    )
    if not schedules:
        return True, 0, []
    premium_users: set[int] = set()
    if only_non_premium:
        tg_ids = list({schedule.tg_id for schedule in schedules})
        premium_users.update(
            session.execute(
                select(PlexUser.tg_id).where(
                    PlexUser.tg_id.in_(tg_ids), PlexUser.is_premium == 1
                )
            )
            .scalars()
            .all()
        )
        premium_users.update(
            session.execute(
                select(EmbyUser.tg_id).where(
                    EmbyUser.tg_id.in_(tg_ids), EmbyUser.is_premium == 1
                )
            )
            .scalars()
            .all()
        )
    affected: dict[tuple[int, str], dict] = {}
    selected = []
    for schedule in schedules:
        if only_non_premium and schedule.tg_id in premium_users:
            continue
        selected.append(schedule)
        key = (schedule.tg_id, schedule.service)
        affected.setdefault(
            key,
            {"tg_id": schedule.tg_id, "service": schedule.service, "schedule_count": 0},
        )["schedule_count"] += 1
    now = int(time.time())
    for schedule in selected:
        schedule.is_enabled = 0
        schedule.updated_at = now
    return True, len(selected), list(affected.values())


def get_users_with_line_schedule_tx(session, line_name: str) -> list[dict]:
    schedules = (
        session.execute(
            select(LineSchedule).where(
                LineSchedule.line == line_name, LineSchedule.is_enabled == 1
            )
        )
        .scalars()
        .all()
    )
    affected: dict[tuple[int, str], dict] = {}
    for schedule in schedules:
        key = (schedule.tg_id, schedule.service)
        affected.setdefault(
            key,
            {"tg_id": schedule.tg_id, "service": schedule.service, "schedule_count": 0},
        )["schedule_count"] += 1
    return list(affected.values())


def unlock_line_schedule_with_credit(tg_id: int, service: str, cost: float) -> bool:
    """Unlock line scheduling and charge the account in one transaction."""
    with get_session() as session:
        unlock_line_schedule_with_credit_tx(session, tg_id, service, cost)
        return True


REASSIGNED_TG_ID_COLUMNS: tuple[str, ...] = ("line_schedule.tg_id",)


def check_tg_id_reassign_tx(
    session, old_tg_id: int, new_tg_id: int
) -> list[TgIdReassignIssue]:
    return []


def reassign_tg_id_tx(session, old_tg_id: int, new_tg_id: int) -> dict[str, int]:
    result = session.execute(
        update(LineSchedule)
        .where(LineSchedule.tg_id == int(old_tg_id))
        .values(tg_id=int(new_tg_id))
    )
    return {"line_schedule.tg_id": max(0, int(result.rowcount or 0))}
