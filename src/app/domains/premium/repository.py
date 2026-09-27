from datetime import datetime, timedelta

from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.identity.models import EmbyUser, PlexUser
from app.domains.traffic.models import LineTrafficStats


class PremiumRepository:
    def get_plex_premium_quota_status(self, plex_id: int) -> dict:
        """获取 Plex 用户今日 Premium 免费额度状态"""
        try:
            today = datetime.now(settings.TZ)
            with get_session() as session:
                user = session.execute(
                    select(
                        PlexUser.is_premium,
                        PlexUser.premium_traffic_debt_bytes,
                        PlexUser.premium_traffic_debt_updated_date,
                    ).where(PlexUser.plex_id == plex_id)
                ).fetchone()

            if not user:
                return {
                    "daily_limit": 0,
                    "current_debt": 0,
                    "remaining_free": 0,
                }

            daily_limit = (
                settings.PREMIUM_USER_TRAFFIC_LIMIT
                if user[0]
                else settings.USER_TRAFFIC_LIMIT
            )
            current_debt = int(user[1] or 0)
            debt_updated_date = user[2]

            if debt_updated_date:
                try:
                    debt_day = datetime.strptime(debt_updated_date, "%Y-%m-%d").replace(
                        tzinfo=settings.TZ
                    )
                    gap_days = max((today.date() - debt_day.date()).days - 1, 0)
                    current_debt = max(current_debt - gap_days * daily_limit, 0)
                except ValueError:
                    logger.warning(
                        f"Invalid Plex premium debt date for {plex_id}: {debt_updated_date}"
                    )

            return {
                "daily_limit": daily_limit,
                "current_debt": current_debt,
                "remaining_free": max(daily_limit - current_debt, 0),
            }
        except Exception as e:
            logger.error(f"Error getting Plex premium quota status for {plex_id}: {e}")
            return {"daily_limit": 0, "current_debt": 0, "remaining_free": 0}

    def get_emby_premium_quota_status(self, emby_username: str) -> dict:
        """获取 Emby 用户今日 Premium 免费额度状态"""
        try:
            today = datetime.now(settings.TZ)
            with get_session() as session:
                user = session.execute(
                    select(
                        EmbyUser.is_premium,
                        EmbyUser.premium_traffic_debt_bytes,
                        EmbyUser.premium_traffic_debt_updated_date,
                    ).where(func.lower(EmbyUser.emby_username) == emby_username.lower())
                ).fetchone()

            if not user:
                return {
                    "daily_limit": 0,
                    "current_debt": 0,
                    "remaining_free": 0,
                }

            daily_limit = (
                settings.PREMIUM_USER_TRAFFIC_LIMIT
                if user[0]
                else settings.USER_TRAFFIC_LIMIT
            )
            current_debt = int(user[1] or 0)
            debt_updated_date = user[2]

            if debt_updated_date:
                try:
                    debt_day = datetime.strptime(debt_updated_date, "%Y-%m-%d").replace(
                        tzinfo=settings.TZ
                    )
                    gap_days = max((today.date() - debt_day.date()).days - 1, 0)
                    current_debt = max(current_debt - gap_days * daily_limit, 0)
                except ValueError:
                    logger.warning(
                        f"Invalid Emby premium debt date for {emby_username}: {debt_updated_date}"
                    )

            return {
                "daily_limit": daily_limit,
                "current_debt": current_debt,
                "remaining_free": max(daily_limit - current_debt, 0),
            }
        except Exception as e:
            logger.error(
                f"Error getting Emby premium quota status for {emby_username}: {e}"
            )
            return {"daily_limit": 0, "current_debt": 0, "remaining_free": 0}

    def get_expired_premium_users(self) -> list:
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

    def update_expired_premium_status(self) -> int:
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

    def get_premium_users_expiring_soon(self, days: int = 3) -> list:
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

    def get_premium_statistics(self) -> dict:
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

    def get_all_active_premium_users(self) -> list:
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

    def get_all_premium_traffic_debt_users(self) -> list:
        """获取所有有 Premium 流量欠额或预计结算后欠额的用户"""
        debt_users = []
        now = datetime.now(settings.TZ)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        premium_lines = settings.PREMIUM_STREAM_BACKEND

        if not premium_lines:
            return debt_users

        try:
            with get_session() as session:
                plex_traffic_rows = session.execute(
                    select(
                        LineTrafficStats.user_id,
                        func.coalesce(func.sum(LineTrafficStats.send_bytes), 0),
                    )
                    .where(
                        LineTrafficStats.service == "plex",
                        LineTrafficStats.user_id.isnot(None),
                        LineTrafficStats.line.in_(premium_lines),
                        LineTrafficStats.timestamp >= today_start.isoformat(),
                        LineTrafficStats.timestamp <= today_end.isoformat(),
                    )
                    .group_by(LineTrafficStats.user_id)
                ).fetchall()
                plex_today_traffic = {
                    str(user_id): int(traffic or 0)
                    for user_id, traffic in plex_traffic_rows
                    if user_id
                }
                plex_today_user_ids = [
                    int(user_id)
                    for user_id in plex_today_traffic
                    if str(user_id).isdigit()
                ]

                emby_traffic_rows = session.execute(
                    select(
                        LineTrafficStats.username,
                        func.coalesce(func.sum(LineTrafficStats.send_bytes), 0),
                    )
                    .where(
                        LineTrafficStats.service == "emby",
                        LineTrafficStats.line.in_(premium_lines),
                        LineTrafficStats.timestamp >= today_start.isoformat(),
                        LineTrafficStats.timestamp <= today_end.isoformat(),
                    )
                    .group_by(LineTrafficStats.username)
                ).fetchall()
                emby_today_traffic = {
                    username.lower(): int(traffic or 0)
                    for username, traffic in emby_traffic_rows
                    if username
                }

                plex_stmt = select(
                    PlexUser.plex_id,
                    PlexUser.tg_id,
                    PlexUser.plex_username,
                    PlexUser.plex_line,
                    PlexUser.is_premium,
                    PlexUser.premium_traffic_debt_bytes,
                ).where(
                    (PlexUser.premium_traffic_debt_bytes > 0)
                    | (PlexUser.plex_id.in_(plex_today_user_ids))
                )
                plex_users = session.execute(plex_stmt).fetchall()

                emby_stmt = select(
                    EmbyUser.emby_username,
                    EmbyUser.tg_id,
                    EmbyUser.emby_line,
                    EmbyUser.is_premium,
                    EmbyUser.premium_traffic_debt_bytes,
                ).where(
                    (EmbyUser.premium_traffic_debt_bytes > 0)
                    | (
                        func.lower(EmbyUser.emby_username).in_(
                            list(emby_today_traffic.keys())
                        )
                    )
                )
                emby_users = session.execute(emby_stmt).fetchall()

            for user in plex_users:
                plex_id = user[0]
                today_premium_traffic = plex_today_traffic.get(str(plex_id), 0)
                quota_status = self.get_plex_premium_quota_status(plex_id)
                daily_limit = quota_status["daily_limit"]
                current_debt = quota_status["current_debt"]
                projected_debt = min(
                    max(current_debt + today_premium_traffic - daily_limit, 0),
                    daily_limit * 2,
                )
                today_exceed_traffic = max(
                    today_premium_traffic - quota_status["remaining_free"], 0
                )

                if current_debt > 0 or projected_debt > 0:
                    debt_users.append(
                        {
                            "service": "Plex",
                            "username": user[2],
                            "tg_id": user[1],
                            "is_premium": bool(user[4]),
                            "current_debt": current_debt,
                            "today_exceed_traffic": today_exceed_traffic,
                            "projected_debt": projected_debt,
                        }
                    )

            for user in emby_users:
                username = user[0]
                today_premium_traffic = emby_today_traffic.get(username.lower(), 0)
                quota_status = self.get_emby_premium_quota_status(username)
                daily_limit = quota_status["daily_limit"]
                current_debt = quota_status["current_debt"]
                projected_debt = min(
                    max(current_debt + today_premium_traffic - daily_limit, 0),
                    daily_limit * 2,
                )
                today_exceed_traffic = max(
                    today_premium_traffic - quota_status["remaining_free"], 0
                )

                if current_debt > 0 or projected_debt > 0:
                    debt_users.append(
                        {
                            "service": "Emby",
                            "username": username,
                            "tg_id": user[1],
                            "is_premium": bool(user[3]),
                            "current_debt": current_debt,
                            "today_exceed_traffic": today_exceed_traffic,
                            "projected_debt": projected_debt,
                        }
                    )

            debt_users.sort(
                key=lambda item: (
                    item["service"],
                    -item["projected_debt"],
                    -item["current_debt"],
                    item["username"] or "",
                )
            )
            return debt_users
        except Exception as e:
            logger.error(f"Error getting premium traffic debt users: {e}")
            return []

    # ---------------------------------------------------------------- Premium 天数
    #
    # 礼包等跨域奖励要延长 Premium 到期时间：列属于 identity 宽表，写入由 premium
    # 负责，所以通过这里的 `*_tx` 在调用方事务内加行锁后读写，媒体服务器同步由
    # 调用方在提交之后执行（见 design D2）。

    def grant_premium_days_tx(
        self, session, tg_id: int, service: str, days: int = 30
    ) -> datetime | None:
        """锁住媒体账号行并延长 Premium 到期时间（调用方持有事务）。

        行为与旧的 `update_premium_status` 一致：永久会员返回 None 且不写入；
        未过期则从原到期时间续期，已过期或首次开通则从当前时间起算；首次成为
        Premium 会写入 `premium_status_updated_at`。
        """
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
            raise NameError(
                "请先绑定 Plex 账户" if service == "plex" else "请先绑定 Emby 账户"
            )

        current_expiry = row.premium_expiry_time
        if bool(row.is_premium) and not current_expiry:
            # 永久会员：跳过延长
            return None

        now = datetime.now(settings.TZ)
        if (
            current_expiry
            and datetime.fromisoformat(str(current_expiry)).astimezone(settings.TZ)
            > now
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

    def get_premium_sync_target(self, tg_id: int, service: str) -> str | None:
        """把 Premium 权限同步到媒体服务器所需的外部标识（Plex 邮箱 / Emby ID）。"""
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


# 模块级入口：跨域调用方（如礼包）只使用这些函数，不触碰门面实例。
_premium_repository = PremiumRepository()


def grant_premium_days_tx(
    session, tg_id: int, service: str, days: int = 30
) -> datetime | None:
    return _premium_repository.grant_premium_days_tx(session, tg_id, service, days)


def get_premium_sync_target(tg_id: int, service: str) -> str | None:
    return _premium_repository.get_premium_sync_target(tg_id, service)
