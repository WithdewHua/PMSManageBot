from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.identity import service as identity_service
from app.domains.identity.models import EmbyUser, PlexUser
from app.domains.traffic.models import LineTrafficMonthlyStats, LineTrafficStats


class TrafficRepository:
    def create_line_traffic_entry(
        self,
        line: str,
        send_bytes: int,
        service: str,
        username: str,
        user_id: str,
        timestamp: str,
        event_hash: str,
        request_uri: str | None = None,
        upstream: str | None = None,
        upstream_response_time: str | None = None,
    ) -> tuple[bool, bool]:
        """创建流量统计记录"""
        try:
            with get_session() as session:
                existing_stmt = select(LineTrafficStats.id).where(
                    LineTrafficStats.event_hash == event_hash
                )
                existing_id = session.execute(existing_stmt).scalar_one_or_none()
                if existing_id is not None:
                    logger.info(
                        f"Skip duplicated line traffic entry, event_hash={event_hash}"
                    )
                    return False, True

                traffic_entry = LineTrafficStats(
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
                session.add(traffic_entry)
                return True, False
        except Exception as e:
            # 并发场景下仍可能在显式查询后发生唯一键冲突，保留兜底判断
            if "uq_line_traffic_event_hash" in str(
                e
            ) or "UNIQUE constraint failed: line_traffic_stats.event_hash" in str(e):
                logger.info(
                    f"Skip duplicated line traffic entry, event_hash={event_hash}"
                )
                return False, True
            logger.error(f"Error creating line traffic entry: {e}")
            return False, False

    def bulk_create_line_traffic_entries(
        self,
        rows: list[dict],
        *,
        query_chunk: int = 500,
        insert_chunk: int = 500,
    ) -> dict[str, str]:
        """批量创建流量统计记录

        Args:
            rows: 每项为含 event_hash 及 LineTrafficStats 字段的 dict

        Returns:
            {event_hash: 'inserted' | 'duplicate' | 'failed'}
            默认 'failed'（未确定，调用方应重试）；查重命中为 'duplicate'；
            成功落库为 'inserted'。批内重复 event_hash 在此防御性收敛，
            每个 event_hash 只插入一次。
        """
        if not rows:
            return {}

        # 防御性去重：同一 event_hash 只保留首条
        unique: dict[str, dict] = {}
        for row in rows:
            unique.setdefault(row["event_hash"], row)

        # 默认 failed：任何未走到确定结论的 event_hash 都交给上游重试
        result: dict[str, str] = {event_hash: "failed" for event_hash in unique}

        try:
            with get_session() as session:
                # 分块预查重，避免 SQLite IN 参数上限（999）
                hashes = list(unique.keys())
                existing: set[str] = set()
                for i in range(0, len(hashes), query_chunk):
                    chunk = hashes[i : i + query_chunk]
                    stmt = select(LineTrafficStats.event_hash).where(
                        LineTrafficStats.event_hash.in_(chunk)
                    )
                    existing.update(session.execute(stmt).scalars().all())

                for event_hash in existing:
                    result[event_hash] = "duplicate"

                pending = [unique[h] for h in hashes if h not in existing]

                # 按 service 分组后再分块插入：plex 的 user_id 是整数、emby 的是 hex
                # 字符串，而 user_id 列为 text。批量插入用多行 VALUES，Postgres 会按列
                # 统一推断类型，同一批混入整数与字符串会把该列推断为 integer，导致
                # 字符串报 "invalid input syntax for type integer"。按 service 分批可
                # 保证每批 user_id 类型同构，无需改写入值。单块失败仅影响该块。
                pending_by_service: dict[str, list[dict]] = {}
                for row in pending:
                    pending_by_service.setdefault(row["service"], []).append(row)

                for service_rows in pending_by_service.values():
                    for i in range(0, len(service_rows), insert_chunk):
                        chunk_rows = service_rows[i : i + insert_chunk]
                        try:
                            session.add_all(
                                [LineTrafficStats(**row) for row in chunk_rows]
                            )
                            session.flush()
                            session.commit()
                            for row in chunk_rows:
                                result[row["event_hash"]] = "inserted"
                        except Exception as e:
                            session.rollback()
                            logger.error(
                                f"批量插入流量日志失败，本块 {len(chunk_rows)} 条将重试: {e}"
                            )
        except Exception as e:
            logger.error(f"批量创建流量日志记录时发生错误: {e}")

        return result

    def get_premium_line_traffic_statistics(self) -> list:
        """获取Premium线路流量统计信息"""
        try:
            now = datetime.now(settings.TZ)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = today_start - timedelta(days=now.weekday())
            month_start = today_start.replace(day=1)

            # 获取Premium线路列表
            premium_lines = settings.PREMIUM_STREAM_BACKEND

            line_stats = []

            with get_session() as session:
                for line in premium_lines:
                    # 计算今日流量
                    today_traffic = session.execute(
                        select(
                            func.coalesce(func.sum(LineTrafficStats.send_bytes), 0)
                        ).where(
                            LineTrafficStats.line == line,
                            LineTrafficStats.timestamp >= today_start.isoformat(),
                        )
                    ).scalar()

                    # 计算本周流量
                    week_traffic = session.execute(
                        select(
                            func.coalesce(func.sum(LineTrafficStats.send_bytes), 0)
                        ).where(
                            LineTrafficStats.line == line,
                            LineTrafficStats.timestamp >= week_start.isoformat(),
                        )
                    ).scalar()

                    # 计算本月流量
                    month_traffic = session.execute(
                        select(
                            func.coalesce(func.sum(LineTrafficStats.send_bytes), 0)
                        ).where(
                            LineTrafficStats.line == line,
                            LineTrafficStats.timestamp >= month_start.isoformat(),
                        )
                    ).scalar()

                    # 获取当前线路流量排名前五的用户（基于今日数据）
                    top_users_result = session.execute(
                        select(
                            LineTrafficStats.username,
                            func.sum(LineTrafficStats.send_bytes).label(
                                "total_traffic"
                            ),
                        )
                        .where(
                            LineTrafficStats.line == line,
                            LineTrafficStats.timestamp >= today_start.isoformat(),
                        )
                        .group_by(LineTrafficStats.username)
                        .order_by(func.sum(LineTrafficStats.send_bytes).desc())
                        .limit(5)
                    ).fetchall()

                    top_users = []
                    for username, traffic in top_users_result:
                        top_users.append({"username": username, "traffic": traffic})

                    line_stats.append(
                        {
                            "line": line,
                            "today_traffic": today_traffic,
                            "week_traffic": week_traffic,
                            "month_traffic": month_traffic,
                            "top_users": top_users,
                        }
                    )

            return line_stats

        except Exception as e:
            logger.error(f"Error getting premium line traffic statistics: {e}")
            return []

    def get_user_daily_traffic(
        self,
        username: str | None = None,
        user_id: str | None = None,
        service: str | None = None,
        date: datetime | None = None,
        premium_only: bool = False,
    ) -> int:
        """获取用户指定日期的流量消耗，默认为今日"""
        if not username and not user_id:
            logger.error(
                "Username or user_id must be provided to get user daily traffic"
            )
            return 0
        try:
            # 如果未指定日期，使用今日
            if date is None:
                date = datetime.now(settings.TZ)

            # 确保日期对象包含时区信息
            if date.tzinfo is None:
                date = date.replace(tzinfo=settings.TZ)
            else:
                date = date.astimezone(settings.TZ)

            # 计算指定日期的开始和结束时间
            day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = date.replace(hour=23, minute=59, second=59, microsecond=999999)

            with get_session() as session:
                # 原始流量表按天精确查询，月初结算昨日数据也依赖这里
                if user_id:
                    conditions = [
                        LineTrafficStats.user_id == user_id,
                        LineTrafficStats.service == service,
                        LineTrafficStats.timestamp >= day_start.isoformat(),
                        LineTrafficStats.timestamp <= day_end.isoformat(),
                    ]
                else:
                    conditions = [
                        func.lower(LineTrafficStats.username) == username.lower(),
                        LineTrafficStats.service == service,
                        LineTrafficStats.timestamp >= day_start.isoformat(),
                        LineTrafficStats.timestamp <= day_end.isoformat(),
                    ]

                if premium_only:
                    premium_lines = settings.PREMIUM_STREAM_BACKEND
                    if premium_lines:
                        conditions.append(LineTrafficStats.line.in_(premium_lines))
                    else:
                        return 0

                result = session.execute(
                    select(
                        func.coalesce(func.sum(LineTrafficStats.send_bytes), 0)
                    ).where(*conditions)
                ).scalar()

                return result if result else 0

        except Exception as e:
            logger.error(
                f"Error getting user daily traffic for {username or user_id}: {e}"
            )
            return 0

    def get_plex_traffic_rank(self, start_date=None, end_date=None) -> list:
        """获取 Plex 流量排行榜"""
        try:
            # 使用北京时间
            now_beijing = datetime.now(settings.TZ)

            if start_date is None:
                # 默认为今日开始
                start_date = now_beijing.replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
            else:
                # 确保是当月的日期
                current_month_start = now_beijing.replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                )
                start_date = max(start_date, current_month_start)

            if end_date is None:
                # 默认为今日结束
                end_date = now_beijing.replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
            else:
                # 确保不超过今日
                today_end = now_beijing.replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
                end_date = min(end_date, today_end)

            # 仅当月数据，从 line_traffic_stats 表查询
            with get_session() as session:
                stmt = (
                    select(
                        PlexUser.plex_username,
                        LineTrafficStats.user_id,
                        func.sum(LineTrafficStats.send_bytes).label("total_traffic"),
                        func.coalesce(PlexUser.is_premium, 0).label("is_premium"),
                        PlexUser.tg_id,
                    )
                    .select_from(LineTrafficStats)
                    .outerjoin(
                        PlexUser,
                        func.lower(LineTrafficStats.username)
                        == func.lower(PlexUser.plex_username),
                    )
                    .where(
                        LineTrafficStats.service == "plex",
                        LineTrafficStats.timestamp >= start_date.isoformat(),
                        LineTrafficStats.timestamp <= end_date.isoformat(),
                        LineTrafficStats.username.isnot(None),
                        LineTrafficStats.username != "",
                    )
                    .group_by(
                        func.lower(LineTrafficStats.username),
                        LineTrafficStats.user_id,
                        PlexUser.is_premium,
                        PlexUser.tg_id,
                        PlexUser.plex_username,
                    )
                    .order_by(func.sum(LineTrafficStats.send_bytes).desc())
                    .limit(50)
                )

                results = session.execute(stmt).fetchall()
                return [(r[0], r[1], r[2], r[3], r[4]) for r in results]

        except Exception as e:
            logger.error(f"Error getting Plex traffic rank: {e}")
            return []

    def get_emby_traffic_rank(self, start_date=None, end_date=None) -> list:
        """获取 Emby 流量排行榜"""
        try:
            # 使用北京时间
            now_beijing = datetime.now(settings.TZ)

            if start_date is None:
                # 默认为今日开始
                start_date = now_beijing.replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
            else:
                # 确保是当月的日期
                current_month_start = now_beijing.replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                )
                start_date = max(start_date, current_month_start)

            if end_date is None:
                # 默认为今日结束
                end_date = now_beijing.replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
            else:
                # 确保不超过今日
                today_end = now_beijing.replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
                end_date = min(end_date, today_end)

            with get_session() as session:
                stmt = (
                    select(
                        EmbyUser.emby_username,
                        LineTrafficStats.user_id,
                        func.sum(LineTrafficStats.send_bytes).label("total_traffic"),
                        func.coalesce(EmbyUser.is_premium, 0).label("is_premium"),
                        EmbyUser.tg_id,
                    )
                    .select_from(LineTrafficStats)
                    .outerjoin(
                        EmbyUser,
                        func.lower(LineTrafficStats.username)
                        == func.lower(EmbyUser.emby_username),
                    )
                    .where(
                        LineTrafficStats.service == "emby",
                        LineTrafficStats.timestamp >= start_date.isoformat(),
                        LineTrafficStats.timestamp <= end_date.isoformat(),
                        LineTrafficStats.username.isnot(None),
                        LineTrafficStats.username != "",
                    )
                    .group_by(
                        func.lower(LineTrafficStats.username),
                        LineTrafficStats.user_id,
                        EmbyUser.is_premium,
                        EmbyUser.tg_id,
                        EmbyUser.emby_username,
                    )
                    .order_by(func.sum(LineTrafficStats.send_bytes).desc())
                    .limit(50)
                )

                results = session.execute(stmt).fetchall()
                return [(r[0], r[1], r[2], r[3], r[4]) for r in results]

        except Exception as e:
            logger.error(f"Error getting Emby traffic rank: {e}")
            return []

    def aggregate_monthly_traffic_data(self, target_month: str | None = None) -> tuple:
        """聚合指定月份的流量数据到月度统计表"""
        try:
            if target_month is None:
                # 默认处理上个月的数据
                now = datetime.now(settings.TZ)
                if now.day == 1:
                    # 如果是每月1号，处理上个月数据
                    last_month = now.replace(day=1) - timedelta(days=1)
                    target_month = last_month.strftime("%Y-%m")
                else:
                    return False, "只能在每月1号自动处理上个月数据"

            logger.info(f"开始聚合 {target_month} 的流量数据")

            # 验证月份格式
            try:
                # 偏移量仅用于格式校验，实际月份范围仍按 settings.TZ 计算。
                datetime.strptime(f"{target_month} +0000", "%Y-%m %z")
            except ValueError:
                return False, f"月份格式错误: {target_month}，应为 YYYY-MM 格式"

            with get_session() as session:
                # 检查是否已经聚合过该月份的数据（已改为警告而非阻止）
                existing_check = session.execute(
                    select(func.count(LineTrafficMonthlyStats.id)).where(
                        LineTrafficMonthlyStats.year_month == target_month
                    )
                ).scalar()

                if existing_check > 0:
                    logger.warning(
                        f"月份 {target_month} 已存在 {existing_check} 条聚合数据，将跳过重复记录"
                    )

                # 计算目标月份的开始和结束时间
                month_start = datetime.strptime(
                    f"{target_month}-01", "%Y-%m-%d"
                ).replace(tzinfo=settings.TZ)
                if month_start.month == 12:
                    next_month_start = month_start.replace(
                        year=month_start.year + 1, month=1
                    )
                else:
                    next_month_start = month_start.replace(month=month_start.month + 1)

                month_start_str = month_start.isoformat()
                next_month_start_str = next_month_start.isoformat()

                # 聚合查询：按 line, service, username, user_id 分组求和
                aggregation_stmt = (
                    select(
                        LineTrafficStats.line,
                        LineTrafficStats.service,
                        LineTrafficStats.username,
                        LineTrafficStats.user_id,
                        func.sum(LineTrafficStats.send_bytes).label("total_bytes"),
                        func.count(LineTrafficStats.id).label("record_count"),
                    )
                    .where(
                        LineTrafficStats.timestamp >= month_start_str,
                        LineTrafficStats.timestamp < next_month_start_str,
                    )
                    .group_by(
                        LineTrafficStats.line,
                        LineTrafficStats.service,
                        LineTrafficStats.username,
                        LineTrafficStats.user_id,
                    )
                    .having(func.sum(LineTrafficStats.send_bytes) > 0)
                    .order_by(func.sum(LineTrafficStats.send_bytes).desc())
                )

                aggregated_data = session.execute(aggregation_stmt).fetchall()

                if not aggregated_data:
                    return False, f"月份 {target_month} 没有找到需要聚合的数据"

                # 插入聚合数据到月度统计表
                current_time = datetime.now(settings.TZ).isoformat()
                insert_count = 0
                skip_count = 0
                update_count = 0

                # 使用 SAVEPOINT 来处理每条记录，避免整个事务回滚
                from sqlalchemy import exc as sa_exc

                for record in aggregated_data:
                    line, service, username, user_id, total_bytes, _record_count = (
                        record
                    )

                    # 为每条记录创建一个保存点
                    savepoint = session.begin_nested()

                    try:
                        # 先检查记录是否已存在
                        existing_record = session.execute(
                            select(LineTrafficMonthlyStats).where(
                                LineTrafficMonthlyStats.line == line,
                                LineTrafficMonthlyStats.service == service,
                                LineTrafficMonthlyStats.username == username,
                                LineTrafficMonthlyStats.year_month == target_month,
                            )
                        ).scalar_one_or_none()

                        if existing_record:
                            # 记录已存在，检查是否需要更新
                            if existing_record.total_bytes != total_bytes:
                                existing_record.total_bytes = total_bytes
                                existing_record.created_at = current_time
                                update_count += 1
                                logger.debug(
                                    f"更新月度流量记录: {line}, {service}, {username}, {target_month}"
                                )
                            else:
                                skip_count += 1
                        else:
                            # 记录不存在，插入新记录
                            monthly_stat = LineTrafficMonthlyStats(
                                line=line,
                                service=service,
                                username=username,
                                user_id=user_id,
                                year_month=target_month,
                                total_bytes=total_bytes,
                                created_at=current_time,
                            )
                            session.add(monthly_stat)
                            insert_count += 1

                        # 提交这条记录的保存点
                        savepoint.commit()

                    except sa_exc.IntegrityError:
                        # 唯一约束冲突，回滚到保存点
                        savepoint.rollback()
                        skip_count += 1
                        logger.debug(
                            f"跳过重复记录（唯一约束冲突）: {line}, {service}, {username}, {target_month}"
                        )
                    except Exception as e:
                        # 其他错误，回滚到保存点
                        savepoint.rollback()
                        skip_count += 1
                        logger.warning(
                            f"处理月度聚合数据失败: {e}, 数据: line={line}, service={service}, "
                            f"username={username}, month={target_month}"
                        )

                logger.info(
                    f"成功聚合 {target_month} 月份数据: {len(aggregated_data)} 个用户组合，"
                    f"插入 {insert_count} 条新记录，更新 {update_count} 条记录，跳过 {skip_count} 条重复记录"
                )
                return (
                    True,
                    (
                        f"成功聚合 {target_month} 月份数据: 插入了 {insert_count} 条新记录，"
                        f"更新了 {update_count} 条记录，跳过了 {skip_count} 条重复记录"
                    ),
                )

        except Exception as e:
            logger.error(f"聚合月度流量数据失败: {e}")
            return False, f"聚合月度流量数据失败: {e!s}"

    def cleanup_monthly_traffic_data(self, target_month: str) -> tuple:
        """清理已聚合月份的原始流量数据"""
        try:
            # 验证月份格式
            try:
                # 偏移量仅用于格式校验，实际月份范围仍按 settings.TZ 计算。
                datetime.strptime(f"{target_month} +0000", "%Y-%m %z")
            except ValueError:
                return False, f"月份格式错误: {target_month}，应为 YYYY-MM 格式"

            with get_session() as session:
                # 检查月度聚合数据是否存在
                monthly_check = session.execute(
                    select(func.count(LineTrafficMonthlyStats.id)).where(
                        LineTrafficMonthlyStats.year_month == target_month
                    )
                ).scalar()

                if monthly_check == 0:
                    return (
                        False,
                        f"月份 {target_month} 的聚合数据不存在，不能清理原始数据",
                    )

                # 计算目标月份的时间范围
                month_start = datetime.strptime(
                    f"{target_month}-01", "%Y-%m-%d"
                ).replace(tzinfo=settings.TZ)
                if month_start.month == 12:
                    next_month_start = month_start.replace(
                        year=month_start.year + 1, month=1
                    )
                else:
                    next_month_start = month_start.replace(month=month_start.month + 1)

                month_start_str = month_start.isoformat()
                next_month_start_str = next_month_start.isoformat()

                # 统计要删除的记录数
                delete_count = session.execute(
                    select(func.count(LineTrafficStats.id)).where(
                        LineTrafficStats.timestamp >= month_start_str,
                        LineTrafficStats.timestamp < next_month_start_str,
                    )
                ).scalar()

                if delete_count == 0:
                    return True, f"月份 {target_month} 没有需要清理的原始数据"

                # 删除原始数据
                session.execute(
                    delete(LineTrafficStats).where(
                        LineTrafficStats.timestamp >= month_start_str,
                        LineTrafficStats.timestamp < next_month_start_str,
                    )
                )

                logger.info(
                    f"已清理 {target_month} 月份的 {delete_count} 条原始流量数据"
                )
                return (
                    True,
                    f"成功清理 {target_month} 月份的 {delete_count} 条原始流量数据",
                )

        except Exception as e:
            logger.error(f"清理月度流量数据失败: {e}")
            return False, f"清理月度流量数据失败: {e!s}"

    def update_traffic_username(self, old_username: str, new_username: str) -> bool:
        """更新流量统计中的用户名"""
        if not old_username or not new_username:
            logger.warning(
                f"跳过流量统计用户名更新，用户名为空: {old_username} -> {new_username}"
            )
            return False

        try:
            with get_session() as session:
                # 更新 line_traffic_stats 表
                raw_result = session.execute(
                    update(LineTrafficStats)
                    .where(
                        func.lower(LineTrafficStats.username) == old_username.lower()
                    )
                    .values(username=new_username)
                )

                # 月度表存在唯一约束 (line, service, username, year_month)，
                # 用户名变更时如果目标用户名记录已存在，需要合并流量后删除旧记录。
                monthly_records = session.execute(
                    select(LineTrafficMonthlyStats).where(
                        func.lower(LineTrafficMonthlyStats.username)
                        == old_username.lower(),
                        LineTrafficMonthlyStats.username != new_username,
                    )
                ).scalars()

                monthly_updated_count = 0
                monthly_merged_count = 0
                for monthly_record in monthly_records:
                    existing_record = session.execute(
                        select(LineTrafficMonthlyStats).where(
                            LineTrafficMonthlyStats.line == monthly_record.line,
                            LineTrafficMonthlyStats.service == monthly_record.service,
                            LineTrafficMonthlyStats.username == new_username,
                            LineTrafficMonthlyStats.year_month
                            == monthly_record.year_month,
                            LineTrafficMonthlyStats.id != monthly_record.id,
                        )
                    ).scalar_one_or_none()

                    if existing_record:
                        existing_record.total_bytes += monthly_record.total_bytes
                        if not existing_record.user_id and monthly_record.user_id:
                            existing_record.user_id = monthly_record.user_id
                        session.delete(monthly_record)
                        monthly_merged_count += 1
                    else:
                        monthly_record.username = new_username
                        monthly_updated_count += 1

                logger.info(
                    f"更新流量统计用户名成功: {old_username} -> {new_username}, "
                    f"原始记录 {raw_result.rowcount} 条, 月度更新 {monthly_updated_count} 条, "
                    f"月度合并 {monthly_merged_count} 条"
                )
                return True
        except Exception as e:
            logger.error(f"更新流量统计用户名失败: {e}")
            return False


