from sqlalchemy import select
from sqlalchemy import update as sql_update

from app.core.db import get_session
from app.domains.identity.models import PlexUser
from app.domains.media_access import repository as media_access_repository
from app.domains.media_access.config import MEDIA_ACCESS_CONFIG
from app.integrations.plex import Plex


def get_unlock_credits() -> int:
    return int(MEDIA_ACCESS_CONFIG.get().unlock_credits)


def get_download_unlock_credits() -> int:
    return int(MEDIA_ACCESS_CONFIG.get().download_unlock_credits)


def get_nsfw_libs() -> list[str]:
    return list(MEDIA_ACCESS_CONFIG.get().nsfw_libs)


def set_unlock_credits(credits: int) -> int:
    return int(MEDIA_ACCESS_CONFIG.update(unlock_credits=credits).unlock_credits)


def set_download_unlock_credits(credits: int) -> int:
    return int(
        MEDIA_ACCESS_CONFIG.update(
            download_unlock_credits=credits
        ).download_unlock_credits
    )


def set_nsfw_libs(libs: list[str]) -> list[str]:
    return list(MEDIA_ACCESS_CONFIG.update(nsfw_libs=libs).nsfw_libs)


def is_download_unlocked(tg_id: int, service: str) -> bool:
    """该用户在指定服务上是否已经拥有下载/同步权限（含 Premium 自动解锁）。

    跨域调用方（premium 的权限同步、礼包解锁）用它判断“是否还需要推送到媒体
    服务器”，避免直接读 media_access 的列。
    """
    status = media_access_repository.check_download_unlock(int(tg_id), service)
    return bool(status.get("unlock_time"))


def update_all_lib():
    """更新用户资料库权限状态"""
    _plex = Plex()
    try:
        users = _plex.users_by_email
        all_libs = _plex.get_libraries()
        for email, user in users.items():
            if not email:
                continue
            with get_session() as session:
                stmt = select(PlexUser).where(PlexUser.plex_email == email)
                _info = session.execute(stmt).fetchone()
            if not _info:
                continue
            cur_libs = _plex.get_user_shared_libs_by_id(user[0])
            all_lib_flag = 1 if not set(all_libs).difference(set(cur_libs)) else 0
            with get_session() as session:
                stmt = (
                    sql_update(PlexUser)
                    .where(PlexUser.plex_email == email)
                    .values(all_lib=all_lib_flag)
                )
                session.execute(stmt)
    except Exception as e:
        print(e)
