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
    """Return whether persisted or Premium-derived access is available."""
    status = media_access_repository.check_download_unlock(int(tg_id), service)
    return bool(status.get("is_unlocked"))


def unlock_download(tg_id: int, service: str, cost: float):
    return media_access_repository.unlock_download(
        tg_id=int(tg_id), service=service, cost=float(cost)
    )


def apply_download_unlock_to_media(tg_id: int, service: str) -> None:
    """Apply a committed permanent download unlock to the media server."""
    target = media_access_repository.get_download_sync_target(int(tg_id), service)
    if not target:
        raise RuntimeError(f"未找到绑定的 {service} 账号")
    if service == "plex":
        if not Plex().update_sync_for_user(target, allow_sync=True):
            raise RuntimeError("Plex 同步权限更新失败")
    elif service == "emby":
        from app.integrations.emby import Emby

        result = Emby().update_download_permission_for_user(target, allow_download=True)
        if isinstance(result, tuple) and not result[0]:
            raise RuntimeError(f"Emby 下载权限更新失败: {result[1]}")
        if result is False:
            raise RuntimeError("Emby 下载权限更新失败")
    else:
        raise ValueError(f"不支持的服务类型: {service}")


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
