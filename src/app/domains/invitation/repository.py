from sqlalchemy import func, select, update

from app.core.db import get_session
from app.core.log import logger
from app.domains.invitation.models import Invitation


class InvitationRepository:
    def add_invitation_code(
        self, code: str, owner: int, is_used: int = 0, used_by: int | None = None
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

    def update_invitation_status(
        self,
        code: str,
        used_by: str,
        service: str | None = None,
        plex_id: int | None = None,
        emby_id: str | None = None,
    ) -> bool:
        """更新邀请码状态"""
        try:
            with get_session() as session:
                session.execute(
                    update(Invitation)
                    .where(Invitation.code == code)
                    .values(
                        is_used=1,
                        used_by=used_by,
                        service=service,
                        plex_id=plex_id,
                        emby_id=emby_id,
                    )
                )
                return True
        except Exception as e:
            logger.error(f"Error updating invitation status: {e}")
            return False

    def update_invitation_plex_id(self, plex_email: str, plex_id: int) -> bool:
        """通过 plex_email（used_by）更新对应邀请码的 plex_id 字段"""
        try:
            with get_session() as session:
                session.execute(
                    update(Invitation)
                    .where(
                        Invitation.used_by == plex_email,
                        Invitation.service == "plex",
                        Invitation.plex_id.is_(None),
                    )
                    .values(plex_id=plex_id)
                )
                return True
        except Exception as e:
            logger.error(f"Error updating invitation plex_id: {e}")
            return False

    def get_inviter_tg_id_by_plex_id(self, plex_id: int) -> int | None:
        """通过被邀请人的 plex_id 查找邀请人的 tg_id"""
        with get_session() as session:
            stmt = select(Invitation.owner).where(
                Invitation.plex_id == plex_id,
                Invitation.service == "plex",
                Invitation.is_used == 1,
            )
            return session.execute(stmt).scalar_one_or_none()

    def get_inviter_tg_id_by_emby_id(self, emby_id: str) -> int | None:
        """通过被邀请人的 emby_id 查找邀请人的 tg_id"""
        with get_session() as session:
            stmt = select(Invitation.owner).where(
                Invitation.emby_id == emby_id,
                Invitation.service == "emby",
                Invitation.is_used == 1,
            )
            return session.execute(stmt).scalar_one_or_none()

    def verify_invitation_code_is_used(self, code: str) -> tuple | None:
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