from datetime import datetime

from sqlalchemy import and_

from app.domains.lines.rules import normalize_line_domain


async def _get_line_monthly_traffic(
    session,
    line_domain: str,
    year_month: str,
    owner_tg_id: int | None = None,
    from_raw_table: bool = False,
) -> float:
    """
    获取指定线路在指定月份的总流量（GB）

    Args:
        session: 数据库会话
        line_domain: 线路域名（支持带协议前缀或路径后缀，内部会自动规范化为纯主机名）
        year_month: 年月，格式：YYYY-MM
        owner_tg_id: 线路所有者的 tg_id，传入时排除该所有者产生的流量（用于结算），
                     None 表示包含所有用户流量（用于流量检查）
        from_raw_table: 是否从原始流量表(line_traffic_stats)实时聚合，用于删除线路时获取当月未聚合的流量

    Returns:
        总流量（GB）
    """
    try:
        # 规范化 line_domain，去除协议前缀和路径后缀，与数据库中存储的纯主机名格式对齐
        normalized_domain = normalize_line_domain(line_domain)
        if normalized_domain != line_domain:
            logger.debug(f"线路域名规范化: {line_domain!r} -> {normalized_domain!r}")
        # 获取线路所有者的用户名（Plex 和 Emby）
        owner_usernames = set()

        if owner_tg_id is not None:
            # Preserve B2's two independent identity lookup sessions. The
            # aggregation query below still uses the caller's session.
            plex_user = identity_service.get_plex_info_by_tg_id(owner_tg_id)
            if plex_user and plex_user[4]:  # plex_username (索引4)
                owner_usernames.add(plex_user[4].lower())

            emby_user = identity_service.get_emby_info_by_tg_id(owner_tg_id)
            if emby_user and emby_user[0]:  # emby_username
                owner_usernames.add(emby_user[0].lower())

        if from_raw_table:
            # 从原始流量表实时聚合（用于删除线路时获取当月流量）
            from app.domains.traffic.models import LineTrafficStats

            # 计算目标月份的开始和结束时间
            month_start = datetime.strptime(f"{year_month}-01", "%Y-%m-%d").replace(
                tzinfo=settings.TZ
            )
            if month_start.month == 12:
                next_month_start = month_start.replace(
                    year=month_start.year + 1, month=1
                )
            else:
                next_month_start = month_start.replace(month=month_start.month + 1)

            month_start_str = month_start.isoformat()
            next_month_start_str = next_month_start.isoformat()

            # 从原始流量表实时聚合
            stmt = select(func.sum(LineTrafficStats.send_bytes)).where(
                and_(
                    LineTrafficStats.line == normalized_domain,
                    LineTrafficStats.timestamp >= month_start_str,
                    LineTrafficStats.timestamp < next_month_start_str,
                    ~LineTrafficStats.username.in_([u.lower() for u in owner_usernames])
                    if owner_usernames
                    else True,
                )
            )

            result = session.execute(stmt)
            total_bytes = result.scalar() or 0

            logger.info(
                f"从原始流量表聚合线路 {normalized_domain} {year_month} 流量: {total_bytes} bytes"
            )
        else:
            # 从月度流量统计表查询（用于正常月初结算）
            stmt = select(func.sum(LineTrafficMonthlyStats.total_bytes)).where(
                and_(
                    LineTrafficMonthlyStats.line == normalized_domain,
                    LineTrafficMonthlyStats.year_month == year_month,
                    ~LineTrafficMonthlyStats.username.in_(
                        [u.lower() for u in owner_usernames]
                    )
                    if owner_usernames
                    else True,
                )
            )

            result = session.execute(stmt)
            total_bytes = result.scalar() or 0

        # 转换为 GB
        total_gb = total_bytes / (1024**3)

        return total_gb

    except Exception as e:
        logger.error(
            f"获取线路 {line_domain} 月流量失败 (月份: {year_month}, 原始表: {from_raw_table}): {e}",
            exc_info=True,
        )
        return 0.0
