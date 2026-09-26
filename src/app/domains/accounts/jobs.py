from app.domains.accounts.service import (
    update_emby_users_last_viewed_at,
    update_plex_users_last_viewed_at,
)


def update_users_last_viewed():
    """更新所有用户的最后观看时间"""
    from concurrent.futures import ThreadPoolExecutor, wait

    with ThreadPoolExecutor() as executor:
        future1 = executor.submit(update_plex_users_last_viewed_at)
        future2 = executor.submit(update_emby_users_last_viewed_at)
        wait([future1, future2])


from sqlalchemy import select

from app.core.db import get_session as get_db_session
from app.core.log import logger
from app.domains.identity.models import EmbyUser
from app.integrations.emby import Emby


def refresh_emby_user_info(emby_username: str | None = None):
    """刷新 emby user info"""
    emby = Emby()
    # 获取所有的 emby 用户名
    try:
        if not emby_username:
            with get_db_session() as session:
                stmt = select(EmbyUser.emby_username)
                emby_users = [
                    username for username in session.execute(stmt).scalars().all()
                ]
        else:
            emby_users = [emby_username]

        for user in emby_users:
            emby.get_user_info_from_username(user)
    except Exception as e:
        logger.error(f"Refresh emby user info failed: {e}")
