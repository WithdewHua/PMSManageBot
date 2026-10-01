from datetime import datetime, timedelta

from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import EmbyUser, PlexUser
from app.domains.premium.exceptions import PremiumAccountNotBound


def get_plex_premium_debt_record(plex_id: int) -> tuple | None:
    """获取 Plex 用户的 Premium 额度与欠额记录。"""
    with get_session() as session:
        return session.execute(
            select(
                PlexUser.is_premium,
                PlexUser.premium_traffic_debt_bytes,
                PlexUser.premium_traffic_debt_updated_date,
            ).where(PlexUser.plex_id == plex_id)
        ).fetchone()


def get_emby_premium_debt_record(emby_username: str) -> tuple | None:
    """获取 Emby 用户的 Premium 额度与欠额记录。"""
    with get_session() as session:
        return session.execute(
            select(
                EmbyUser.is_premium,
                EmbyUser.premium_traffic_debt_bytes,
                EmbyUser.premium_traffic_debt_updated_date,
            ).where(func.lower(EmbyUser.emby_username) == emby_username.lower())
        ).fetchone()


def get_expired_premium_users() -> list:
    """获取所有 Premium 已过期的用户"""
    expired_users = []
    current_time = datetime.now(settings.TZ).isoformat()

    with get_session() as session:
        # 检查 Plex 用户
        plex_stmt = select(
            PlexUser.tg_id,
            PlexUser.plex_username,
            PlexUser.premium_expiry_time,
            PlexUser.plex_line,
        ).where(
            PlexUser.is_premium == 1,
            PlexUser.premium_expiry_time.isnot(None),
            PlexUser.premium_expiry_time < current_time,
        )
        plex_users = session.execute(plex_stmt).fetchall()

        for user in plex_users:
            expired_users.append(
                {
                    "tg_id": user[0],
                    "username": user[1],
                    "service": "plex",
                    "expiry_time": user[2],
                    "line": user[3],
                }
            )

        # 检查 Emby 用户
        emby_stmt = select(
            EmbyUser.tg_id,
            EmbyUser.emby_username,
            EmbyUser.premium_expiry_time,
            EmbyUser.emby_line,
        ).where(
            EmbyUser.is_premium == 1,
            EmbyUser.premium_expiry_time.isnot(None),
            EmbyUser.premium_expiry_time < current_time,
        )
        emby_users = session.execute(emby_stmt).fetchall()

        for user in emby_users:
            expired_users.append(
                {
                    "tg_id": user[0],
                    "username": user[1],
                    "service": "emby",
                    "expiry_time": user[2],
                    "line": user[3],
                }
            )

    return expired_users


def update_expired_premium_status() -> int:
    """批量更新已过期的 Premium 用户状态"""
    current_time = datetime.now(settings.TZ).isoformat()
    current_timestamp = int(datetime.now(settings.TZ).timestamp())

    with get_session() as session:
        # 更新 Plex 用户
        plex_result = session.execute(
            update(PlexUser)
            .where(
                PlexUser.is_premium == 1,
                PlexUser.premium_expiry_time.isnot(None),
                PlexUser.premium_expiry_time < current_time,
            )
            .values(
                is_premium=0,
                premium_expiry_time=None,
                premium_status_updated_at=current_timestamp,
            )
        )

        # 更新 Emby 用户
        emby_result = session.execute(
            update(EmbyUser)
            .where(
                EmbyUser.is_premium == 1,
                EmbyUser.premium_expiry_time.isnot(None),
                EmbyUser.premium_expiry_time < current_time,
            )
            .values(
                is_premium=0,
                premium_expiry_time=None,
                premium_status_updated_at=current_timestamp,
            )
        )
        total_updated = plex_result.rowcount + emby_result.rowcount
        return total_updated


