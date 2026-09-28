import time
from datetime import datetime

from sqlalchemy import select, update

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.credits import repository as credits_repository
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import EmbyUser, PlexUser
from app.domains.lines.models import LineSchedule


class LinesRepository:
    def set_emby_line(
        self, line: str, tg_id: int | None = None, emby_id: str | None = None
    ) -> bool:
        """设置 Emby 线路"""
        try:
            with get_session() as session:
                if tg_id is not None:
                    session.execute(
                        update(EmbyUser)
                        .where(EmbyUser.tg_id == tg_id)
                        .values(emby_line=line)
                    )
                elif emby_id is not None:
                    session.execute(
                        update(EmbyUser)
                        .where(EmbyUser.emby_id == emby_id)
                        .values(emby_line=line)
                    )
                return True
        except Exception as e:
            logger.error(f"Error setting emby line: {e}")
            return False

    def get_emby_line(self, tg_id: int) -> str | None:
        """获取 Emby 线路"""
        with get_session() as session:
            stmt = select(EmbyUser.emby_line).where(EmbyUser.tg_id == tg_id)
            result = session.execute(stmt).scalar_one_or_none()
            return result

    def get_emby_user_with_binded_line(self) -> list:
        """获取绑定线路的 Emby 用户"""
        with get_session() as session:
            stmt = select(
                EmbyUser.emby_username,
                EmbyUser.tg_id,
                EmbyUser.emby_id,
                EmbyUser.emby_line,
                EmbyUser.is_premium,
            ).where(EmbyUser.emby_line.isnot(None))
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1], r[2], r[3], r[4]) for r in results]

    def set_plex_line(
        self, line: str, tg_id: int | None = None, plex_id: int | None = None
    ) -> bool:
        """设置 Plex 线路"""
        try:
            with get_session() as session:
                if tg_id is not None:
                    session.execute(
                        update(PlexUser)
                        .where(PlexUser.tg_id == tg_id)
                        .values(plex_line=line)
                    )
                elif plex_id is not None:
                    session.execute(
                        update(PlexUser)
                        .where(PlexUser.plex_id == plex_id)
                        .values(plex_line=line)
                    )
                return True
        except Exception as e:
            logger.error(f"Error setting plex line: {e}")
            return False

    def get_plex_line(self, tg_id: int) -> str | None:
        """获取 Plex 线路"""
        with get_session() as session:
            stmt = select(PlexUser.plex_line).where(PlexUser.tg_id == tg_id)
            result = session.execute(stmt).scalar_one_or_none()
            return result

    def get_plex_user_with_binded_line(self) -> list:
        """获取绑定线路的 Plex 用户"""
        with get_session() as session:
            stmt = select(
                PlexUser.plex_username,
                PlexUser.tg_id,
                PlexUser.plex_id,
                PlexUser.plex_line,
                PlexUser.is_premium,
            ).where(PlexUser.plex_line.isnot(None))
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1], r[2], r[3], r[4]) for r in results]

    def get_free_premium_lines(self) -> list[str]:
        """获取所有免费高级线路列表"""
        configs = self.get_all_configs_by_type("free_premium_line")
        return [key for key, value in configs.items() if value == "1"]

    def set_free_premium_lines(self, lines: list[str]) -> bool:
        """
        设置免费高级线路列表

        Args:
            lines: 线路名称列表

        Returns:
            是否成功
        """
        try:
            # 获取现有的免费线路
            existing_lines = set(self.get_free_premium_lines())
            new_lines = set(lines)

            # 删除不再免费的线路
            for line in existing_lines - new_lines:
                self.delete_system_config("free_premium_line", line)

            # 添加新的免费线路
            for line in new_lines:
                self.set_system_config("free_premium_line", line, "1")

            logger.info(f"设置免费高级线路成功，共 {len(lines)} 条线路")
            return True
        except Exception as e:
            logger.error(f"设置免费高级线路失败: {e!s}")
            return False

    def is_free_premium_line(self, line_name: str) -> bool:
        """检查线路是否为免费高级线路"""
        value = self.get_system_config("free_premium_line", line_name)
        return value == "1"

    def get_line_tags(self, line_name: str) -> list[str]:
        """
        获取线路的标签列表

        Args:
            line_name: 线路名称

        Returns:
            标签列表
        """
        tags_str = self.get_system_config("line_tag", line_name)
        if tags_str:
            tags = tags_str.split(",")
            return [tag.strip() for tag in tags if tag.strip()]
        return []

    def set_line_tags(self, line_name: str, tags: list[str]) -> bool:
        """
        设置线路标签

        Args:
            line_name: 线路名称
            tags: 标签列表

        Returns:
            是否成功
        """
        if not tags:
            # 如果标签为空，删除该配置
            return self.delete_system_config("line_tag", line_name)

        # 去重并转换为逗号分隔的字符串
        tags_str = ",".join(set(tags))
        return self.set_system_config("line_tag", line_name, tags_str)

    def delete_line_tags(self, line_name: str) -> bool:
        """删除线路的所有标签"""
        return self.delete_system_config("line_tag", line_name)

    def get_all_line_tags(self) -> dict:
        """
        获取所有线路的标签

        Returns:
            字典 {line_name: [tags]}
        """
        configs = self.get_all_configs_by_type("line_tag")
        result = {}
        for line_name, tags_str in configs.items():
            tags = tags_str.split(",")
            result[line_name] = [tag.strip() for tag in tags if tag.strip()]
        return result

    def check_line_schedule_unlock(self, tg_id: int, service: str) -> dict:
        """
        检查用户是否解锁了指定服务的线路调度功能

        Args:
            tg_id: 用户的 Telegram ID
            service: 服务类型 (plex/emby)

        Returns:
            dict: {
                'is_unlocked': bool,  # 是否已解锁（包括 premium 自动解锁）
                'is_premium': bool,   # 是否为 premium 用户
                'unlock_time': int,   # 解锁时间戳
            }
        """
        from app.core.telegram import get_user_name_from_tg_id

        try:
            with get_session() as session:
                is_premium = False
                unlock_time = None

                if service == "plex":
                    # 检查 Plex 用户状态
                    stmt = select(
                        PlexUser.is_premium,
                        PlexUser.premium_expiry_time,
                        PlexUser.line_schedule_unlocked,
                        PlexUser.line_schedule_unlock_time,
                    ).where(PlexUser.tg_id == tg_id)
                    result = session.execute(stmt).fetchone()

                    if result:
                        # 检查 premium 状态
                        if result[0] == 1:
                            # premium_expiry_time 为空表示永久 premium
                            if not result[1]:
                                is_premium = True
                            else:
                                # 有过期时间，检查是否过期
                                expiry = datetime.fromisoformat(result[1])
                                if expiry > datetime.now(settings.TZ):
                                    is_premium = True

                        # 检查解锁状态
                        if result[2] == 1:
                            unlock_time = result[3]

                elif service == "emby":
                    # 检查 Emby 用户状态
                    stmt = select(
                        EmbyUser.is_premium,
                        EmbyUser.premium_expiry_time,
                        EmbyUser.line_schedule_unlocked,
                        EmbyUser.line_schedule_unlock_time,
                    ).where(EmbyUser.tg_id == tg_id)
                    result = session.execute(stmt).fetchone()

                    if result:
                        # 检查 premium 状态
                        if result[0] == 1:
                            # premium_expiry_time 为空表示永久 premium
                            if not result[1]:
                                is_premium = True
                            else:
                                # 有过期时间，检查是否过期
                                expiry = datetime.fromisoformat(result[1])
                                if expiry > datetime.now(settings.TZ):
                                    is_premium = True

                        # 检查解锁状态
                        if result[2] == 1:
                            unlock_time = result[3]

                # Premium 用户或已解锁用户都算已解锁
                is_unlocked = is_premium or (unlock_time is not None)

                return {
                    "is_unlocked": is_unlocked,
                    "is_premium": is_premium,
                    "unlock_time": unlock_time,
                }

        except Exception as e:
            logger.error(
                f"检查用户 {get_user_name_from_tg_id(tg_id)} 的 {service} 线路调度解锁状态失败: {e}"
            )
            return {"is_unlocked": False, "is_premium": False, "unlock_time": None}

    def unlock_line_schedule_with_credit(
        self, tg_id: int, service: str, cost: float
    ) -> bool:
        """Unlock line scheduling and charge the account in one transaction."""
        with get_session() as session:
            mutation = credits_repository.deduct_tx(
                session, CreditAccount.tg(int(tg_id)), cost
            )
            if service == "plex":
                stmt = (
                    update(PlexUser)
                    .where(PlexUser.tg_id == tg_id)
                    .values(
                        line_schedule_unlocked=1,
                        line_schedule_unlock_time=int(time.time()),
                    )
                )
            elif service == "emby":
                stmt = (
                    update(EmbyUser)
                    .where(EmbyUser.tg_id == tg_id)
                    .values(
                        line_schedule_unlocked=1,
                        line_schedule_unlock_time=int(time.time()),
                    )
                )
            else:
                raise ValueError(f"未知的服务类型: {service}")
            result = session.execute(stmt)
            if result.rowcount != 1:
                raise ValueError(f"用户未绑定 {service} 账户")
            credits_service.register_cache_invalidation(session, mutation)
            return True

    def unlock_line_schedule(self, tg_id: int, service: str) -> bool:
        """
        解锁用户的线路调度功能

        Args:
            tg_id: 用户的 Telegram ID
            service: 服务类型 (plex/emby)

        Returns:
            是否成功
        """
        from app.core.telegram import get_user_name_from_tg_id

        try:
            with get_session() as session:
                unlock_time = int(time.time())

                if service == "plex":
                    stmt = (
                        update(PlexUser)
                        .where(PlexUser.tg_id == tg_id)
                        .values(
                            line_schedule_unlocked=1,
                            line_schedule_unlock_time=unlock_time,
                        )
                    )
                elif service == "emby":
                    stmt = (
                        update(EmbyUser)
                        .where(EmbyUser.tg_id == tg_id)
                        .values(
                            line_schedule_unlocked=1,
                            line_schedule_unlock_time=unlock_time,
                        )
                    )
                else:
                    logger.error(f"未知的服务类型: {service}")
                    return False

                session.execute(stmt)
                logger.info(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 解锁 {service} 线路调度功能"
                )
                return True

        except Exception as e:
            logger.error(f"解锁 {service} 线路调度功能失败: {e}")
            return False

    def create_line_schedule(
        self,
        tg_id: int,
        service: str,
        line: str,
        days_of_week: list[int],
        start_time: str,
        end_time: str,
        priority: int = 0,
    ) -> int | None:
        """
        创建线路调度

        Args:
            tg_id: 用户的 Telegram ID
            service: 服务类型 (plex/emby)
            line: 线路名称
            days_of_week: 星期几列表 [0-6]
            start_time: 开始时间 HH:MM
            end_time: 结束时间 HH:MM
            priority: 优先级

        Returns:
            创建的调度 ID，失败返回 None
        """
        from app.core.telegram import get_user_name_from_tg_id

        try:
            with get_session() as session:
                schedule = LineSchedule(
                    tg_id=tg_id,
                    service=service,
                    line=line,
                    days_of_week=",".join(map(str, sorted(days_of_week)))
                    if days_of_week
                    else "",
                    start_time=start_time,
                    end_time=end_time,
                    priority=priority,
                    is_enabled=1,
                    created_at=int(time.time()),
                    updated_at=int(time.time()),
                )
                session.add(schedule)
                session.flush()  # 获取 schedule.id

                logger.info(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 创建 {service} 线路调度: {line} "
                    f"({days_of_week}, {start_time}-{end_time})"
                )
                return schedule.id

        except Exception as e:
            logger.error(f"创建线路调度失败: {e}")
            return None

    def get_user_line_schedules(
        self,
        tg_id: int,
        service: str | None = None,
        enabled_only: bool = False,
    ) -> list[dict]:
        """
        获取用户的线路调度列表

        Args:
            tg_id: 用户的 Telegram ID
            service: 服务类型，None 表示获取所有
            enabled_only: 是否只获取启用的调度

        Returns:
            调度列表
        """
        try:
            with get_session() as session:
                stmt = select(LineSchedule).where(LineSchedule.tg_id == tg_id)

                if service:
                    stmt = stmt.where(LineSchedule.service == service)

                if enabled_only:
                    stmt = stmt.where(LineSchedule.is_enabled == 1)

                stmt = stmt.order_by(LineSchedule.priority, LineSchedule.created_at)

                schedules = session.execute(stmt).scalars().all()

                return [
                    {
                        "id": s.id,
                        "service": s.service,
                        "line": s.line,
                        "days_of_week": [int(d) for d in s.days_of_week.split(",")]
                        if s.days_of_week
                        else [],
                        "start_time": s.start_time,
                        "end_time": s.end_time,
                        "priority": s.priority,
                        "is_enabled": s.is_enabled == 1,
                        "created_at": s.created_at,
                        "updated_at": s.updated_at,
                    }
                    for s in schedules
                ]

        except Exception as e:
            logger.error(f"获取用户 {tg_id} 的线路调度列表失败: {e}")
            return []

    def update_line_schedule(self, schedule_id: int, tg_id: int, **kwargs) -> bool:
        """
        更新线路调度

        Args:
            schedule_id: 调度 ID
            tg_id: 用户的 Telegram ID (用于验证权限)
            **kwargs: 要更新的字段

        Returns:
            是否成功
        """
        from app.core.telegram import get_user_name_from_tg_id

        try:
            with get_session() as session:
                schedule = session.execute(
                    select(LineSchedule).where(
                        LineSchedule.id == schedule_id, LineSchedule.tg_id == tg_id
                    )
                ).scalar_one_or_none()

                if not schedule:
                    logger.warning(f"线路调度 {schedule_id} 不存在或无权限")
                    return False

                # 更新字段
                if "line" in kwargs:
                    schedule.line = kwargs["line"]
                if "days_of_week" in kwargs:
                    schedule.days_of_week = ",".join(
                        map(str, sorted(kwargs["days_of_week"]))
                    )
                if "start_time" in kwargs:
                    schedule.start_time = kwargs["start_time"]
                if "end_time" in kwargs:
                    schedule.end_time = kwargs["end_time"]
                if "priority" in kwargs:
                    schedule.priority = kwargs["priority"]
                if "is_enabled" in kwargs:
                    schedule.is_enabled = 1 if kwargs["is_enabled"] else 0

                schedule.updated_at = int(time.time())
                logger.info(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 更新线路调度 {schedule_id}"
                )
                return True

        except Exception as e:
            logger.error(f"更新线路调度 {schedule_id} 失败: {e}")
            return False

    def delete_line_schedule(self, schedule_id: int, tg_id: int) -> bool:
        """
        删除线路调度

        Args:
            schedule_id: 调度 ID
            tg_id: 用户的 Telegram ID (用于验证权限)

        Returns:
            是否成功
        """
        from app.core.telegram import get_user_name_from_tg_id

        try:
            with get_session() as session:
                # 先查询以获取调度信息
                schedule = session.execute(
                    select(LineSchedule).where(
                        LineSchedule.id == schedule_id, LineSchedule.tg_id == tg_id
                    )
                ).scalar_one_or_none()

                if not schedule:
                    logger.warning(f"线路调度 {schedule_id} 不存在或无权限")
                    return False

                # 删除调度
                session.delete(schedule)
                logger.info(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 删除线路调度 {schedule_id}"
                )
                return True

        except Exception as e:
            logger.error(f"删除线路调度 {schedule_id} 失败: {e}")
            return False

    def check_schedule_conflict(
        self,
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
            schedules = self.get_user_line_schedules(tg_id, service, enabled_only=True)

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

    def get_current_active_schedule(self, tg_id: int, service: str) -> dict | None:
        """
        获取当前生效的线路调度

        Args:
            tg_id: 用户的 Telegram ID
            service: 服务类型

        Returns:
            当前生效的调度，没有返回 None
        """
        try:
            now = datetime.now(settings.TZ)
            current_day = now.weekday()  # 0=Monday, 6=Sunday
            current_time = now.strftime("%H:%M")

            def time_to_minutes(t: str) -> int:
                h, m = map(int, t.split(":"))
                return h * 60 + m

            current_minutes = time_to_minutes(current_time)

            schedules = self.get_user_line_schedules(tg_id, service, enabled_only=True)

            # 按优先级排序
            schedules.sort(key=lambda x: x["priority"])

            for schedule in schedules:
                # 检查星期几
                if current_day not in schedule["days_of_week"]:
                    continue

                # 检查时间段
                start_minutes = time_to_minutes(schedule["start_time"])
                end_minutes = time_to_minutes(schedule["end_time"])

                # 处理跨天情况
                if end_minutes <= start_minutes:
                    # 跨天时间段
                    if (
                        current_minutes >= start_minutes
                        or current_minutes < end_minutes
                    ):
                        return schedule
                else:
                    # 同一天时间段
                    if start_minutes <= current_minutes < end_minutes:
                        return schedule

            return None

        except Exception as e:
            logger.error(f"获取当前生效的调度失败: {e}")
            return None

    def disable_schedules_by_line(
        self, line_name: str, only_non_premium: bool = False
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

    def get_users_with_line_schedule(self, line_name: str) -> list[dict]:
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
