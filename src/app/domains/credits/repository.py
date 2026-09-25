from sqlalchemy import select, update

from app.core.db import get_session
from app.core.log import logger
from app.domains.identity.models import EmbyUser, PlexUser, Statistics


class CreditsRepository:
    def get_user_credits(self, tg_id: int) -> float | None:
        """获取用户积分"""
        with get_session() as session:
            stmt = select(Statistics).where(Statistics.tg_id == tg_id)
            stats = session.execute(stmt).scalar_one_or_none()
            return stats.credits if stats else None

    def update_user_credits(
        self,
        credits: float,
        plex_id: int | None = None,
        emby_id: str | None = None,
        tg_id: int | None = None,
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