def get_premium_users_expiring_soon(days: int = 3) -> list:
    """获取即将过期的 Premium 用户（默认3天内）"""
    current_time = datetime.now(settings.TZ)
    warning_time = (current_time + timedelta(days=days)).isoformat()
    current_time_str = current_time.isoformat()

    expiring_users = []

    with get_session() as session:
        # 检查 Plex 用户
        plex_stmt = select(
            PlexUser.tg_id, PlexUser.plex_username, PlexUser.premium_expiry_time
        ).where(
            PlexUser.is_premium == 1,
            PlexUser.premium_expiry_time.isnot(None),
            PlexUser.premium_expiry_time > current_time_str,
            PlexUser.premium_expiry_time <= warning_time,
        )
        plex_users = session.execute(plex_stmt).fetchall()

        for user in plex_users:
            expiry_dt = datetime.fromisoformat(user[2]).astimezone(settings.TZ)
            days_remaining = (expiry_dt - current_time).days
            expiring_users.append(
                {
                    "tg_id": user[0],
                    "username": user[1],
                    "service": "plex",
                    "expiry_time": user[2],
                    "days_remaining": days_remaining,
                }
            )

        # 检查 Emby 用户
        emby_stmt = select(
            EmbyUser.tg_id, EmbyUser.emby_username, EmbyUser.premium_expiry_time
        ).where(
            EmbyUser.is_premium == 1,
            EmbyUser.premium_expiry_time.isnot(None),
            EmbyUser.premium_expiry_time > current_time_str,
            EmbyUser.premium_expiry_time <= warning_time,
        )
        emby_users = session.execute(emby_stmt).fetchall()

        for user in emby_users:
            expiry_dt = datetime.fromisoformat(user[2]).astimezone(settings.TZ)
            days_remaining = (expiry_dt - current_time).days
            expiring_users.append(
                {
                    "tg_id": user[0],
                    "username": user[1],
                    "service": "emby",
                    "expiry_time": user[2],
                    "days_remaining": days_remaining,
                }
            )

    return expiring_users


def get_premium_statistics() -> dict:
    """获取 Premium 用户统计信息"""
    try:
        current_time = datetime.now(settings.TZ).isoformat()

        with get_session() as session:
            # 总 Premium 用户数（去重）
            total_premium_users = session.execute(
                select(func.count()).select_from(
                    select(PlexUser.tg_id)
                    .where(PlexUser.is_premium == 1, PlexUser.tg_id.isnot(None))
                    .union(
                        select(EmbyUser.tg_id).where(
                            EmbyUser.is_premium == 1, EmbyUser.tg_id.isnot(None)
                        )
                    )
                    .subquery()
                )
            ).scalar()

            # 活跃 Premium 用户数（未过期的，去重）
            active_premium_users = session.execute(
                select(func.count()).select_from(
                    select(PlexUser.tg_id)
                    .where(
                        PlexUser.is_premium == 1,
                        PlexUser.tg_id.isnot(None),
                        (PlexUser.premium_expiry_time.is_(None))
                        | (PlexUser.premium_expiry_time > current_time),
                    )
                    .union(
                        select(EmbyUser.tg_id).where(
                            EmbyUser.is_premium == 1,
                            EmbyUser.tg_id.isnot(None),
                            (EmbyUser.premium_expiry_time.is_(None))
                            | (EmbyUser.premium_expiry_time > current_time),
                        )
                    )
                    .subquery()
                )
            ).scalar()

            # Premium Plex 用户数（未过期的）
            premium_plex_users = session.execute(
                select(func.count(PlexUser.id)).where(
                    PlexUser.is_premium == 1,
                    (PlexUser.premium_expiry_time.is_(None))
                    | (PlexUser.premium_expiry_time > current_time),
                )
            ).scalar()

            # Premium Emby 用户数（未过期的）
            premium_emby_users = session.execute(
                select(func.count(EmbyUser.emby_username)).where(
                    EmbyUser.is_premium == 1,
                    (EmbyUser.premium_expiry_time.is_(None))
                    | (EmbyUser.premium_expiry_time > current_time),
                )
            ).scalar()

            return {
                "total_premium_users": total_premium_users,
                "active_premium_users": active_premium_users,
                "premium_plex_users": premium_plex_users,
                "premium_emby_users": premium_emby_users,
            }

    except Exception as e:
        logger.error(f"Error getting premium statistics: {e}")
        return {
            "total_premium_users": 0,
            "active_premium_users": 0,
            "premium_plex_users": 0,
            "premium_emby_users": 0,
        }


def get_all_active_premium_users() -> list:
    """获取所有活跃的 Premium 用户及其到期时间"""
    premium_users = []
    current_time = datetime.now(settings.TZ).isoformat()

    try:
        with get_session() as session:
            # 获取 Plex Premium 用户
            plex_stmt = select(
                PlexUser.tg_id,
                PlexUser.plex_username,
                PlexUser.premium_expiry_time,
                PlexUser.plex_line,
            ).where(
                PlexUser.is_premium == 1,
                (PlexUser.premium_expiry_time.is_(None))
                | (PlexUser.premium_expiry_time > current_time),
            )
            plex_users = session.execute(plex_stmt).fetchall()

            for user in plex_users:
                premium_users.append(
                    {
                        "tg_id": user[0],
                        "username": user[1],
                        "service": "Plex",
                        "expiry_time": user[2],
                        "line": user[3],
                    }
                )

            # 获取 Emby Premium 用户
            emby_stmt = select(
                EmbyUser.tg_id,
                EmbyUser.emby_username,
                EmbyUser.premium_expiry_time,
                EmbyUser.emby_line,
            ).where(
                EmbyUser.is_premium == 1,
                (EmbyUser.premium_expiry_time.is_(None))
                | (EmbyUser.premium_expiry_time > current_time),
            )
            emby_users = session.execute(emby_stmt).fetchall()

            for user in emby_users:
                premium_users.append(
                    {
                        "tg_id": user[0],
                        "username": user[1],
                        "service": "Emby",
                        "expiry_time": user[2],
                        "line": user[3],
                    }
                )

        # 按服务类型和到期时间排序
        premium_users.sort(
            key=lambda x: (
                x["service"],
                x["expiry_time"] if x["expiry_time"] else "9999-12-31",
            )
        )

        return premium_users

    except Exception as e:
        logger.error(f"Error getting all active premium users: {e}")
        return []


