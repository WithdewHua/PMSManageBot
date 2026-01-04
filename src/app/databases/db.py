#!/usr/bin/env python3
"""
ORM-based database operations using SQLAlchemy
"""

import json
import time
import traceback
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from app.config import settings
from app.databases.cache import user_info_cache
from app.databases.session import get_session
from app.log import logger
from app.models.models import (
    AuctionBids,
    Auctions,
    Badge,
    CryptoDonationOrders,
    DonationRegistrations,
    EmbyUser,
    Invitation,
    LineSchedule,
    LineTrafficMonthlyStats,
    LineTrafficStats,
    Overseerr,
    PlexUser,
    Statistics,
    SystemConfig,
    UserBadge,
    VaultwardenRedeemRecords,
    WheelStats,
)
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import joinedload


class DatabaseORM:
    """
    基于 ORM 的数据库操作类
    """

    class _CurWrapper:
        """A tiny compatibility wrapper so existing code that calls
        `db.cur.execute(...).fetchall()` keeps working while we migrate
        everything to ORM/session usage. It translates simple SQL strings
        (including positional `?` params) to SQLAlchemy `text()` calls.
        """

        def __init__(self, parent: "DatabaseORM"):
            self._parent = parent
            self._last_rows = []

        def _prepare(self, query: str, params=None):
            # Convert DB-API positional `?` placeholders to SQLAlchemy named
            # parameters (:p0, :p1, ...). If params is a dict, assume it's
            # already named and pass through.
            from sqlalchemy import text

            if params is None:
                return text(query), None

            # If params is a dict, pass directly
            if isinstance(params, dict):
                return text(query), params

            # Assume sequence/tuple positional params and convert `?` placeholders
            if isinstance(params, (list, tuple)):
                # quick replacement: replace each '?' with :p{i}
                parts = query.split("?")
                if len(parts) - 1 != len(params):
                    # fallback: don't transform, let SQLAlchemy try to bind
                    return text(query), params
                new_query = []
                for i, part in enumerate(parts[:-1]):
                    new_query.append(part)
                    new_query.append(f":p{i}")
                new_query.append(parts[-1])
                named = {f"p{i}": params[i] for i in range(len(params))}
                return text("".join(new_query)), named

            # Unknown param style: pass as-is
            return text(query), params

        def execute(self, query: str, params=None):
            stmt, bound_params = self._prepare(query, params)
            # Use a session to execute; fetch all rows and store them
            try:
                with get_session() as session:
                    if bound_params is not None:
                        res = session.execute(stmt, bound_params)
                    else:
                        res = session.execute(stmt)
                    # SQLAlchemy 1.4+ returns Row objects; convert to tuples
                    rows = res.fetchall()
                    # keep as list of tuples for compatibility
                    self._last_rows = [tuple(r) for r in rows]
            except Exception:
                # On any failure just set empty and re-raise so caller sees it
                self._last_rows = []
                raise
            return self

        def fetchall(self):
            return self._last_rows

        def fetchone(self):
            return self._last_rows[0] if self._last_rows else None

    @property
    def cur(self):
        # Return a long-lived wrapper instance per DatabaseORM instance
        if not hasattr(self, "_cur"):
            self._cur = DatabaseORM._CurWrapper(self)
        return self._cur

    # ==================== Plex User Operations ====================

    def add_plex_user(
        self,
        plex_id: Optional[int] = None,
        tg_id: Optional[int] = None,
        plex_email: Optional[str] = None,
        plex_username: Optional[str] = None,
        credits: float = 0,
        all_lib: int = 0,
        unlock_time: Optional[str] = None,
        watched_time: float = 0,
        plex_line: Optional[str] = None,
        is_premium: int = 0,
        premium_expiry_time: Optional[str] = None,
    ) -> bool:
        """添加 Plex 用户"""
        try:
            with get_session() as session:
                user = PlexUser(
                    plex_id=plex_id,
                    tg_id=tg_id,
                    credits=credits,
                    plex_email=plex_email,
                    plex_username=plex_username,
                    all_lib=all_lib,
                    unlock_time=unlock_time,
                    watched_time=watched_time,
                    plex_line=plex_line,
                    is_premium=is_premium,
                    premium_expiry_time=premium_expiry_time,
                )
                session.add(user)

                # 更新缓存
                if plex_username:
                    user_info_cache.put(
                        f"plex:{plex_username.lower()}",
                        json.dumps(
                            {
                                "plex_id": plex_id,
                                "tg_id": tg_id,
                                "plex_email": plex_email,
                                "plex_username": plex_username,
                                "is_premium": is_premium,
                            }
                        ),
                    )
                return True
        except Exception as e:
            logger.error(f"Error adding plex user: {e}")
            return False

    def delete_plex_user(self, plex_email: str) -> bool:
        """删除 Plex 用户"""
        try:
            with get_session() as session:
                session.execute(
                    delete(PlexUser).where(
                        func.lower(PlexUser.plex_email) == plex_email.lower()
                    )
                )
                return True
        except Exception as e:
            logger.error(f"Error deleting plex user: {e}")
            return False

    def get_plex_users_num(self) -> int:
        """获取 Plex 用户数量"""
        with get_session() as session:
            stmt = select(func.count(PlexUser.plex_id))
            return session.execute(stmt).scalar()

    def get_plex_info_by_tg_id(self, tg_id: int) -> Optional[Tuple]:
        """通过 Telegram ID 获取 Plex 用户信息"""
        with get_session() as session:
            stmt = select(PlexUser).where(PlexUser.tg_id == tg_id)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (
                    user.plex_id,
                    user.tg_id,
                    user.credits,
                    user.plex_email,
                    user.plex_username,
                    user.all_lib,
                    user.unlock_time,
                    user.watched_time,
                    user.plex_line,
                    user.is_premium,
                    user.premium_expiry_time,
                    user.last_viewed_at,
                )
            return None

    def get_plex_info_by_plex_id(self, plex_id: int) -> Optional[Tuple]:
        """通过 Plex ID 获取用户信息"""
        with get_session() as session:
            stmt = select(PlexUser).where(PlexUser.plex_id == plex_id)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (
                    user.plex_id,
                    user.tg_id,
                    user.credits,
                    user.plex_email,
                    user.plex_username,
                    user.all_lib,
                    user.unlock_time,
                    user.watched_time,
                    user.plex_line,
                    user.is_premium,
                    user.premium_expiry_time,
                    user.last_viewed_at,
                )
            return None

    def get_plex_info_by_plex_username(self, plex_username: str) -> Optional[Tuple]:
        """通过 Plex 用户名获取用户信息"""
        with get_session() as session:
            stmt = select(PlexUser).where(
                func.lower(PlexUser.plex_username) == plex_username.lower()
            )
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (
                    user.plex_id,
                    user.tg_id,
                    user.credits,
                    user.plex_email,
                    user.plex_username,
                    user.all_lib,
                    user.unlock_time,
                    user.watched_time,
                    user.plex_line,
                    user.is_premium,
                    user.premium_expiry_time,
                    user.last_viewed_at,
                )
            return None

    def get_plex_info_by_plex_email(self, plex_email: str) -> Optional[Tuple]:
        """通过 Plex 邮箱获取用户信息"""
        with get_session() as session:
            stmt = select(PlexUser).where(
                func.lower(PlexUser.plex_email) == plex_email.lower()
            )
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (
                    user.plex_id,
                    user.tg_id,
                    user.credits,
                    user.plex_email,
                    user.plex_username,
                    user.all_lib,
                    user.unlock_time,
                    user.watched_time,
                    user.plex_line,
                    user.is_premium,
                    user.premium_expiry_time,
                    user.last_viewed_at,
                )
            return None

    # ==================== Emby User Operations ====================

    def add_emby_user(
        self,
        emby_username: str,
        emby_id: Optional[str] = None,
        tg_id: Optional[int] = None,
        emby_is_unlock: int = 0,
        emby_unlock_time: Optional[int] = None,
        emby_watched_time: float = 0,
        emby_credits: float = 0,
        emby_line: Optional[str] = None,
        is_premium: int = 0,
        premium_expiry_time: Optional[str] = None,
    ) -> bool:
        """添加 Emby 用户"""
        try:
            with get_session() as session:
                user = EmbyUser(
                    emby_username=emby_username,
                    emby_id=emby_id,
                    tg_id=tg_id,
                    emby_is_unlock=emby_is_unlock,
                    emby_unlock_time=emby_unlock_time,
                    emby_watched_time=emby_watched_time,
                    emby_credits=emby_credits,
                    emby_line=emby_line,
                    is_premium=is_premium,
                    premium_expiry_time=premium_expiry_time,
                )
                session.add(user)

                # 更新缓存
                user_info_cache.put(
                    f"emby:{emby_username.lower()}",
                    json.dumps(
                        {
                            "emby_id": emby_id,
                            "tg_id": tg_id,
                            "emby_username": emby_username,
                            "is_premium": is_premium,
                        }
                    ),
                )
                return True
        except Exception as e:
            logger.error(f"Error adding emby user: {e}")
            return False

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

    def get_emby_info_by_emby_username(self, username: str) -> Optional[Tuple]:
        """通过 Emby 用户名获取用户信息"""
        with get_session() as session:
            stmt = select(EmbyUser).where(
                func.lower(EmbyUser.emby_username) == username.lower()
            )
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (
                    user.emby_username,
                    user.emby_id,
                    user.tg_id,
                    user.emby_is_unlock,
                    user.emby_unlock_time,
                    user.emby_watched_time,
                    user.emby_credits,
                    user.emby_line,
                    user.is_premium,
                    user.premium_expiry_time,
                    user.last_viewed_at,
                )
            return None

    def get_emby_info_by_tg_id(self, tg_id: int) -> Optional[Tuple]:
        """通过 Telegram ID 获取 Emby 用户信息"""
        with get_session() as session:
            stmt = select(EmbyUser).where(EmbyUser.tg_id == tg_id)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (
                    user.emby_username,
                    user.emby_id,
                    user.tg_id,
                    user.emby_is_unlock,
                    user.emby_unlock_time,
                    user.emby_watched_time,
                    user.emby_credits,
                    user.emby_line,
                    user.is_premium,
                    user.premium_expiry_time,
                    user.last_viewed_at,
                )
            return None

    def get_emby_info_by_emby_id(self, emby_id: str) -> Optional[Tuple]:
        """通过 Emby ID 获取用户信息"""
        with get_session() as session:
            stmt = select(EmbyUser).where(EmbyUser.emby_id == emby_id)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (
                    user.emby_username,
                    user.emby_id,
                    user.tg_id,
                    user.emby_is_unlock,
                    user.emby_unlock_time,
                    user.emby_watched_time,
                    user.emby_credits,
                    user.emby_line,
                    user.is_premium,
                    user.premium_expiry_time,
                    user.last_viewed_at,
                )
            return None

    # ==================== Statistics Operations ====================

    def add_user_data(
        self, tg_id: int, credits: float = 0, donation: float = 0
    ) -> bool:
        """添加用户统计数据"""
        try:
            with get_session() as session:
                stats = Statistics(tg_id=tg_id, credits=credits, donation=donation)
                session.add(stats)
                return True
        except Exception as e:
            logger.error(f"Error adding user data: {e}")
            return False

    def get_stats_by_tg_id(self, tg_id: int) -> Optional[Tuple]:
        """通过 Telegram ID 获取统计信息"""
        with get_session() as session:
            stmt = select(Statistics).where(Statistics.tg_id == tg_id)
            stats = session.execute(stmt).scalar_one_or_none()
            if stats:
                return (stats.tg_id, stats.donation, stats.credits)
            return None

    def get_user_credits(self, tg_id: int) -> Optional[float]:
        """获取用户积分"""
        with get_session() as session:
            stmt = select(Statistics).where(Statistics.tg_id == tg_id)
            stats = session.execute(stmt).scalar_one_or_none()
            return stats.credits if stats else None

    def update_user_donation(self, donation: float, tg_id: int) -> bool:
        """更新用户捐赠金额"""
        try:
            with get_session() as session:
                session.execute(
                    update(Statistics)
                    .where(Statistics.tg_id == tg_id)
                    .values(donation=donation)
                )
                return True
        except Exception as e:
            logger.error(f"Error updating user donation: {e}")
            return False

    # ==================== Invitation Operations ====================

    def add_invitation_code(
        self, code: str, owner: int, is_used: int = 0, used_by: Optional[int] = None
    ) -> bool:
        """添加邀请码"""
        try:
            with get_session() as session:
                invitation = Invitation(
                    code=code, owner=owner, is_used=is_used, used_by=used_by
                )
                session.add(invitation)
                return True
        except Exception as e:
            logger.error(f"Error adding invitation code: {e}")
            return False

    def update_invitation_status(self, code: str, used_by: int) -> bool:
        """更新邀请码状态"""
        try:
            with get_session() as session:
                session.execute(
                    update(Invitation)
                    .where(Invitation.code == code)
                    .values(is_used=1, used_by=used_by)
                )
                return True
        except Exception as e:
            logger.error(f"Error updating invitation status: {e}")
            return False

    # ==================== Overseerr Operations ====================

    def add_overseerr_user(self, user_id: int, user_email: str, tg_id: int) -> bool:
        """添加 Overseerr 用户"""
        try:
            with get_session() as session:
                user = Overseerr(user_id=user_id, user_email=user_email, tg_id=tg_id)
                session.add(user)
                return True
        except Exception as e:
            logger.error(f"Error adding overseerr user: {e}")
            return False

    def get_overseerr_info_by_tg_id(self, tg_id: int) -> Optional[Tuple]:
        """通过 Telegram ID 获取 Overseerr 用户信息"""
        with get_session() as session:
            stmt = select(Overseerr).where(Overseerr.tg_id == tg_id)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (user.user_id, user.user_email, user.tg_id)
            return None

    # ==================== Update Operations ====================

    def update_user_tg_id(
        self, tg_id: int, plex_id: Optional[int] = None, emby_id: Optional[str] = None
    ) -> bool:
        """更新用户 Telegram ID"""
        try:
            with get_session() as session:
                if plex_id is not None:
                    session.execute(
                        update(PlexUser)
                        .where(PlexUser.plex_id == plex_id)
                        .values(tg_id=tg_id)
                    )
                if emby_id is not None:
                    session.execute(
                        update(EmbyUser)
                        .where(EmbyUser.emby_id == emby_id)
                        .values(tg_id=tg_id)
                    )
                return True
        except Exception as e:
            logger.error(f"Error updating user tg_id: {e}")
            return False

    def update_user_credits(
        self,
        credits: float,
        plex_id: Optional[int] = None,
        emby_id: Optional[str] = None,
        tg_id: Optional[int] = None,
    ) -> bool:
        """更新用户积分"""
        try:
            with get_session() as session:
                if tg_id is not None:
                    session.execute(
                        update(Statistics)
                        .where(Statistics.tg_id == tg_id)
                        .values(credits=credits)
                    )
                elif plex_id is not None:
                    session.execute(
                        update(PlexUser)
                        .where(PlexUser.plex_id == plex_id)
                        .values(credits=credits)
                    )
                elif emby_id is not None:
                    session.execute(
                        update(EmbyUser)
                        .where(EmbyUser.emby_id == emby_id)
                        .values(emby_credits=credits)
                    )
                else:
                    logger.error("Error: there is no enough params")
                    return False
                return True
        except Exception as e:
            logger.error(f"Error updating user credits: {e}")
            return False

    def update_all_lib_flag(
        self,
        all_lib: int,
        unlock_time: Optional[str] = None,
        plex_id: Optional[int] = None,
        emby_id: Optional[str] = None,
        tg_id: Optional[int] = None,
        media_server: str = "plex",
    ) -> bool:
        """更新全库权限标志"""
        try:
            with get_session() as session:
                if media_server.lower() == "plex":
                    if plex_id is not None:
                        session.execute(
                            update(PlexUser)
                            .where(PlexUser.plex_id == plex_id)
                            .values(all_lib=all_lib, unlock_time=unlock_time)
                        )
                    elif tg_id is not None:
                        session.execute(
                            update(PlexUser)
                            .where(PlexUser.tg_id == tg_id)
                            .values(all_lib=all_lib, unlock_time=unlock_time)
                        )
                elif media_server.lower() == "emby":
                    if emby_id is not None:
                        session.execute(
                            update(EmbyUser)
                            .where(EmbyUser.emby_id == emby_id)
                            .values(
                                emby_is_unlock=all_lib, emby_unlock_time=unlock_time
                            )
                        )
                    elif tg_id is not None:
                        session.execute(
                            update(EmbyUser)
                            .where(EmbyUser.tg_id == tg_id)
                            .values(
                                emby_is_unlock=all_lib, emby_unlock_time=unlock_time
                            )
                        )
                else:
                    logger.error("Error: please specify correct media server")
                    return False
                return True
        except Exception as e:
            logger.error(f"Error updating all_lib_flag: {e}")
            return False

    def get_overseerr_info_by_email(self, email: str) -> Optional[Tuple]:
        """通过邮箱获取 Overseerr 用户信息"""
        with get_session() as session:
            stmt = select(Overseerr).where(Overseerr.user_email == email)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (user.user_id, user.user_email, user.tg_id)
            return None

    # ==================== Rank Operations ====================

    def get_credits_rank(self) -> list:
        """获取积分排行"""
        with get_session() as session:
            stmt = select(Statistics.tg_id, Statistics.credits).order_by(
                Statistics.credits.desc()
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1]) for r in results]

    def get_donation_rank(self) -> list:
        """获取捐赠排行"""
        with get_session() as session:
            stmt = select(Statistics.tg_id, Statistics.donation).order_by(
                Statistics.donation.desc()
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1]) for r in results]

    def get_plex_watched_time_rank(self) -> list:
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
            return [(r[0], r[1], r[2], r[3], r[4]) for r in results]

    def get_emby_watched_time_rank(self) -> list:
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
            return [(r[0], r[1], r[2], r[3], r[4]) for r in results]

    def get_invitation_rank(self) -> list:
        """获取邀请排行榜数据"""
        with get_session() as session:
            stmt = (
                select(
                    Invitation.owner,
                    func.count(func.distinct(Invitation.used_by)).label("invite_count"),
                )
                .where(Invitation.is_used == 1, Invitation.used_by.isnot(None))
                .group_by(Invitation.owner)
                .order_by(func.count(func.distinct(Invitation.used_by)).desc())
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1]) for r in results]

    # ==================== Invitation Query Operations ====================

    def verify_invitation_code_is_used(self, code: str) -> Optional[Tuple]:
        """验证邀请码是否已使用"""
        with get_session() as session:
            stmt = select(Invitation.is_used, Invitation.owner).where(
                Invitation.code == code
            )
            result = session.execute(stmt).fetchone()
            return (result[0], result[1]) if result else None

    def get_invitation_code_by_owner(
        self, tg_id: int, is_available: bool = True
    ) -> list:
        """获取用户的邀请码"""
        with get_session() as session:
            if is_available:
                stmt = select(Invitation.code).where(
                    Invitation.owner == tg_id, Invitation.is_used == 0
                )
            else:
                stmt = select(Invitation.code).where(Invitation.owner == tg_id)
            results = session.execute(stmt).fetchall()
            return [r[0] for r in results]

    def get_invitee_count_by_owner(self, tg_id: int) -> int:
        """获取用户邀请的人数"""
        try:
            with get_session() as session:
                stmt = select(func.count(func.distinct(Invitation.used_by))).where(
                    Invitation.owner == tg_id,
                    Invitation.is_used == 1,
                    Invitation.used_by.isnot(None),
                )
                count = session.execute(stmt).scalar()
                return count if count else 0
        except Exception as e:
            logger.error(f"获取邀请人数失败: {e}")
            return 0

    # ==================== Line Management Operations ====================

    def set_emby_line(
        self, line: str, tg_id: Optional[int] = None, emby_id: Optional[str] = None
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

    def get_emby_line(self, tg_id: int) -> Optional[str]:
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
                EmbyUser.emby_line,
                EmbyUser.is_premium,
            ).where(EmbyUser.emby_line.isnot(None))
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1], r[2], r[3]) for r in results]

    def set_plex_line(
        self, line: str, tg_id: Optional[int] = None, plex_id: Optional[int] = None
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

    def get_plex_line(self, tg_id: int) -> Optional[str]:
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
                PlexUser.plex_line,
                PlexUser.is_premium,
            ).where(PlexUser.plex_line.isnot(None))
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1], r[2], r[3]) for r in results]

    # ==================== Wheel Operations ====================

    def add_wheel_spin_record(
        self, tg_id: int, item_name: str, credits_change: float
    ) -> bool:
        """记录转盘旋转记录"""
        try:
            with get_session() as session:
                timestamp = int(time.time())
                date = datetime.now(settings.TZ).strftime("%Y-%m-%d")

                wheel_record = WheelStats(
                    tg_id=tg_id,
                    item_name=item_name,
                    credits_change=credits_change,
                    timestamp=timestamp,
                    date=date,
                )
                session.add(wheel_record)
                return True
        except Exception as e:
            logger.error(f"Error adding wheel spin record: {e}")
            return False

    def get_wheel_stats(self) -> dict:
        """获取转盘统计数据"""
        try:
            with get_session() as session:
                today = datetime.now(settings.TZ).strftime("%Y-%m-%d")
                week_ago = (datetime.now(settings.TZ) - timedelta(days=7)).strftime(
                    "%Y-%m-%d"
                )

                # 总抽奖次数
                total_spins = session.execute(
                    select(func.count(WheelStats.id))
                ).scalar()

                # 参与用户数（去重）
                active_users = session.execute(
                    select(func.count(func.distinct(WheelStats.tg_id)))
                ).scalar()

                # 今日抽奖次数
                today_spins = session.execute(
                    select(func.count(WheelStats.id)).where(WheelStats.date == today)
                ).scalar()

                # 本周抽奖次数
                week_spins = session.execute(
                    select(func.count(WheelStats.id)).where(WheelStats.date >= week_ago)
                ).scalar()

                # 转盘总积分变化
                total_credits_change = (
                    session.execute(
                        select(func.sum(WheelStats.credits_change))
                    ).scalar()
                    or 0.0
                )

                # 总邀请码发放数
                total_invite_codes = (
                    session.execute(
                        select(func.count(WheelStats.id)).where(
                            WheelStats.item_name == "邀请码 1 枚"
                        )
                    ).scalar()
                    or 0
                )

                return {
                    "totalSpins": total_spins,
                    "activeUsers": active_users,
                    "todaySpins": today_spins,
                    "lastWeekSpins": week_spins,
                    "totalCreditsChange": float(total_credits_change),
                    "totalInviteCodes": total_invite_codes,
                }
        except Exception as e:
            logger.error(f"Error getting wheel stats: {e}")
            return {
                "totalSpins": 0,
                "activeUsers": 0,
                "todaySpins": 0,
                "lastWeekSpins": 0,
                "totalCreditsChange": 0.0,
                "totalInviteCodes": 0,
            }

    def get_user_wheel_stats(self, tg_id: int) -> dict:
        """获取用户个人转盘统计数据"""
        try:
            with get_session() as session:
                today = datetime.now(settings.TZ).strftime("%Y-%m-%d")
                week_ago = (datetime.now(settings.TZ) - timedelta(days=7)).strftime(
                    "%Y-%m-%d"
                )

                # 用户今日游戏次数
                today_spins = session.execute(
                    select(func.count(WheelStats.id)).where(
                        WheelStats.tg_id == tg_id, WheelStats.date == today
                    )
                ).scalar()

                # 用户总游戏次数
                total_spins = session.execute(
                    select(func.count(WheelStats.id)).where(WheelStats.tg_id == tg_id)
                ).scalar()

                # 用户本周游戏次数
                week_spins = session.execute(
                    select(func.count(WheelStats.id)).where(
                        WheelStats.tg_id == tg_id, WheelStats.date >= week_ago
                    )
                ).scalar()

                # 用户总积分变化
                total_credits_change = (
                    session.execute(
                        select(func.sum(WheelStats.credits_change)).where(
                            WheelStats.tg_id == tg_id
                        )
                    ).scalar()
                    or 0.0
                )

                # 用户今日积分变化
                today_credits_change = (
                    session.execute(
                        select(func.sum(WheelStats.credits_change)).where(
                            WheelStats.tg_id == tg_id, WheelStats.date == today
                        )
                    ).scalar()
                    or 0.0
                )

                # 用户本周积分变化
                week_credits_change = (
                    session.execute(
                        select(func.sum(WheelStats.credits_change)).where(
                            WheelStats.tg_id == tg_id, WheelStats.date >= week_ago
                        )
                    ).scalar()
                    or 0.0
                )

                # 用户获得的邀请码数量
                invite_codes_earned = session.execute(
                    select(func.count(WheelStats.id)).where(
                        WheelStats.tg_id == tg_id, WheelStats.item_name == "邀请码 1 枚"
                    )
                ).scalar()

                # 用户今日获得的邀请码数量
                today_invite_codes = session.execute(
                    select(func.count(WheelStats.id)).where(
                        WheelStats.tg_id == tg_id,
                        WheelStats.item_name == "邀请码 1 枚",
                        WheelStats.date == today,
                    )
                ).scalar()

                # 用户本周获得的邀请码数量
                week_invite_codes = session.execute(
                    select(func.count(WheelStats.id)).where(
                        WheelStats.tg_id == tg_id,
                        WheelStats.item_name == "邀请码 1 枚",
                        WheelStats.date >= week_ago,
                    )
                ).scalar()

                # 最近5次游戏记录
                stmt = (
                    select(
                        WheelStats.item_name,
                        WheelStats.credits_change,
                        WheelStats.date,
                        WheelStats.timestamp,
                    )
                    .where(WheelStats.tg_id == tg_id)
                    .order_by(WheelStats.timestamp.desc())
                    .limit(5)
                )
                recent_games_result = session.execute(stmt).fetchall()

                recent_games_list = [
                    {
                        "item_name": game[0],
                        "credits_change": game[1],
                        "date": game[2],
                        "timestamp": game[3],
                    }
                    for game in recent_games_result
                ]

                return {
                    "today_spins": today_spins,
                    "total_spins": total_spins,
                    "week_spins": week_spins,
                    "total_credits_change": float(total_credits_change),
                    "today_credits_change": float(today_credits_change),
                    "week_credits_change": float(week_credits_change),
                    "total_invite_codes": invite_codes_earned,
                    "today_invite_codes": today_invite_codes,
                    "week_invite_codes": week_invite_codes,
                    "recent_games": recent_games_list,
                }
        except Exception as e:
            logger.error(f"Error getting user wheel stats: {e}")
            return {
                "today_spins": 0,
                "total_spins": 0,
                "week_spins": 0,
                "total_credits_change": 0.0,
                "today_credits_change": 0.0,
                "week_credits_change": 0.0,
                "total_invite_codes": 0,
                "today_invite_codes": 0,
                "week_invite_codes": 0,
                "recent_games": [],
            }

    # ==================== Premium Operations ====================

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

        with get_session() as session:
            # 更新 Plex 用户
            plex_result = session.execute(
                update(PlexUser)
                .where(
                    PlexUser.is_premium == 1,
                    PlexUser.premium_expiry_time.isnot(None),
                    PlexUser.premium_expiry_time < current_time,
                )
                .values(is_premium=0, premium_expiry_time=None)
            )

            # 更新 Emby 用户
            emby_result = session.execute(
                update(EmbyUser)
                .where(
                    EmbyUser.is_premium == 1,
                    EmbyUser.premium_expiry_time.isnot(None),
                    EmbyUser.premium_expiry_time < current_time,
                )
                .values(is_premium=0, premium_expiry_time=None)
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

    # ==================== Auction Operations ====================

    def create_auction(
        self,
        title: str,
        description: str,
        starting_price: float,
        end_time: int,
        created_by: int,
    ) -> Optional[int]:
        """创建竞拍"""
        try:
            with get_session() as session:
                created_at = int(time.time())
                auction = Auctions(
                    title=title,
                    description=description,
                    starting_price=starting_price,
                    current_price=starting_price,
                    end_time=end_time,
                    created_by=created_by,
                    created_at=created_at,
                )
                session.add(auction)
                return auction.id
        except Exception as e:
            logger.error(f"Error creating auction: {e}")
            return None

    def get_auction_by_id(self, auction_id: int) -> Optional[dict]:
        """根据ID获取竞拍信息"""
        try:
            with get_session() as session:
                stmt = select(Auctions).where(Auctions.id == auction_id)
                auction = session.execute(stmt).scalar_one_or_none()

                if auction:
                    return {
                        "id": auction.id,
                        "title": auction.title or f"竞拍活动 #{auction.id}",
                        "description": auction.description or "无描述",
                        "starting_price": auction.starting_price or 0,
                        "current_price": auction.current_price
                        or auction.starting_price
                        or 0,
                        "end_time": auction.end_time,
                        "created_by": auction.created_by,
                        "created_at": auction.created_at,
                        "is_active": auction.is_active,
                        "winner_id": auction.winner_id,
                        "bid_count": auction.bid_count,
                    }
                return None
        except Exception as e:
            logger.error(f"Error getting auction by id: {e}")
            return None

    def get_active_auctions(self, limit: int = 50) -> List[dict]:
        """获取活跃竞拍列表"""
        try:
            with get_session() as session:
                current_time = int(time.time())
                stmt = (
                    select(Auctions)
                    .where(Auctions.is_active == 1, Auctions.end_time > current_time)
                    .order_by(Auctions.created_at.desc())
                    .limit(limit)
                )
                results = session.execute(stmt).scalars().all()

                auctions = []
                for auction in results:
                    auctions.append(
                        {
                            "id": auction.id,
                            "title": auction.title or f"竞拍活动 #{auction.id}",
                            "description": auction.description or "无描述",
                            "starting_price": auction.starting_price or 0,
                            "current_price": auction.current_price
                            or auction.starting_price
                            or 0,
                            "end_time": auction.end_time,
                            "created_by": auction.created_by,
                            "created_at": auction.created_at,
                            "is_active": auction.is_active,
                            "winner_id": auction.winner_id,
                            "bid_count": auction.bid_count,
                        }
                    )
                return auctions
        except Exception as e:
            logger.error(f"Error getting active auctions: {e}")
            return []

    def place_bid(self, auction_id: int, bidder_id: int, bid_amount: float) -> bool:
        """出价"""
        try:
            with get_session() as session:
                bid_time = int(time.time())

                # 检查竞拍是否存在且活跃
                auction = session.execute(
                    select(Auctions).where(Auctions.id == auction_id)
                ).scalar_one_or_none()

                if not auction or not auction.is_active or auction.end_time <= bid_time:
                    return False

                # 检查出价是否高于当前价格
                if bid_amount <= auction.current_price:
                    return False

                # 插入出价记录
                bid = AuctionBids(
                    auction_id=auction_id,
                    bidder_id=bidder_id,
                    bid_amount=bid_amount,
                    bid_time=bid_time,
                )
                session.add(bid)

                # 更新竞拍当前价格和出价次数
                session.execute(
                    update(Auctions)
                    .where(Auctions.id == auction_id)
                    .values(current_price=bid_amount, bid_count=Auctions.bid_count + 1)
                )
                return True
        except Exception as e:
            logger.error(f"Error placing bid: {e}")
            return False

    def get_auction_bids(self, auction_id: int, limit: int = 50) -> List[dict]:
        """获取竞拍出价记录"""
        try:
            with get_session() as session:
                stmt = (
                    select(AuctionBids)
                    .where(AuctionBids.auction_id == auction_id)
                    .order_by(AuctionBids.bid_time.desc())
                    .limit(limit)
                )
                results = session.execute(stmt).scalars().all()

                bids = []
                for bid in results:
                    bids.append(
                        {
                            "id": bid.id,
                            "auction_id": bid.auction_id,
                            "bidder_id": bid.bidder_id,
                            "bid_amount": bid.bid_amount,
                            "bid_time": bid.bid_time,
                        }
                    )
                return bids
        except Exception as e:
            logger.error(f"Error getting auction bids: {e}")
            return []

    def get_user_highest_bid(self, auction_id: int, user_id: int) -> Optional[float]:
        """获取用户在特定竞拍中的最高出价"""
        try:
            with get_session() as session:
                stmt = select(func.max(AuctionBids.bid_amount)).where(
                    AuctionBids.auction_id == auction_id,
                    AuctionBids.bidder_id == user_id,
                )
                result = session.execute(stmt).scalar()
                return result
        except Exception as e:
            logger.error(f"Error getting user highest bid: {e}")
            return None

    def get_auction_participants(
        self, auction_id: int, exclude_user_id: Optional[int] = None
    ) -> List[int]:
        """获取拍卖的所有参与者（出价者）ID列表，可排除指定用户"""
        try:
            with get_session() as session:
                if exclude_user_id:
                    stmt = select(func.distinct(AuctionBids.bidder_id)).where(
                        AuctionBids.auction_id == auction_id,
                        AuctionBids.bidder_id != exclude_user_id,
                    )
                else:
                    stmt = select(func.distinct(AuctionBids.bidder_id)).where(
                        AuctionBids.auction_id == auction_id
                    )
                results = session.execute(stmt).scalars().all()
                return list(results)
        except Exception as e:
            logger.error(f"Error getting auction participants: {e}")
            return []

    def finish_expired_auctions(self) -> List[dict]:
        """结束过期的竞拍"""
        try:
            with get_session() as session:
                current_time = int(time.time())

                # 查找过期的活跃竞拍
                stmt = select(Auctions).where(
                    Auctions.is_active == 1, Auctions.end_time <= current_time
                )
                expired_auctions = session.execute(stmt).scalars().all()

                finished_auctions = []
                for auction in expired_auctions:
                    auction_id = auction.id

                    # 获取最高出价者
                    highest_bid_stmt = (
                        select(AuctionBids.bidder_id, func.max(AuctionBids.bid_amount))
                        .where(AuctionBids.auction_id == auction_id)
                        .group_by(AuctionBids.auction_id)
                    )
                    highest_bid = session.execute(highest_bid_stmt).fetchone()

                    winner_id = highest_bid[0] if highest_bid else None
                    final_price = auction.current_price
                    credits_reduced = False

                    # 如果有获胜者，扣除其积分
                    if winner_id and highest_bid:
                        final_price = highest_bid[1]

                        # 获取用户当前积分
                        stats = session.execute(
                            select(Statistics).where(Statistics.tg_id == winner_id)
                        ).scalar_one_or_none()

                        if stats and stats.credits >= final_price:
                            session.execute(
                                update(Statistics)
                                .where(Statistics.tg_id == winner_id)
                                .values(credits=Statistics.credits - final_price)
                            )
                            credits_reduced = True
                            logger.info(
                                f"Auction {auction_id} finished: deducted {final_price} credits from winner {winner_id}"
                            )
                        else:
                            logger.warning(
                                f"Winner {winner_id} has insufficient credits for auction {auction_id} (price: {final_price})"
                            )

                    # 更新竞拍状态
                    session.execute(
                        update(Auctions)
                        .where(Auctions.id == auction_id)
                        .values(
                            is_active=0, winner_id=winner_id, current_price=final_price
                        )
                    )

                    finished_auctions.append(
                        {
                            "id": auction_id,
                            "title": auction.title or f"竞拍活动 #{auction_id}",
                            "winner_id": winner_id,
                            "final_price": final_price,
                            "credits_reduced": credits_reduced,
                        }
                    )
                return finished_auctions
        except Exception as e:
            logger.error(f"Error finishing expired auctions: {e}")
            logger.error(traceback.format_exc())
            return []

    def get_auction_stats(self) -> dict:
        """获取竞拍统计数据"""
        try:
            with get_session() as session:
                current_time = int(time.time())

                # 总竞拍数
                total_auctions = session.execute(
                    select(func.count(Auctions.id))
                ).scalar()

                # 活跃竞拍数
                active_auctions = session.execute(
                    select(func.count(Auctions.id)).where(
                        Auctions.is_active == 1, Auctions.end_time > current_time
                    )
                ).scalar()

                # 总出价数
                total_bids = session.execute(
                    select(func.count(AuctionBids.id))
                ).scalar()

                # 总成交价值
                total_value = (
                    session.execute(
                        select(func.sum(Auctions.current_price)).where(
                            Auctions.winner_id.isnot(None)
                        )
                    ).scalar()
                    or 0.0
                )

                return {
                    "total_auctions": total_auctions,
                    "active_auctions": active_auctions,
                    "total_bids": total_bids,
                    "total_value": float(total_value),
                }
        except Exception as e:
            logger.error(f"Error getting auction stats: {e}")
            return {
                "total_auctions": 0,
                "active_auctions": 0,
                "total_bids": 0,
                "total_value": 0.0,
            }

    def get_all_auctions(
        self, status: Optional[str] = None, limit: int = 50, offset: int = 0
    ) -> List[dict]:
        """获取所有竞拍活动（管理员用）"""
        try:
            with get_session() as session:
                current_time = int(time.time())

                if status == "active":
                    stmt = (
                        select(Auctions)
                        .where(
                            Auctions.is_active == 1, Auctions.end_time > current_time
                        )
                        .order_by(Auctions.created_at.desc())
                        .limit(limit)
                        .offset(offset)
                    )
                elif status == "ended":
                    stmt = (
                        select(Auctions)
                        .where(
                            (Auctions.is_active == 0)
                            | (Auctions.end_time <= current_time)
                        )
                        .order_by(Auctions.created_at.desc())
                        .limit(limit)
                        .offset(offset)
                    )
                else:
                    stmt = (
                        select(Auctions)
                        .order_by(Auctions.created_at.desc())
                        .limit(limit)
                        .offset(offset)
                    )

                results = session.execute(stmt).scalars().all()

                auctions = []
                for auction in results:
                    # 获取出价数量
                    bid_count = session.execute(
                        select(func.count(AuctionBids.id)).where(
                            AuctionBids.auction_id == auction.id
                        )
                    ).scalar()

                    # 判断状态
                    if not auction.is_active:
                        auction_status = "ended"
                    elif auction.end_time <= current_time:
                        auction_status = "ended"
                    else:
                        auction_status = "active"

                    auctions.append(
                        {
                            "id": auction.id,
                            "title": auction.title or f"竞拍活动 #{auction.id}",
                            "description": auction.description or "无描述",
                            "starting_price": auction.starting_price or 0,
                            "current_price": auction.current_price
                            or auction.starting_price
                            or 0,
                            "end_time": auction.end_time,
                            "created_by": auction.created_by,
                            "created_at": auction.created_at,
                            "is_active": bool(auction.is_active),
                            "winner_id": auction.winner_id,
                            "bid_count": bid_count,
                            "status": auction_status,
                        }
                    )

                return auctions
        except Exception as e:
            logger.error(f"Error getting all auctions: {e}")
            return []

    def update_auction(self, auction_id: int, update_data: dict) -> bool:
        """更新竞拍活动"""
        try:
            with get_session() as session:
                values_to_update = {}

                if "title" in update_data:
                    values_to_update["title"] = update_data["title"]
                if "description" in update_data:
                    values_to_update["description"] = update_data["description"]
                if "starting_price" in update_data:
                    values_to_update["starting_price"] = update_data["starting_price"]
                if "end_time" in update_data:
                    values_to_update["end_time"] = update_data["end_time"]

                if not values_to_update:
                    return False

                result = session.execute(
                    update(Auctions)
                    .where(Auctions.id == auction_id)
                    .values(**values_to_update)
                )
                return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating auction: {e}")
            return False

    def delete_auction(self, auction_id: int) -> bool:
        """删除竞拍活动"""
        try:
            with get_session() as session:
                # 先删除相关的出价记录
                session.execute(
                    delete(AuctionBids).where(AuctionBids.auction_id == auction_id)
                )

                # 再删除竞拍活动
                result = session.execute(
                    delete(Auctions).where(Auctions.id == auction_id)
                )
                return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting auction: {e}")
            return False

    def finish_auction_by_id(self, auction_id: int) -> tuple:
        """手动结束指定竞拍活动"""
        try:
            with get_session() as session:
                # 获取竞拍信息
                auction = session.execute(
                    select(Auctions).where(Auctions.id == auction_id)
                ).scalar_one_or_none()

                if not auction:
                    return False, f"竞拍 id {auction_id} 不存在"

                # 获取最高出价
                highest_bid_stmt = (
                    select(AuctionBids.bidder_id, AuctionBids.bid_amount)
                    .where(AuctionBids.auction_id == auction_id)
                    .order_by(AuctionBids.bid_amount.desc())
                    .limit(1)
                )
                highest_bid = session.execute(highest_bid_stmt).fetchone()

                winner_id = None
                final_price = auction.starting_price
                credits_reduced = False

                if highest_bid:
                    winner_id = highest_bid[0]
                    final_price = highest_bid[1]

                    # 扣除获胜者的积分
                    stats = session.execute(
                        select(Statistics).where(Statistics.tg_id == winner_id)
                    ).scalar_one_or_none()

                    if stats and stats.credits >= final_price:
                        session.execute(
                            update(Statistics)
                            .where(Statistics.tg_id == winner_id)
                            .values(credits=Statistics.credits - final_price)
                        )
                        credits_reduced = True

                # 更新竞拍状态
                session.execute(
                    update(Auctions)
                    .where(Auctions.id == auction_id)
                    .values(is_active=0, winner_id=winner_id, current_price=final_price)
                )
                return True, {
                    "id": auction_id,
                    "title": auction.title,
                    "winner_id": winner_id,
                    "final_price": final_price,
                    "credits_reduced": credits_reduced,
                }

        except Exception as e:
            logger.error(f"Error finishing auction {auction_id}: {e}")
            logger.error(traceback.format_exc())
            return False, str(e)

    def get_user_auction_history(self, user_id: int, limit: int = 20) -> List[dict]:
        """获取用户参与的竞拍历史"""
        try:
            with get_session() as session:
                # 获取用户参与的竞拍
                stmt = (
                    select(Auctions)
                    .join(AuctionBids, Auctions.id == AuctionBids.auction_id)
                    .where(AuctionBids.bidder_id == user_id)
                    .order_by(Auctions.created_at.desc())
                    .limit(limit)
                    .distinct()
                )
                results = session.execute(stmt).scalars().all()

                auctions = []
                for auction in results:
                    # 获取用户最高出价
                    highest_bid = session.execute(
                        select(func.max(AuctionBids.bid_amount)).where(
                            AuctionBids.auction_id == auction.id,
                            AuctionBids.bidder_id == user_id,
                        )
                    ).scalar()

                    auctions.append(
                        {
                            "id": auction.id,
                            "title": auction.title or f"竞拍活动 #{auction.id}",
                            "description": auction.description or "无描述",
                            "starting_price": auction.starting_price or 0,
                            "current_price": auction.current_price
                            or auction.starting_price
                            or 0,
                            "end_time": auction.end_time,
                            "created_by": auction.created_by,
                            "created_at": auction.created_at,
                            "is_active": bool(auction.is_active),
                            "winner_id": auction.winner_id,
                            "user_highest_bid": highest_bid,
                            "is_winner": auction.winner_id == user_id,
                        }
                    )

                return auctions
        except Exception as e:
            logger.error(f"Error getting user auction history: {e}")
            return []

    def get_detailed_auction_stats(
        self, start_date: Optional[int] = None, end_date: Optional[int] = None
    ) -> dict:
        """获取详细的竞拍统计数据"""
        try:
            with get_session() as session:
                # 设置默认时间范围（如果未提供）
                if not start_date:
                    start_date = 0
                if not end_date:
                    end_date = int(time.time())

                # 基本统计
                stats = self.get_auction_stats()

                # 时间段内的统计
                period_auctions = session.execute(
                    select(func.count(Auctions.id)).where(
                        Auctions.created_at.between(start_date, end_date)
                    )
                ).scalar()

                # 时间段内的出价数
                period_bids = session.execute(
                    select(func.count(AuctionBids.id))
                    .join(Auctions, AuctionBids.auction_id == Auctions.id)
                    .where(Auctions.created_at.between(start_date, end_date))
                ).scalar()

                # 平均出价数
                avg_bids = (
                    session.execute(
                        select(func.avg(func.count(AuctionBids.id))).group_by(
                            AuctionBids.auction_id
                        )
                    ).scalar()
                    or 0.0
                )

                # 最高成交价
                highest_price = (
                    session.execute(
                        select(func.max(Auctions.current_price)).where(
                            Auctions.winner_id.isnot(None)
                        )
                    ).scalar()
                    or 0.0
                )

                stats.update(
                    {
                        "period_auctions": period_auctions,
                        "period_bids": period_bids,
                        "avg_bids_per_auction": float(avg_bids),
                        "highest_transaction": float(highest_price),
                        "start_date": start_date,
                        "end_date": end_date,
                    }
                )

                return stats
        except Exception as e:
            logger.error(f"Error getting detailed auction stats: {e}")
            return self.get_auction_stats()

    # ==================== Traffic Statistics Operations ====================

    def create_line_traffic_entry(
        self,
        line: str,
        send_bytes: int,
        service: str,
        username: str,
        user_id: str,
        timestamp: str,
        request_uri: Optional[str] = None,
        upstream: Optional[str] = None,
        upstream_response_time: Optional[str] = None,
    ) -> bool:
        """创建流量统计记录"""
        try:
            with get_session() as session:
                traffic_entry = LineTrafficStats(
                    line=line,
                    send_bytes=send_bytes,
                    service=service,
                    username=username,
                    user_id=user_id,
                    timestamp=timestamp,
                    request_uri=request_uri,
                    upstream=upstream,
                    upstream_response_time=upstream_response_time,
                )
                session.add(traffic_entry)
                return True
        except Exception as e:
            logger.error(f"Error creating line traffic entry: {e}")
            return False

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
        username: Optional[str] = None,
        user_id: Optional[str] = None,
        service: str = None,
        date: datetime = None,
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

            # 判断查询日期是否为当月
            now = datetime.now(settings.TZ)
            current_month_start = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )

            if date >= current_month_start:
                # 当月数据，从 line_traffic_stats 表查询
                with get_session() as session:
                    # 构建基本查询条件
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

                    # 如果只统计 premium 线路
                    if premium_only:
                        premium_lines = settings.PREMIUM_STREAM_BACKEND
                        if premium_lines:
                            conditions.append(LineTrafficStats.line.in_(premium_lines))
                        else:
                            # 如果没有配置 premium 线路，返回 0
                            return 0

                    result = session.execute(
                        select(
                            func.coalesce(func.sum(LineTrafficStats.send_bytes), 0)
                        ).where(*conditions)
                    ).scalar()

                    return result if result else 0
            else:
                # 历史月份数据，从 line_traffic_monthly_stats 表查询
                # 注意：月度表只有月度总计，无法精确到天，返回 0
                logger.warning(
                    f"无法获取历史日期 {date.strftime('%Y-%m-%d')} 的精确日流量数据"
                )
                return 0

        except Exception as e:
            logger.error(
                f"Error getting user daily traffic for {username or user_id}: {e}"
            )
            return 0

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
                    }

                    for service, traffic in service_results:
                        if service.lower() == "emby":
                            period_data["emby"] = traffic
                        elif service.lower() == "plex":
                            period_data["plex"] = traffic

                    # 添加线路数据
                    for line, traffic in line_results:
                        # 排除自定义线路，只统计已知的线路
                        for _line in (
                            settings.STREAM_BACKEND + settings.PREMIUM_STREAM_BACKEND
                        ):
                            if line.lower() in _line.lower():
                                period_data["lines"].append(
                                    {"line": line, "traffic": traffic}
                                )
                                break

                    result[period_name] = period_data

            return result

        except Exception as e:
            logger.error(f"Error getting comprehensive traffic statistics: {e}")
            return {
                "today": {"total": 0, "emby": 0, "plex": 0, "lines": []},
                "week": {"total": 0, "emby": 0, "plex": 0, "lines": []},
                "month": {"total": 0, "emby": 0, "plex": 0, "lines": []},
            }

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
                if start_date < current_month_start:
                    start_date = current_month_start

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
                if end_date > today_end:
                    end_date = today_end

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
                if start_date < current_month_start:
                    start_date = current_month_start

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
                if end_date > today_end:
                    end_date = today_end

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

    def aggregate_monthly_traffic_data(self, target_month: str = None) -> tuple:
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
                datetime.strptime(target_month, "%Y-%m")
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
                    line, service, username, user_id, total_bytes, record_count = record

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
                    f"成功聚合 {target_month} 月份数据: 插入了 {insert_count} 条新记录，"
                    f"更新了 {update_count} 条记录，跳过了 {skip_count} 条重复记录",
                )

        except Exception as e:
            logger.error(f"聚合月度流量数据失败: {e}")
            return False, f"聚合月度流量数据失败: {str(e)}"

    def cleanup_monthly_traffic_data(self, target_month: str) -> tuple:
        """清理已聚合月份的原始流量数据"""
        try:
            # 验证月份格式
            try:
                datetime.strptime(target_month, "%Y-%m")
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
            return False, f"清理月度流量数据失败: {str(e)}"

    def update_traffic_username(self, old_username: str, new_username: str) -> bool:
        """更新流量统计中的用户名"""
        try:
            with get_session() as session:
                # 更新 line_traffic_stats 表
                session.execute(
                    update(LineTrafficStats)
                    .where(
                        func.lower(LineTrafficStats.username) == old_username.lower()
                    )
                    .values(username=new_username)
                )
                # 更新 line_traffic_monthly_stats 表
                session.execute(
                    update(LineTrafficMonthlyStats)
                    .where(
                        func.lower(LineTrafficMonthlyStats.username)
                        == old_username.lower()
                    )
                    .values(username=new_username)
                )
                return True
        except Exception as e:
            logger.error(f"更新流量统计用户名失败: {e}")
            return False

    # ==================== Donation Management Operations ====================

    def create_donation_registration(
        self,
        user_id: int,
        payment_method: str,
        amount: float,
        note: str = None,
        is_donation_registration: bool = False,
    ) -> bool:
        """创建捐赠登记记录"""
        try:
            with get_session() as session:
                created_at = datetime.now(settings.TZ).isoformat()

                # 确保统计信息存在以通过外键校验
                stats_exists = session.execute(
                    select(Statistics.tg_id).where(Statistics.tg_id == user_id)
                ).scalar_one_or_none()
                if not stats_exists:
                    session.add(Statistics(tg_id=user_id, credits=0, donation=0))
                    session.flush()

                donation = DonationRegistrations(
                    user_id=user_id,
                    payment_method=payment_method,
                    amount=amount,
                    note=note,
                    created_at=created_at,
                    is_donation_registration=int(is_donation_registration),
                )
                session.add(donation)
                return True
        except Exception as e:
            logger.error(f"创建捐赠登记失败: {e}")
            return False

    def get_donation_registration_by_id(self, registration_id: int) -> Optional[dict]:
        """根据ID获取捐赠登记信息"""
        try:
            from app.utils.utils import get_user_name_from_tg_id

            with get_session() as session:
                stmt = select(DonationRegistrations).where(
                    DonationRegistrations.id == registration_id
                )
                result = session.execute(stmt).scalar_one_or_none()

                if result:
                    user_id = result.user_id
                    processed_by = result.processed_by

                    return {
                        "id": result.id,
                        "user_id": user_id,
                        "payment_method": result.payment_method,
                        "amount": result.amount,
                        "note": result.note,
                        "status": result.status,
                        "admin_note": result.admin_note,
                        "created_at": result.created_at,
                        "processed_at": result.processed_at,
                        "processed_by": processed_by,
                        "is_donation_registration": bool(
                            result.is_donation_registration
                        ),
                        "username": get_user_name_from_tg_id(user_id),
                        "processed_by_username": get_user_name_from_tg_id(processed_by)
                        if processed_by
                        else None,
                    }
                return None
        except Exception as e:
            logger.error(f"获取捐赠登记信息失败: {e}")
            return None

    def get_donation_registrations_by_user(
        self, user_id: int, limit: int = 20
    ) -> List[dict]:
        """获取用户的捐赠登记历史"""
        try:
            from app.utils.utils import get_user_name_from_tg_id

            with get_session() as session:
                stmt = (
                    select(DonationRegistrations)
                    .where(DonationRegistrations.user_id == user_id)
                    .order_by(DonationRegistrations.created_at.desc())
                    .limit(limit)
                )
                results = session.execute(stmt).scalars().all()

                registrations = []
                for result in results:
                    user_id_result = result.user_id
                    processed_by = result.processed_by

                    registrations.append(
                        {
                            "id": result.id,
                            "user_id": user_id_result,
                            "payment_method": result.payment_method,
                            "amount": result.amount,
                            "note": result.note,
                            "status": result.status,
                            "admin_note": result.admin_note,
                            "created_at": result.created_at,
                            "processed_at": result.processed_at,
                            "processed_by": processed_by,
                            "is_donation_registration": bool(
                                result.is_donation_registration
                            ),
                            "username": get_user_name_from_tg_id(user_id_result),
                            "processed_by_username": get_user_name_from_tg_id(
                                processed_by
                            )
                            if processed_by
                            else None,
                        }
                    )
                return registrations
        except Exception as e:
            logger.error(f"获取用户捐赠登记历史失败: {e}")
            return []

    def get_pending_donation_registrations(self, limit: int = 50) -> List[dict]:
        """获取待处理的捐赠登记列表"""
        try:
            from app.utils.utils import get_user_name_from_tg_id

            with get_session() as session:
                stmt = (
                    select(DonationRegistrations)
                    .where(DonationRegistrations.status == "pending")
                    .order_by(DonationRegistrations.created_at.asc())
                    .limit(limit)
                )
                results = session.execute(stmt).scalars().all()

                registrations = []
                for result in results:
                    user_id = result.user_id
                    processed_by = result.processed_by

                    registrations.append(
                        {
                            "id": result.id,
                            "user_id": user_id,
                            "payment_method": result.payment_method,
                            "amount": result.amount,
                            "note": result.note,
                            "status": result.status,
                            "admin_note": result.admin_note,
                            "created_at": result.created_at,
                            "processed_at": result.processed_at,
                            "processed_by": processed_by,
                            "is_donation_registration": bool(
                                result.is_donation_registration
                            ),
                            "username": get_user_name_from_tg_id(user_id),
                            "processed_by_username": get_user_name_from_tg_id(
                                processed_by
                            )
                            if processed_by
                            else None,
                        }
                    )
                return registrations
        except Exception as e:
            logger.error(f"获取待处理捐赠登记失败: {e}")
            return []

    def confirm_donation_registration(
        self,
        registration_id: int,
        approved: bool,
        admin_note: str = None,
        processed_by: int = None,
    ) -> bool:
        """确认捐赠登记状态"""
        try:
            with get_session() as session:
                processed_at = datetime.now(settings.TZ).isoformat()
                status = "approved" if approved else "rejected"

                session.execute(
                    update(DonationRegistrations)
                    .where(DonationRegistrations.id == registration_id)
                    .values(
                        status=status,
                        admin_note=admin_note,
                        processed_at=processed_at,
                        processed_by=processed_by,
                    )
                )
                return True
        except Exception as e:
            logger.error(f"确认捐赠登记失败: {e}")
            return False

    def delete_donation_registration(self, registration_id: int) -> bool:
        """删除捐赠登记记录"""
        try:
            with get_session() as session:
                session.execute(
                    delete(DonationRegistrations).where(
                        DonationRegistrations.id == registration_id
                    )
                )
                return True
        except Exception as e:
            logger.error(f"删除捐赠登记失败: {e}")
            return False

    def get_donation_statistics(self) -> dict:
        """获取捐赠统计信息"""
        try:
            with get_session() as session:
                # 总登记数
                total_registrations = session.execute(
                    select(func.count(DonationRegistrations.id))
                ).scalar()

                # 待处理数
                pending_registrations = session.execute(
                    select(func.count(DonationRegistrations.id)).where(
                        DonationRegistrations.status == "pending"
                    )
                ).scalar()

                # 已批准数
                approved_registrations = session.execute(
                    select(func.count(DonationRegistrations.id)).where(
                        DonationRegistrations.status == "approved"
                    )
                ).scalar()

                # 已拒绝数
                rejected_registrations = session.execute(
                    select(func.count(DonationRegistrations.id)).where(
                        DonationRegistrations.status == "rejected"
                    )
                ).scalar()

                # 总捐赠金额（已批准的）
                total_amount = session.execute(
                    select(func.sum(DonationRegistrations.amount)).where(
                        DonationRegistrations.status == "approved"
                    )
                ).scalar()
                total_amount = float(total_amount) if total_amount else 0.0

                return {
                    "total_registrations": total_registrations,
                    "pending_registrations": pending_registrations,
                    "approved_registrations": approved_registrations,
                    "rejected_registrations": rejected_registrations,
                    "total_approved_amount": total_amount,
                }
        except Exception as e:
            logger.error(f"获取捐赠统计信息失败: {e}")
            return {
                "total_registrations": 0,
                "pending_registrations": 0,
                "approved_registrations": 0,
                "rejected_registrations": 0,
                "total_approved_amount": 0.0,
            }

    # ==================== Crypto Donation Orders Operations ====================

    def create_crypto_donation_order(
        self,
        user_id: int,
        order_id: str,
        crypto_type: str,
        amount: float,
        note: str = None,
    ) -> bool:
        """创建 crypto 捐赠订单"""
        try:
            # 验证加密货币类型是否支持
            if crypto_type not in settings.UPAY_CRYPTO_TYPES:
                logger.error(f"不支持的加密货币类型: {crypto_type}")
                return False

            with get_session() as session:
                created_at = datetime.now(settings.TZ).isoformat()

                order = CryptoDonationOrders(
                    user_id=user_id,
                    order_id=order_id,
                    crypto_type=crypto_type,
                    amount=amount,
                    created_at=created_at,
                    note=note,
                )
                session.add(order)
                return True
        except Exception as e:
            logger.error(f"创建 crypto 捐赠订单失败: {e}")
            return False

    def update_crypto_donation_order_upay_info(
        self,
        order_id: str,
        trade_id: str,
        actual_amount: float,
        payment_address: str,
        payment_url: str,
        expiration_time: int,
    ) -> bool:
        """更新 crypto 捐赠订单的 UPAY 信息"""
        try:
            with get_session() as session:
                updated_at = datetime.now(settings.TZ).isoformat()

                session.execute(
                    update(CryptoDonationOrders)
                    .where(CryptoDonationOrders.order_id == order_id)
                    .values(
                        trade_id=trade_id,
                        actual_amount=actual_amount,
                        payment_address=payment_address,
                        payment_url=payment_url,
                        expiration_time=expiration_time,
                        updated_at=updated_at,
                    )
                )
                return True
        except Exception as e:
            logger.error(f"更新 crypto 捐赠订单 UPAY 信息失败: {e}")
            return False

    def complete_crypto_donation_order(
        self,
        trade_id: str,
        block_transaction_id: str,
        actual_amount: float,
    ) -> bool:
        """完成 crypto 捐赠订单支付"""
        try:
            with get_session() as session:
                paid_at = datetime.now(settings.TZ).isoformat()
                updated_at = paid_at

                session.execute(
                    update(CryptoDonationOrders)
                    .where(CryptoDonationOrders.trade_id == trade_id)
                    .values(
                        status=2,
                        block_transaction_id=block_transaction_id,
                        actual_amount=actual_amount,
                        paid_at=paid_at,
                        updated_at=updated_at,
                    )
                )
                return True
        except Exception as e:
            logger.error(f"完成 crypto 捐赠订单支付失败: {e}")
            return False

    def get_crypto_donation_order_by_order_id(self, order_id: str) -> Optional[dict]:
        """根据订单ID获取 crypto 捐赠订单"""
        try:
            with get_session() as session:
                stmt = select(CryptoDonationOrders).where(
                    CryptoDonationOrders.order_id == order_id
                )
                result = session.execute(stmt).scalar_one_or_none()

                if result:
                    return {
                        "id": result.id,
                        "user_id": result.user_id,
                        "order_id": result.order_id,
                        "trade_id": result.trade_id,
                        "crypto_type": result.crypto_type,
                        "amount": result.amount,
                        "actual_amount": result.actual_amount,
                        "payment_address": result.payment_address,
                        "block_transaction_id": result.block_transaction_id,
                        "status": result.status,
                        "payment_url": result.payment_url,
                        "expiration_time": result.expiration_time,
                        "created_at": result.created_at,
                        "updated_at": result.updated_at,
                        "paid_at": result.paid_at,
                        "note": result.note,
                    }
                return None
        except Exception as e:
            logger.error(f"获取 crypto 捐赠订单失败: {e}")
            return None

    def get_crypto_donation_order_by_trade_id(self, trade_id: str) -> Optional[dict]:
        """根据交易ID获取 crypto 捐赠订单"""
        try:
            with get_session() as session:
                stmt = select(CryptoDonationOrders).where(
                    CryptoDonationOrders.trade_id == trade_id
                )
                result = session.execute(stmt).scalar_one_or_none()

                if result:
                    return {
                        "id": result.id,
                        "user_id": result.user_id,
                        "order_id": result.order_id,
                        "trade_id": result.trade_id,
                        "crypto_type": result.crypto_type,
                        "amount": result.amount,
                        "actual_amount": result.actual_amount,
                        "payment_address": result.payment_address,
                        "block_transaction_id": result.block_transaction_id,
                        "status": result.status,
                        "payment_url": result.payment_url,
                        "expiration_time": result.expiration_time,
                        "created_at": result.created_at,
                        "updated_at": result.updated_at,
                        "paid_at": result.paid_at,
                        "note": result.note,
                    }
                return None
        except Exception as e:
            logger.error(f"获取 crypto 捐赠订单失败: {e}")
            return None

    def get_crypto_donation_orders_by_user(
        self, user_id: int, limit: int = 20
    ) -> List[dict]:
        """获取用户的 crypto 捐赠订单历史"""
        try:
            with get_session() as session:
                stmt = (
                    select(CryptoDonationOrders)
                    .where(CryptoDonationOrders.user_id == user_id)
                    .order_by(CryptoDonationOrders.created_at.desc())
                    .limit(limit)
                )
                results = session.execute(stmt).scalars().all()

                orders = []
                for result in results:
                    orders.append(
                        {
                            "id": result.id,
                            "user_id": result.user_id,
                            "order_id": result.order_id,
                            "trade_id": result.trade_id,
                            "crypto_type": result.crypto_type,
                            "amount": result.amount,
                            "actual_amount": result.actual_amount,
                            "payment_address": result.payment_address,
                            "block_transaction_id": result.block_transaction_id,
                            "status": result.status,
                            "payment_url": result.payment_url,
                            "expiration_time": result.expiration_time,
                            "created_at": result.created_at,
                            "updated_at": result.updated_at,
                            "paid_at": result.paid_at,
                            "note": result.note,
                        }
                    )
                return orders
        except Exception as e:
            logger.error(f"获取用户 crypto 捐赠订单历史失败: {e}")
            return []

    def get_all_crypto_donation_orders(
        self, limit: int = 100, offset: int = 0, status_filter: str = None
    ) -> List[dict]:
        """获取所有 crypto 捐赠订单历史（管理员用）"""
        try:
            with get_session() as session:
                # 构建查询
                stmt = select(CryptoDonationOrders)

                # 添加状态过滤
                if status_filter and status_filter in ["0", "1", "2", "3"]:
                    stmt = stmt.where(CryptoDonationOrders.status == int(status_filter))

                # 排序和分页
                stmt = (
                    stmt.order_by(CryptoDonationOrders.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )

                results = session.execute(stmt).scalars().all()

                orders = []
                for result in results:
                    orders.append(
                        {
                            "id": result.id,
                            "user_id": result.user_id,
                            "order_id": result.order_id,
                            "trade_id": result.trade_id,
                            "crypto_type": result.crypto_type,
                            "amount": result.amount,
                            "actual_amount": result.actual_amount,
                            "payment_address": result.payment_address,
                            "block_transaction_id": result.block_transaction_id,
                            "status": result.status,
                            "payment_url": result.payment_url,
                            "expiration_time": result.expiration_time,
                            "created_at": result.created_at,
                            "updated_at": result.updated_at,
                            "paid_at": result.paid_at,
                            "note": result.note,
                        }
                    )
                return orders
        except Exception as e:
            logger.error(f"获取所有 crypto 捐赠订单历史失败: {e}")
            return []

    def get_crypto_donation_orders_count(self, status_filter: str = None) -> int:
        """获取 crypto 捐赠订单总数（管理员用）"""
        try:
            with get_session() as session:
                # 构建查询
                stmt = select(func.count(CryptoDonationOrders.id))

                # 添加状态过滤
                if status_filter and status_filter in ["0", "1", "2", "3"]:
                    stmt = stmt.where(CryptoDonationOrders.status == int(status_filter))

                result = session.execute(stmt).scalar()
                return result if result else 0
        except Exception as e:
            logger.error(f"获取 crypto 捐赠订单总数失败: {e}")
            return 0

    def get_expired_crypto_donation_orders(self) -> List[dict]:
        """获取所有已过期但状态仍为等待支付的 crypto 捐赠订单"""
        try:
            with get_session() as session:
                current_time = int(time.time() * 1000)  # 当前时间的毫秒时间戳

                stmt = (
                    select(CryptoDonationOrders)
                    .where(
                        CryptoDonationOrders.status == 1,
                        CryptoDonationOrders.expiration_time.isnot(None),
                        CryptoDonationOrders.expiration_time <= current_time,
                    )
                    .order_by(CryptoDonationOrders.created_at.asc())
                )
                results = session.execute(stmt).scalars().all()

                expired_orders = []
                for result in results:
                    expired_orders.append(
                        {
                            "id": result.id,
                            "user_id": result.user_id,
                            "order_id": result.order_id,
                            "trade_id": result.trade_id,
                            "crypto_type": result.crypto_type,
                            "amount": result.amount,
                            "actual_amount": result.actual_amount,
                            "payment_address": result.payment_address,
                            "block_transaction_id": result.block_transaction_id,
                            "status": result.status,
                            "payment_url": result.payment_url,
                            "expiration_time": result.expiration_time,
                            "created_at": result.created_at,
                            "updated_at": result.updated_at,
                            "paid_at": result.paid_at,
                            "note": result.note,
                        }
                    )
                return expired_orders
        except Exception as e:
            logger.error(f"获取过期 crypto 捐赠订单失败: {e}")
            return []

    def update_expired_crypto_donation_orders(self) -> int:
        """批量更新已过期的 crypto 捐赠订单状态为已过期(3)"""
        try:
            with get_session() as session:
                current_time = int(time.time() * 1000)  # 当前时间的毫秒时间戳
                updated_at = datetime.now(settings.TZ).isoformat()

                # 更新所有过期的订单状态
                result = session.execute(
                    update(CryptoDonationOrders)
                    .where(
                        CryptoDonationOrders.status == 1,
                        CryptoDonationOrders.expiration_time.isnot(None),
                        CryptoDonationOrders.expiration_time <= current_time,
                    )
                    .values(status=3, updated_at=updated_at)
                )
                updated_count = result.rowcount

                if updated_count > 0:
                    logger.info(
                        f"成功更新 {updated_count} 个过期的 crypto 捐赠订单状态"
                    )

                return updated_count
        except Exception as e:
            logger.error(f"更新过期 crypto 捐赠订单状态失败: {e}")
            return 0

    # ============================================================
    # SystemConfig 配置管理相关方法
    # ============================================================

    def get_system_config(self, config_type: str, config_key: str) -> Optional[str]:
        """
        获取系统配置

        Args:
            config_type: 配置类型 (free_premium_line, line_tag, lucky_wheel)
            config_key: 配置键

        Returns:
            配置值，如果不存在返回 None
        """
        try:
            with get_session() as session:
                stmt = select(SystemConfig.config_value).where(
                    SystemConfig.config_type == config_type,
                    SystemConfig.config_key == config_key,
                )
                result = session.execute(stmt).scalar_one_or_none()
                return result
        except Exception as e:
            logger.error(
                f"获取系统配置失败 (type={config_type}, key={config_key}): {str(e)}"
            )
            return None

    def set_system_config(
        self, config_type: str, config_key: str, config_value: str
    ) -> bool:
        """
        设置系统配置（更新或插入）

        Args:
            config_type: 配置类型
            config_key: 配置键
            config_value: 配置值

        Returns:
            是否成功
        """
        try:
            current_time = int(time.time())
            with get_session() as session:
                # 尝试查找现有配置
                stmt = select(SystemConfig).where(
                    SystemConfig.config_type == config_type,
                    SystemConfig.config_key == config_key,
                )
                existing_config = session.execute(stmt).scalar_one_or_none()

                if existing_config:
                    # 更新现有配置
                    existing_config.config_value = config_value
                    existing_config.updated_at = current_time
                else:
                    # 插入新配置
                    new_config = SystemConfig(
                        config_type=config_type,
                        config_key=config_key,
                        config_value=config_value,
                        created_at=current_time,
                        updated_at=current_time,
                    )
                    session.add(new_config)

                logger.info(f"设置系统配置成功 (type={config_type}, key={config_key})")
                return True
        except Exception as e:
            logger.error(
                f"设置系统配置失败 (type={config_type}, key={config_key}): {str(e)}"
            )
            return False

    def delete_system_config(self, config_type: str, config_key: str) -> bool:
        """
        删除系统配置

        Args:
            config_type: 配置类型
            config_key: 配置键

        Returns:
            是否成功
        """
        try:
            with get_session() as session:
                stmt = select(SystemConfig).where(
                    SystemConfig.config_type == config_type,
                    SystemConfig.config_key == config_key,
                )
                config = session.execute(stmt).scalar_one_or_none()

                if config:
                    session.delete(config)
                    logger.info(
                        f"删除系统配置成功 (type={config_type}, key={config_key})"
                    )
                    return True
                else:
                    logger.info(
                        f"系统配置不存在 (type={config_type}, key={config_key})"
                    )
                    return True
        except Exception as e:
            logger.error(
                f"删除系统配置失败 (type={config_type}, key={config_key}): {str(e)}"
            )
            return False

    def get_all_configs_by_type(self, config_type: str) -> dict:
        """
        获取指定类型的所有配置

        Args:
            config_type: 配置类型

        Returns:
            配置字典 {config_key: config_value}
        """
        try:
            with get_session() as session:
                stmt = select(SystemConfig.config_key, SystemConfig.config_value).where(
                    SystemConfig.config_type == config_type
                )
                results = session.execute(stmt).all()
                return {row[0]: row[1] for row in results}
        except Exception as e:
            logger.error(f"获取所有配置失败 (type={config_type}): {str(e)}")
            return {}

    # ============================================================
    # 免费高级线路相关方法
    # ============================================================

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
            logger.error(f"设置免费高级线路失败: {str(e)}")
            return False

    def is_free_premium_line(self, line_name: str) -> bool:
        """检查线路是否为免费高级线路"""
        value = self.get_system_config("free_premium_line", line_name)
        return value == "1"

    # ============================================================
    # 线路标签相关方法
    # ============================================================

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

    # ============================================================
    # 幸运大转盘配置相关方法
    # ============================================================

    def get_lucky_wheel_config(self, config_key: str = "config") -> Optional[str]:
        """
        获取幸运大转盘配置

        Args:
            config_key: 配置键 (config 或 randomness_config)

        Returns:
            配置的 JSON 字符串
        """
        return self.get_system_config("lucky_wheel", config_key)

    def set_lucky_wheel_config(self, config_key: str, config_json: str) -> bool:
        """
        设置幸运大转盘配置

        Args:
            config_key: 配置键 (config 或 randomness_config)
            config_json: 配置的 JSON 字符串

        Returns:
            是否成功
        """
        return self.set_system_config("lucky_wheel", config_key, config_json)

    # ============================================================
    # 线路调度功能相关方法
    # ============================================================

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
        from app.utils.utils import get_user_name_from_tg_id

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

    def unlock_line_schedule(self, tg_id: int, service: str) -> bool:
        """
        解锁用户的线路调度功能

        Args:
            tg_id: 用户的 Telegram ID
            service: 服务类型 (plex/emby)

        Returns:
            是否成功
        """
        from app.utils.utils import get_user_name_from_tg_id

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
        days_of_week: List[int],
        start_time: str,
        end_time: str,
        priority: int = 0,
    ) -> Optional[int]:
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
        from app.utils.utils import get_user_name_from_tg_id

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
        service: Optional[str] = None,
        enabled_only: bool = False,
    ) -> List[dict]:
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
        from app.utils.utils import get_user_name_from_tg_id

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
        from app.utils.utils import get_user_name_from_tg_id

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
        days_of_week: List[int],
        start_time: str,
        end_time: str,
        exclude_id: Optional[int] = None,
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

    def get_current_active_schedule(self, tg_id: int, service: str) -> Optional[dict]:
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

    def disable_schedules_by_line(self, line_name: str) -> tuple[bool, int, List[dict]]:
        """
        禁用指定线路的所有调度，并返回受影响的用户信息

        Args:
            line_name: 线路名称

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

                # 统计受影响的用户（在禁用前）
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

                # 禁用所有调度
                count = 0
                current_time = int(time.time())
                for schedule in schedules:
                    schedule.is_enabled = 0
                    schedule.updated_at = current_time
                    count += 1

                affected_users = list(user_service_map.values())
                logger.info(
                    f"已禁用 {count} 个使用线路 {line_name} 的调度，"
                    f"影响 {len(affected_users)} 位用户"
                )
                return True, count, affected_users

        except Exception as e:
            logger.error(f"禁用线路 {line_name} 的调度失败: {e}")
            return False, 0, []

    def get_users_with_line_schedule(self, line_name: str) -> List[dict]:
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

    # ==================== Badge Management ====================

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
            result["badge"] = DatabaseORM._badge_to_dict(user_badge.badge)

        return result

    def get_badge_center_config(self) -> Tuple[bool, Optional[str]]:
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
        self, enabled: bool, message: Optional[str] = None
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
    ) -> Optional[dict]:
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

    def get_badge_by_id(self, badge_id: int) -> Optional[dict]:
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

    def get_badge_by_type(self, badge_type: str) -> Optional[dict]:
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

    def get_all_badges(self, only_enabled: bool = False) -> List[dict]:
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

    def redeem_badge(
        self, tg_id: int, badge_id: int
    ) -> Tuple[bool, str, Optional[dict]]:
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

    def get_user_badges(self, tg_id: int, only_active: bool = True) -> List[dict]:
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

    def get_user_active_badges_with_bonus(self, tg_id: int) -> List[dict]:
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


# 创建全局实例
db = DatabaseORM()
