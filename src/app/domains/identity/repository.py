import json

from sqlalchemy import delete, func, select, update

from app.core.cache import user_info_cache
from app.core.db import get_session
from app.core.log import logger
from app.domains.identity.models import EmbyUser, Overseerr, PlexUser, Statistics


class IdentityRepository:
    def add_plex_user(
        self,
        plex_id: int | None = None,
        tg_id: int | None = None,
        plex_email: str | None = None,
        plex_username: str | None = None,
        credits: float = 0,
        all_lib: int = 0,
        unlock_time: str | None = None,
        watched_time: float = 0,
        plex_line: str | None = None,
        is_premium: int = 0,
        premium_expiry_time: str | None = None,
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

    def get_plex_info_by_tg_id(self, tg_id: int) -> tuple | None:
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

    def get_plex_info_by_plex_id(self, plex_id: int) -> tuple | None:
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

    def get_plex_info_by_plex_username(self, plex_username: str) -> tuple | None:
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

    def get_plex_info_by_plex_email(self, plex_email: str) -> tuple | None:
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

    def add_emby_user(
        self,
        emby_username: str,
        emby_id: str | None = None,
        tg_id: int | None = None,
        emby_is_unlock: int = 0,
        emby_unlock_time: int | None = None,
        emby_watched_time: float = 0,
        emby_credits: float = 0,
        emby_line: str | None = None,
        is_premium: int = 0,
        premium_expiry_time: str | None = None,
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

    def get_emby_info_by_emby_username(self, username: str) -> tuple | None:
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

    def get_emby_info_by_tg_id(self, tg_id: int) -> tuple | None:
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

    def get_emby_info_by_emby_id(self, emby_id: str) -> tuple | None:
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

    def get_stats_by_tg_id(self, tg_id: int) -> tuple | None:
        """通过 Telegram ID 获取统计信息"""
        with get_session() as session:
            stmt = select(Statistics).where(Statistics.tg_id == tg_id)
            stats = session.execute(stmt).scalar_one_or_none()
            if stats:
                return (stats.tg_id, stats.donation, stats.credits)
            return None

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

    def get_overseerr_info_by_tg_id(self, tg_id: int) -> tuple | None:
        """通过 Telegram ID 获取 Overseerr 用户信息"""
        with get_session() as session:
            stmt = select(Overseerr).where(Overseerr.tg_id == tg_id)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (user.user_id, user.user_email, user.tg_id)
            return None

    def update_user_tg_id(
        self, tg_id: int, plex_id: int | None = None, emby_id: str | None = None
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

    def get_overseerr_info_by_email(self, email: str) -> tuple | None:
        """通过邮箱获取 Overseerr 用户信息"""
        with get_session() as session:
            stmt = select(Overseerr).where(Overseerr.user_email == email)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (user.user_id, user.user_email, user.tg_id)
            return None

    def _list_statistics_tg_ids(self) -> list[int]:
        """Return Telegram IDs represented in the statistics table."""
        with get_session() as session:
            return list(session.execute(select(Statistics.tg_id)).scalars().all())