def get_all_users_for_traffic_debt() -> tuple[list, list]:
    """读取所有 Plex 和 Emby 用户行供流量欠额计算。"""
    with get_session() as session:
        plex_users = session.execute(
            select(
                PlexUser.plex_id,
                PlexUser.tg_id,
                PlexUser.plex_username,
                PlexUser.is_premium,
                PlexUser.premium_traffic_debt_bytes,
                PlexUser.premium_traffic_debt_updated_date,
            )
        ).fetchall()
        emby_users = session.execute(
            select(
                EmbyUser.emby_username,
                EmbyUser.tg_id,
                EmbyUser.is_premium,
                EmbyUser.premium_traffic_debt_bytes,
                EmbyUser.premium_traffic_debt_updated_date,
            )
        ).fetchall()
        return plex_users, emby_users


def expire_user(tg_id: int, service: str, now: datetime) -> dict | None:
    """在独立事务中执行单用户到期，返回处理结果。"""
    with get_session() as session:
        return expire_user_tx(session, tg_id=tg_id, service=service, now=now)


def grant_premium_days(tg_id: int, service: str, days: int = 30) -> datetime | None:
    """在独立事务中锁行并延长 Premium 到期时间。"""
    with get_session() as session:
        return grant_premium_days_tx(session, tg_id, service, days)


def _quota_status(
    *,
    is_premium: bool,
    debt_bytes: int | None,
    updated_date: str | None,
    now: datetime,
    traffic_limit: int,
) -> dict:
    current_debt = int(debt_bytes or 0)
    if updated_date:
        try:
            debt_day = datetime.strptime(updated_date, "%Y-%m-%d").replace(
                tzinfo=settings.TZ
            )
            gap_days = max((now.date() - debt_day.date()).days - 1, 0)
            current_debt = max(current_debt - gap_days * traffic_limit, 0)
        except ValueError:
            logger.warning("Invalid Premium traffic debt date: %s", updated_date)
    return {
        "daily_limit": traffic_limit,
        "current_debt": current_debt,
        "remaining_free": max(traffic_limit - current_debt, 0),
    }


# ---------------------------------------------------------------- Premium 天数
#
# 礼包等跨域奖励要延长 Premium 到期时间：列属于 identity 宽表，写入由 premium
# 负责，所以通过这里的 `*_tx` 在调用方事务内加行锁后读写，媒体服务器同步由
# 调用方在提交之后执行（见 design D2）。


def grant_premium_days_tx(
    session, tg_id: int, service: str, days: int = 30
) -> datetime | None:
    """锁住媒体账号行并延长 Premium 到期时间（调用方持有事务）。"""
    model = PlexUser if service == "plex" else EmbyUser
    if service not in ("plex", "emby"):
        raise ValueError("不支持的服务类型")
    row = (
        session.execute(
            select(model).where(model.tg_id == int(tg_id)).with_for_update()
        )
        .scalars()
        .one_or_none()
    )
    if row is None:
        raise PremiumAccountNotBound(service)

    current_expiry = row.premium_expiry_time
    if bool(row.is_premium) and not current_expiry:
        return None

    now = datetime.now(settings.TZ)
    if (
        current_expiry
        and datetime.fromisoformat(str(current_expiry)).astimezone(settings.TZ) > now
    ):
        new_expiry = datetime.fromisoformat(str(current_expiry)).astimezone(
            settings.TZ
        ) + timedelta(days=int(days))
    else:
        new_expiry = now + timedelta(days=int(days))

    was_premium = bool(row.is_premium)
    row.is_premium = 1
    row.premium_expiry_time = new_expiry.isoformat()
    if not was_premium:
        row.premium_status_updated_at = int(now.timestamp())
    session.flush()
    return new_expiry


