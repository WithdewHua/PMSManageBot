from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.custom_lines.models import CustomLine
from app.domains.identity.models import EmbyUser, PlexUser
from app.domains.traffic.models import LineTrafficStats
from app.domains.vaultwarden.models import VaultwardenRedeemRecords


class ReportsRepository:
    def get_plex_users_num(self) -> int:
        """获取 Plex 用户数量"""
        with get_session() as session:
            stmt = select(func.count(PlexUser.plex_id))
            return session.execute(stmt).scalar()

    def get_emby_users_num(self) -> int:
        """获取 Emby 用户数量"""
        with get_session() as session:
            stmt = select(func.count(EmbyUser.emby_username))
            return session.execute(stmt).scalar()

    def get_nsfw_unlocked_users_num(self) -> int:
        """获取 NSFW 解锁用户数量"""
        with get_session() as session:
            # Plex 用户中已解锁 NSFW 的数量
            plex_stmt = select(func.count(PlexUser.id)).where(PlexUser.all_lib == 1)
            plex_count = session.execute(plex_stmt).scalar() or 0

            # Emby 用户中已解锁 NSFW 的数量
            emby_stmt = select(func.count(EmbyUser.emby_username)).where(
                EmbyUser.emby_is_unlock == 1
            )
            emby_count = session.execute(emby_stmt).scalar() or 0

            return plex_count + emby_count

    def get_line_schedule_unlocked_users_num(self) -> int:
        """获取线路调度解锁用户数量"""
        with get_session() as session:
            # Plex 用户中已解锁线路调度的数量
            plex_stmt = select(func.count(PlexUser.id)).where(
                PlexUser.line_schedule_unlocked == 1
            )
            plex_count = session.execute(plex_stmt).scalar() or 0

            # Emby 用户中已解锁线路调度的数量
            emby_stmt = select(func.count(EmbyUser.emby_username)).where(
                EmbyUser.line_schedule_unlocked == 1
            )
            emby_count = session.execute(emby_stmt).scalar() or 0

            return plex_count + emby_count

    def get_vaultwarden_redeemed_users_num(self) -> int:
        """获取 Vaultwarden 兑换次数"""
        with get_session() as session:
            # 统计总兑换次数
            stmt = select(func.count(VaultwardenRedeemRecords.id))
            return session.execute(stmt).scalar() or 0

    def get_traffic_statistics(self) -> dict:
        """获取全面的流量统计信息，包括今日/本周/本月，按服务类型和线路分类"""
        try:
            now = datetime.now(settings.TZ)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = today_start - timedelta(days=now.weekday())
            month_start = today_start.replace(day=1)

            periods = [
                ("today", today_start.isoformat()),
                ("week", week_start.isoformat()),
                ("month", month_start.isoformat()),
            ]

            result = {}

            with get_session() as session:
                # 获取所有已批准的自定义线路域名
                approved_custom_lines = (
                    session.execute(
                        select(CustomLine.domain).where(CustomLine.status == "approved")
                    )
                    .scalars()
                    .all()
                )

                for period_name, start_time in periods:
                    # 查询按服务类型分组的流量统计
                    service_results = session.execute(
                        select(
                            LineTrafficStats.service,
                            func.coalesce(
                                func.sum(LineTrafficStats.send_bytes), 0
                            ).label("total_traffic"),
                        )
                        .where(LineTrafficStats.timestamp >= start_time)
                        .group_by(LineTrafficStats.service)
                    ).fetchall()

                    # 查询按线路分组的流量统计
                    line_results = session.execute(
                        select(
                            LineTrafficStats.line,
                            func.coalesce(
                                func.sum(LineTrafficStats.send_bytes), 0
                            ).label("total_traffic"),
                        )
                        .where(LineTrafficStats.timestamp >= start_time)
                        .group_by(LineTrafficStats.line)
                        .order_by(func.sum(LineTrafficStats.send_bytes).desc())
                    ).fetchall()

                    # 计算总流量
                    total_traffic = session.execute(
                        select(
                            func.coalesce(func.sum(LineTrafficStats.send_bytes), 0)
                        ).where(LineTrafficStats.timestamp >= start_time)
                    ).scalar()

                    # 构建期间数据
                    period_data = {
                        "total": total_traffic,
                        "emby": 0,
                        "plex": 0,
                        "lines": [],
                        "custom_lines": [],  # 新增：自定义线路统计
                    }

                    for service, traffic in service_results:
                        if service.lower() == "emby":
                            period_data["emby"] = traffic
                        elif service.lower() == "plex":
                            period_data["plex"] = traffic

                    # 添加线路数据
                    for line, traffic in line_results:
                        is_known_line = False
                        # 检查是否是已知线路
                        for _line in (
                            settings.STREAM_BACKEND + settings.PREMIUM_STREAM_BACKEND
                        ):
                            if line.lower() in _line.lower():
                                period_data["lines"].append(
                                    {"line": line, "traffic": traffic}
                                )
                                is_known_line = True
                                break

                        # 如果不是已知线路，检查是否是已批准的自定义线路
                        if not is_known_line and line in approved_custom_lines:
                            period_data["custom_lines"].append(
                                {"line": line, "traffic": traffic, "is_custom": True}
                            )

                    result[period_name] = period_data

            return result

        except Exception as e:
            logger.error(f"Error getting comprehensive traffic statistics: {e}")
            return {
                "today": {
                    "total": 0,
                    "emby": 0,
                    "plex": 0,
                    "lines": [],
                    "custom_lines": [],
                },
                "week": {
                    "total": 0,
                    "emby": 0,
                    "plex": 0,
                    "lines": [],
                    "custom_lines": [],
                },
                "month": {
                    "total": 0,
                    "emby": 0,
                    "plex": 0,
                    "lines": [],
                    "custom_lines": [],
                },
            }
