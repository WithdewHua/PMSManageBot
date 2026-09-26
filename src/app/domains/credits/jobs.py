from sqlalchemy import select

from app.core.cache import user_credits_cache
from app.core.db import get_session
from app.core.log import logger
from app.domains.identity.models import EmbyUser, PlexUser, Statistics


def rewrite_users_credits_to_redis():
    """
    将用户积分信息写入 redis 缓存
    """
    try:
        # 从 statistics 表中获取所有用户的积分信息
        with get_session() as session:
            stmt = select(Statistics.tg_id, Statistics.credits)
            stats = session.execute(stmt).fetchall()
        user_stats = {tg_id: credits for tg_id, credits in stats}
        # 获取 Plex 用户信息
        with get_session() as session:
            stmt = select(
                PlexUser.plex_id,
                PlexUser.tg_id,
                PlexUser.credits,
                PlexUser.plex_username,
            )
            plex_users = session.execute(stmt).fetchall()
        for user in plex_users:
            # 未接受邀请，此时数据库中的 plex_id 为空
            if not user[0]:
                continue
            tg_id = user[1]
            credits = user[2]
            plex_username = user[3]
            if tg_id:
                credits = user_stats.get(tg_id, 0)
            user_credits_cache.put(f"plex:{plex_username.lower()}", credits)
        # 获取 Emby 用户信息
        with get_session() as session:
            stmt = select(
                EmbyUser.emby_id,
                EmbyUser.tg_id,
                EmbyUser.emby_credits,
                EmbyUser.emby_username,
            )
            emby_users = session.execute(stmt).fetchall()
        for user in emby_users:
            tg_id = user[1]
            credits = user[2]
            emby_username = user[3]
            if tg_id:
                credits = user_stats.get(tg_id, 0)
            user_credits_cache.put(f"emby:{emby_username.lower()}", credits)
    except Exception as e:
        logger.error(f"检查用户积分时发生错误: {e}")
