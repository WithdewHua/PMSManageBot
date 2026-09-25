from sqlalchemy import func, select

from app.core.db import get_session
from app.domains.identity.models import EmbyUser, PlexUser
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