def get_premium_sync_target(tg_id: int, service: str) -> str | None:
    """读取媒体权限同步所需的外部标识。"""
    try:
        with get_session() as session:
            if service == "plex":
                row = session.execute(
                    select(PlexUser.plex_email).where(PlexUser.tg_id == int(tg_id))
                ).scalar_one_or_none()
            elif service == "emby":
                row = session.execute(
                    select(EmbyUser.emby_id).where(EmbyUser.tg_id == int(tg_id))
                ).scalar_one_or_none()
            else:
                raise ValueError("不支持的服务类型")
            return str(row) if row else None
    except ValueError:
        raise
    except Exception as e:
        logger.warning(f"读取 {service} 同步标识失败 (tg_id={tg_id}): {e}")
        return None


def _expire_user_tx_impl(
    session, *, tg_id: int, service: str, now: datetime
) -> dict | None:
    """Atomically claim one expired Premium account for post-commit cleanup."""
    model = PlexUser if service == "plex" else EmbyUser
    if service not in ("plex", "emby"):
        raise ValueError("不支持的服务类型")
    row = session.execute(
        select(model).where(model.tg_id == int(tg_id)).with_for_update()
    ).scalar_one_or_none()
    if row is None or not row.is_premium or not row.premium_expiry_time:
        return None
    raw_expiry = str(row.premium_expiry_time)
    try:
        expiry = datetime.fromisoformat(raw_expiry).astimezone(settings.TZ)
    except ValueError:
        expiry = datetime.fromtimestamp(float(raw_expiry), tz=settings.TZ)
    if expiry >= now:
        return None
    old_expiry = row.premium_expiry_time
    username = row.plex_username if service == "plex" else row.emby_username
    target = row.plex_email if service == "plex" else row.emby_id
    line = row.plex_line if service == "plex" else row.emby_line
    row.is_premium = 0
    row.premium_expiry_time = None
    row.premium_status_updated_at = int(now.timestamp())
    session.flush()
    return {
        "tg_id": int(tg_id),
        "service": service,
        "username": username,
        "target": target,
        "line": line,
        "expiry_time": old_expiry,
    }


def purchase_premium(*, tg_id: int, service: str, days: int, cost: float):
    """Grant Premium and charge credits atomically in one transaction."""
    from app.domains.credits import repository as credits_repository

    with get_session() as session:
        mutation = credits_repository.deduct_tx(
            session, CreditAccount.tg(int(tg_id)), float(cost)
        )
        expiry = grant_premium_days_tx(session, int(tg_id), service, int(days))
        if expiry is None:
            raise ValueError("您已是永久 Premium 会员，无需续费")
        return expiry, mutation


def is_permanent_member(tg_id: int, service: str) -> bool:
    """Return whether the bound media account is already permanently premium."""
    model = PlexUser if service == "plex" else EmbyUser
    if service not in ("plex", "emby"):
        raise ValueError("不支持的服务类型")
    with get_session() as session:
        row = session.execute(
            select(model.is_premium, model.premium_expiry_time).where(
                model.tg_id == int(tg_id)
            )
        ).one_or_none()
        return bool(row and row[0] and not row[1])


def expire_user_tx(session, *, tg_id: int, service: str, now: datetime) -> dict | None:
    return _expire_user_tx_impl(session, tg_id=tg_id, service=service, now=now)


def _expire_user_tx(session, *, tg_id: int, service: str, now: datetime) -> dict | None:
    return _expire_user_tx_impl(session, tg_id=tg_id, service=service, now=now)


def update_traffic_debt_tx(
    session,
    account: CreditAccount,
    *,
    debt_bytes: int,
    updated_date: str | None,
) -> None:
    """Update one account's Premium traffic debt in the caller's transaction."""
    if account.kind == "plex":
        model = PlexUser
        key_column = PlexUser.plex_id
        identifier = int(account.identifier)
    elif account.kind == "emby":
        model = EmbyUser
        key_column = EmbyUser.emby_username
        identifier = str(account.identifier)
    else:
        raise ValueError("Premium traffic debt requires a Plex or Emby account")

    row = session.execute(
        select(model).where(key_column == identifier).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise ValueError(f"Premium account not found: {account.label}")
    row.premium_traffic_debt_bytes = int(debt_bytes)
    row.premium_traffic_debt_updated_date = updated_date
    session.flush()


class PremiumRepositoryAPI:
    """Legacy method-shaped adapter retained for source-level compatibility tests."""

    def grant_premium_days_tx(
        self, session, tg_id: int, service: str, days: int
    ) -> datetime | None:
        """Delegate to the transaction helper, which uses with_for_update."""
        return grant_premium_days_tx(session, tg_id, service, days)
