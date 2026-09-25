import time
import traceback

from sqlalchemy import delete, select, update
from sqlalchemy.orm import joinedload

from app.core.db import get_session
from app.core.log import logger
from app.domains.badges.models import Badge, UserBadge
from app.domains.identity.models import Statistics


class BadgesRepository:
    @staticmethod
    def _badge_to_dict(badge: Badge) -> dict:
        """将 Badge ORM 对象转换为字典"""
        return {
            "id": badge.id,
            "badge_type": badge.badge_type,
            "name": badge.name,
            "description": badge.description,
            "icon_url": badge.icon_url,
            "credits_cost": badge.credits_cost,
            "bonus_percentage": badge.bonus_percentage,
            "valid_days": badge.valid_days,
            "is_enabled": badge.is_enabled,
            "created_at": badge.created_at,
            "updated_at": badge.updated_at,
        }

    @staticmethod
    def _user_badge_to_dict(user_badge: UserBadge, include_badge: bool = True) -> dict:
        """将 UserBadge ORM 对象转换为字典"""
        current_time = int(time.time())
        bonus_active = user_badge.expires_at > current_time

        result = {
            "id": user_badge.id,
            "tg_id": user_badge.tg_id,
            "badge_id": user_badge.badge_id,
            "credits_cost": user_badge.credits_cost,
            "redeemed_at": user_badge.redeemed_at,
            "expires_at": user_badge.expires_at,
            "is_active": user_badge.is_active,
            "bonus_active": bonus_active,  # 积分加成是否有效
            "badge": None,
        }

        if include_badge and user_badge.badge:
            result["badge"] = BadgesRepository._badge_to_dict(user_badge.badge)

        return result

    def get_badge_center_config(self) -> tuple[bool, str | None]:
        """
        获取勋章中心配置

        Returns:
            (是否启用, 提示信息)
        """
        enabled_str = self.get_system_config("badge_center", "enabled")
        enabled = enabled_str == "1" if enabled_str else False
        message = self.get_system_config("badge_center", "message")
        return enabled, message

    def set_badge_center_config(
        self, enabled: bool, message: str | None = None
    ) -> bool:
        """
        设置勋章中心配置

        Args:
            enabled: 是否启用
            message: 提示信息

        Returns:
            是否成功
        """
        try:
            self.set_system_config("badge_center", "enabled", "1" if enabled else "0")
            if message is not None:
                self.set_system_config("badge_center", "message", message)
            return True
        except Exception as e:
            logger.error(f"设置勋章中心配置失败: {e}")
            return False

    def create_badge(
        self,
        badge_type: str,
        name: str,
        description: str,
        icon_url: str,
        credits_cost: float,
        bonus_percentage: float,
        valid_days: int = 365,
        is_enabled: int = 1,
    ) -> dict | None:
        """
        创建勋章

        Returns:
            Badge字典或None
        """
        try:
            with get_session() as session:
                current_time = int(time.time())
                badge = Badge(
                    badge_type=badge_type,
                    name=name,
                    description=description,
                    icon_url=icon_url,
                    credits_cost=credits_cost,
                    bonus_percentage=bonus_percentage,
                    valid_days=valid_days,
                    is_enabled=is_enabled,
                    created_at=current_time,
                    updated_at=current_time,
                )
                session.add(badge)
                session.flush()  # 刷新以获取 badge 的 ID
                logger.info(f"创建勋章成功: {badge_type}")

                # 转换为字典返回
                return self._badge_to_dict(badge)
        except Exception as e:
            logger.error(f"创建勋章失败: {e}")
            return None

    def get_badge_by_id(self, badge_id: int) -> dict | None:
        """根据ID获取勋章"""
        try:
            with get_session() as session:
                stmt = select(Badge).where(Badge.id == badge_id)
                badge = session.execute(stmt).scalar_one_or_none()

                if not badge:
                    return None

                return self._badge_to_dict(badge)
        except Exception as e:
            logger.error(f"获取勋章失败: {e}")
            return None

    def get_badge_by_type(self, badge_type: str) -> dict | None:
        """根据类型获取勋章"""
        try:
            with get_session() as session:
                stmt = select(Badge).where(Badge.badge_type == badge_type)
                badge = session.execute(stmt).scalar_one_or_none()

                if not badge:
                    return None

                return self._badge_to_dict(badge)
        except Exception as e:
            logger.error(f"获取勋章失败: {e}")
            return None

    def get_all_badges(self, only_enabled: bool = False) -> list[dict]:
        """
        获取所有勋章

        Args:
            only_enabled: 是否只获取启用的勋章

        Returns:
            勋章字典列表
        """
        try:
            with get_session() as session:
                stmt = select(Badge)
                if only_enabled:
                    stmt = stmt.where(Badge.is_enabled == 1)
                stmt = stmt.order_by(Badge.created_at.desc())
                badges = session.execute(stmt).scalars().all()

                return [self._badge_to_dict(badge) for badge in badges]
        except Exception as e:
            logger.error(f"获取勋章列表失败: {e}")
            return []

    def update_badge(
        self,
        badge_id: int,
        **kwargs,
    ) -> bool:
        """
        更新勋章信息

        Args:
            badge_id: 勋章ID
            **kwargs: 要更新的字段

        Returns:
            是否成功
        """
        try:
            with get_session() as session:
                stmt = select(Badge).where(Badge.id == badge_id)
                badge = session.execute(stmt).scalar_one_or_none()
                if not badge:
                    logger.error(f"勋章不存在: {badge_id}")
                    return False

                for key, value in kwargs.items():
                    if hasattr(badge, key) and value is not None:
                        setattr(badge, key, value)

                badge.updated_at = int(time.time())
                logger.info(f"更新勋章成功: {badge_id}")
                return True
        except Exception as e:
            logger.error(f"更新勋章失败: {e}")
            return False

    def delete_badge(self, badge_id: int) -> bool:
        """
        删除勋章

        Args:
            badge_id: 勋章ID

        Returns:
            是否成功
        """
        try:
            with get_session() as session:
                stmt = delete(Badge).where(Badge.id == badge_id)
                result = session.execute(stmt)
                row_count = result.rowcount
                logger.info(f"删除勋章成功: {badge_id}, 影响行数: {row_count}")

            return row_count > 0
        except Exception as e:
            logger.error(f"删除勋章失败: {e}")
            return False

    def redeem_badge(self, tg_id: int, badge_id: int) -> tuple[bool, str, dict | None]:
        """
        兑换勋章

        Args:
            tg_id: 用户TG ID
            badge_id: 勋章ID

        Returns:
            (是否成功, 消息, UserBadge字典或None)
        """
        try:
            with get_session() as session:
                # 1. 检查勋章是否存在且已启用
                badge = session.execute(
                    select(Badge).where(Badge.id == badge_id)
                ).scalar_one_or_none()
                if not badge:
                    return False, "勋章不存在", None
                if badge.is_enabled != 1:
                    return False, "该勋章暂不可兑换", None

                # 2. 检查用户是否已经拥有该勋章
                existing = session.execute(
                    select(UserBadge).where(
                        UserBadge.tg_id == tg_id, UserBadge.badge_id == badge_id
                    )
                ).scalar_one_or_none()
                if existing:
                    return False, "您已经拥有该勋章", None

                # 3. 检查用户积分是否足够
                stats = session.execute(
                    select(Statistics).where(Statistics.tg_id == tg_id)
                ).scalar_one_or_none()

                if not stats:
                    return False, "用户不存在", None

                if stats.credits < badge.credits_cost:
                    return False, f"积分不足，需要 {badge.credits_cost} 积分", None

                # 4. 扣除积分（在同一个事务中）
                new_credits = stats.credits - badge.credits_cost
                session.execute(
                    update(Statistics)
                    .where(Statistics.tg_id == tg_id)
                    .values(credits=new_credits)
                )

                # 5. 创建用户勋章记录
                current_time = int(time.time())
                expires_at = current_time + (badge.valid_days * 24 * 3600)
                user_badge = UserBadge(
                    tg_id=tg_id,
                    badge_id=badge_id,
                    credits_cost=badge.credits_cost,
                    redeemed_at=current_time,
                    expires_at=expires_at,
                    is_active=1,
                )
                session.add(user_badge)
                session.flush()  # 刷新以获取 user_badge 的 ID，但不提交

                # 手动设置 badge 关联以便转换
                user_badge.badge = badge

                # 转换为字典返回
                badge_info = self._user_badge_to_dict(user_badge, include_badge=True)

                logger.info(
                    f"用户 {tg_id} 兑换勋章 {badge.name} 成功，"
                    f"消耗积分 {badge.credits_cost}"
                )

            return True, "兑换成功", badge_info

        except Exception as e:
            logger.error(f"兑换勋章失败: {e}")
            logger.error(traceback.format_exc())
            return False, "兑换失败，请稍后重试", None

    def get_user_badges(self, tg_id: int, only_active: bool = True) -> list[dict]:
        """
        获取用户拥有的勋章

        Args:
            tg_id: 用户TG ID
            only_active: 是否只获取有效的勋章

        Returns:
            用户勋章字典列表
        """
        try:
            with get_session() as session:
                stmt = (
                    select(UserBadge)
                    .options(joinedload(UserBadge.badge))  # 急加载关联的勋章数据
                    .where(UserBadge.tg_id == tg_id)
                    .order_by(UserBadge.redeemed_at.desc())
                )
                if only_active:
                    stmt = stmt.where(UserBadge.is_active == 1)

                user_badges = session.execute(stmt).scalars().unique().all()

                return [self._user_badge_to_dict(ub) for ub in user_badges]
        except Exception as e:
            logger.error(f"获取用户勋章失败: {e}")
            return []

    def get_user_active_badges_with_bonus(self, tg_id: int) -> list[dict]:
        """
        获取用户当前有效的勋章及其加成信息

        Args:
            tg_id: 用户TG ID

        Returns:
            勋章信息列表 [{"badge": dict, "bonus_percentage": float, "expires_at": int}, ...]
        """
        try:
            current_time = int(time.time())
            with get_session() as session:
                stmt = (
                    select(UserBadge)
                    .where(
                        UserBadge.tg_id == tg_id,
                        UserBadge.is_active == 1,
                        UserBadge.expires_at > current_time,
                    )
                    .order_by(UserBadge.redeemed_at.desc())
                )
                user_badges = session.execute(stmt).scalars().all()

                result = []
                for ub in user_badges:
                    badge = session.execute(
                        select(Badge).where(Badge.id == ub.badge_id)
                    ).scalar_one_or_none()
                    if badge:
                        result.append(
                            {
                                "badge": self._badge_to_dict(badge),
                                "bonus_percentage": badge.bonus_percentage,
                                "expires_at": ub.expires_at,
                            }
                        )
                return result
        except Exception as e:
            logger.error(f"获取用户有效勋章失败: {e}")
            return []
