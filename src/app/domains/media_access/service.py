from app.core.log import logger
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.identity import service as identity_service
from app.domains.media_access import exceptions as media_access_exceptions
from app.domains.media_access import notifications as media_access_notifications
from app.domains.media_access import repository as media_access_repository
from app.domains.media_access.config import MEDIA_ACCESS_CONFIG
from app.domains.media_access.rules import caculate_credits_fund
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


def check_download_unlock(tg_id: int, service: str) -> dict:
    return media_access_repository.check_download_unlock(int(tg_id), service)


def is_download_unlocked(tg_id: int, service: str) -> bool:
    """Return whether persisted or Premium-derived access is available."""
    status = check_download_unlock(int(tg_id), service)
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


async def perform_nsfw_operation(tg_id: int, service: str, operation: str) -> dict:
    """Run one NSFW workflow and return its committed credit result."""
    normalized = service.lower()
    if normalized == "plex":
        account = identity_service.find_plex_by_tg(int(tg_id))
        unlocked = account and int(account.all_lib or 0) == 1
        unlock_time = account.unlock_time if account else None
    elif normalized == "emby":
        account = identity_service.find_emby_by_tg(int(tg_id))
        unlocked = account and int(account.emby_is_unlock or 0) == 1
        unlock_time = account.emby_unlock_time if account else None
    else:
        raise ValueError(f"不支持的服务类型: {service}")
    if account is None:
        raise media_access_exceptions.MediaAccountNotBound(normalized)
    if operation == "unlock":
        if unlocked:
            raise ValueError("您已拥有全部库权限")
        return await unlock_nsfw(int(tg_id), normalized, get_unlock_credits())
    if operation == "lock":
        if not unlocked:
            raise ValueError("您未解锁NSFW内容")
        return await lock_nsfw(
            int(tg_id), normalized, unlock_time, get_unlock_credits()
        )
    raise ValueError(f"不支持的操作类型: {operation}")


async def unlock_nsfw(tg_id: int, service: str, cost: float) -> dict:
    """Commit NSFW unlock, then synchronize the media server with compensation."""
    committed = media_access_repository.unlock_nsfw(int(tg_id), service, float(cost))

    try:
        if service == "plex":
            Plex().update_user_shared_libs(committed["target"], Plex().get_libraries())
        elif service == "emby":
            from app.integrations.emby import Emby

            success, message = Emby().add_user_library(
                user_id=committed["target"], library=get_nsfw_libs()
            )
            if not success:
                raise RuntimeError(message)
        else:
            raise ValueError(f"不支持的服务类型: {service}")
    except Exception as error:
        logger.error("同步 %s NSFW 解锁失败: %s", service, error)
        try:
            media_access_repository.compensate_nsfw_unlock(
                int(tg_id), service, float(cost)
            )
        except Exception as compensation_error:
            logger.error("NSFW 解锁补偿失败: %s", compensation_error)
            await media_access_notifications.notify_nsfw_compensation_failed(
                int(tg_id), service, "unlock", compensation_error
            )
        raise

    return {
        "credits": credits_service.read_optional(CreditAccount.tg(int(tg_id))) or 0.0,
        "cost": float(cost),
    }


async def lock_nsfw(tg_id: int, service: str, unlock_time, unlock_credits: int) -> dict:
    """Commit NSFW lock and refund, then synchronize with compensation."""
    refund = caculate_credits_fund(unlock_time, unlock_credits)
    committed = media_access_repository.lock_nsfw(int(tg_id), service, float(refund))

    try:
        if service == "plex":
            plex = Plex()
            libraries = plex.get_libraries()
            libraries = [
                library for library in libraries if library not in get_nsfw_libs()
            ]
            plex.update_user_shared_libs(committed["target"], libraries)
        elif service == "emby":
            from app.integrations.emby import Emby

            success, message = Emby().remove_user_library(
                user_id=committed["target"], library=get_nsfw_libs()
            )
            if not success:
                raise RuntimeError(message)
        else:
            raise ValueError(f"不支持的服务类型: {service}")
    except Exception as error:
        logger.error("同步 %s NSFW 锁定失败: %s", service, error)
        try:
            media_access_repository.compensate_nsfw_lock(
                int(tg_id), service, float(refund)
            )
        except Exception as compensation_error:
            logger.error("NSFW 锁定补偿失败: %s", compensation_error)
            await media_access_notifications.notify_nsfw_compensation_failed(
                int(tg_id), service, "lock", compensation_error
            )
        raise

    return {
        "credits": credits_service.read_optional(CreditAccount.tg(int(tg_id))) or 0.0,
        "refund": float(refund),
    }


def update_all_lib_flag(*args, **kwargs) -> bool:
    return media_access_repository.update_all_lib_flag(*args, **kwargs)


def set_download_unlocked(tg_id: int, service: str) -> bool:
    return media_access_repository.set_download_unlocked(tg_id, service)


def deduct_credits_for_download_unlock(tg_id: int) -> tuple[bool, str, float]:
    return media_access_repository.deduct_credits_for_download_unlock(tg_id)


def get_download_unlocked_users_num() -> int:
    return media_access_repository.get_download_unlocked_users_num()
