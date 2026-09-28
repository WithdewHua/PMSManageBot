import time
from datetime import datetime

from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.credits import repository as credits_repository
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
from app.domains.media_access.config import MEDIA_ACCESS_CONFIG


class MediaAccessRepository:
    def update_all_lib_flag(
        self,
        all_lib: int,
        unlock_time: str | None = None,
        plex_id: int | None = None,
        emby_id: str | None = None,
        tg_id: int | None = None,
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

    def check_download_unlock(self, tg_id: int, service: str) -> dict:
        """
        检查用户是否解锁了指定服务的下载/同步功能

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
        from app.core.telegram import get_user_name_from_tg_id

        try:
            with get_session() as session:
                is_premium = False
                unlock_time = None

                if service == "plex":
                    # 检查 Plex 用户状态
                    stmt = select(
                        PlexUser.is_premium,
                        PlexUser.premium_expiry_time,
                        PlexUser.sync_unlocked,
                        PlexUser.sync_unlock_time,
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
                        EmbyUser.download_unlocked,
                        EmbyUser.download_unlock_time,
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
                f"检查用户 {get_user_name_from_tg_id(tg_id)} 的 {service} 下载权限解锁状态失败: {e}"
            )
            return {"is_unlocked": False, "is_premium": False, "unlock_time": None}

    def set_download_unlocked(self, tg_id: int, service: str) -> bool:
        """
        设置用户下载权限为已解锁（仅更新数据库）

        Args:
            tg_id: 用户的 Telegram ID
            service: 服务类型 (plex/emby)

        Returns:
            是否成功
        """
        try:
            with get_session() as session:
                unlock_time = int(time.time())

                if service == "plex":
                    stmt = (
                        update(PlexUser)
                        .where(PlexUser.tg_id == tg_id)
                        .values(
                            sync_unlocked=1,
                            sync_unlock_time=unlock_time,
                        )
                    )
                elif service == "emby":
                    stmt = (
                        update(EmbyUser)
                        .where(EmbyUser.tg_id == tg_id)
                        .values(
                            download_unlocked=1,
                            download_unlock_time=unlock_time,
                        )
                    )
                else:
                    logger.error(f"未知的服务类型: {service}")
                    return False

                session.execute(stmt)
                logger.info(f"用户 {tg_id} 的 {service} 下载权限已解锁")
                return True

        except Exception as e:
            logger.error(f"设置 {service} 下载权限解锁失败: {e}")
            return False

    def deduct_credits_for_download_unlock(self, tg_id: int) -> tuple[bool, str, float]:
        """
        扣除解锁下载权限所需积分

        Args:
            tg_id: 用户的 Telegram ID

        Returns:
            (是否成功, 消息, 剩余积分)
        """
        try:
            with get_session() as session:
                stmt = select(Statistics.credits).where(Statistics.tg_id == tg_id)
                credits = session.execute(stmt).scalar()

                if credits is None:
                    return False, "用户不存在", 0

                required_credits = MEDIA_ACCESS_CONFIG.get().download_unlock_credits
                if credits < required_credits:
                    return (
                        False,
                        f"积分不足，需要 {required_credits} 积分，当前积分 {credits:.2f}",
                        credits,
                    )

                # 扣除积分
                mutation = credits_repository.deduct_tx(
                    session, CreditAccount.tg(int(tg_id)), required_credits
                )
                credits_service.register_cache_invalidation(session, mutation)
                new_credits = mutation.after

                logger.info(
                    f"用户 {tg_id} 扣除 {required_credits} 积分用于解锁下载权限"
                )
                return True, f"消耗 {required_credits} 积分", new_credits

        except Exception as e:
            logger.error(f"扣除积分失败: {e}")
            return False, f"扣除积分失败: {e!s}", 0

    def get_download_unlocked_users_num(self) -> int:
        """
        获取已解锁下载权限的用户数量（不包括 Premium 用户）

        Returns:
            解锁用户数量
        """
        try:
            with get_session() as session:
                # Plex 用户
                plex_count = session.execute(
                    select(func.count()).where(PlexUser.sync_unlocked == 1)
                ).scalar()

                # Emby 用户
                emby_count = session.execute(
                    select(func.count()).where(EmbyUser.download_unlocked == 1)
                ).scalar()

                return (plex_count or 0) + (emby_count or 0)
        except Exception as e:
            logger.error(f"获取下载权限解锁用户数量失败: {e}")
            return 0


# 模块级入口：处于 service 端的调用方（如 premium 的权限同步）不持有门面实例。
_media_access_repository = MediaAccessRepository()


def check_download_unlock(tg_id: int, service: str) -> dict:
    """该用户在指定服务上的下载/同步权限状态（含 Premium 自动解锁）。"""
    return _media_access_repository.check_download_unlock(tg_id, service)


# 下载/同步解锁列属于 media_access（见 docs/architecture.md 宽表列归属）。
_DOWNLOAD_UNLOCK_COLUMNS = {
    "plex": (PlexUser, "sync_unlocked", "sync_unlock_time"),
    "emby": (EmbyUser, "download_unlocked", "download_unlock_time"),
}


def unlock_download_tx(session, tg_id: int, service: str) -> dict:
    """在调用方事务内永久解锁下载/同步权限，返回“已解锁”或“已跳过”。

    只写永久解锁标记列：Premium 自带的下载权限不写这两列，避免 Premium
    到期后永久权限被误判为已拥有（与 check_download_unlock 的语义区分）。
    """
    if service not in _DOWNLOAD_UNLOCK_COLUMNS:
        raise ValueError(f"不支持的解锁类型: download/{service}")
    model, flag_col, time_col = _DOWNLOAD_UNLOCK_COLUMNS[service]
    user = (
        session.execute(
            select(model).where(model.tg_id == int(tg_id)).with_for_update()
        )
        .scalars()
        .one_or_none()
    )
    if user is None:
        raise ValueError(f"未找到绑定的 {service.capitalize()} 账号")
    if int(getattr(user, flag_col) or 0) == 1:
        return {"unlocked": False, "skipped": "already_unlocked", "service": service}
    setattr(user, flag_col, 1)
    setattr(user, time_col, int(time.time()))
    return {"unlocked": True, "skipped": None, "service": service}
