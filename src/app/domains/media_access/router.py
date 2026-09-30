from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request

from app.core.log import uvicorn_logger as logger
from app.domains.credits.exceptions import InsufficientCredits
from app.domains.identity import service as identity_service
from app.domains.media_access import exceptions as media_access_exceptions
from app.domains.media_access import notifications as media_access_notifications
from app.domains.media_access import service as media_access_service
from app.domains.media_access.rules import caculate_credits_fund
from app.integrations.telegram.profiles import get_user_name_from_tg_id
from app.transport.http.auth import get_telegram_user, require_telegram_auth
from app.transport.http.schemas import BaseResponse, TelegramUser

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/nsfw-info")
@require_telegram_auth
async def get_nsfw_info(
    request: Request,
    service: str,
    operation: str,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取NSFW操作所需积分或可退回积分"""
    if service not in ("plex", "emby"):
        raise HTTPException(status_code=400, detail="不支持的服务类型")
    if operation not in ("unlock", "lock"):
        raise HTTPException(status_code=400, detail="不支持的操作类型")
    if operation == "unlock":
        return {"cost": media_access_service.get_unlock_credits()}
    account = (
        identity_service.find_plex_by_tg(user.id)
        if service == "plex"
        else identity_service.find_emby_by_tg(user.id)
    )
    if not account or (
        not account.all_lib if service == "plex" else not account.emby_is_unlock
    ):
        raise HTTPException(status_code=400, detail="您尚未解锁 NSFW 内容")
    unlock_time = account.unlock_time if service == "plex" else account.emby_unlock_time
    return {
        "refund": caculate_credits_fund(
            unlock_time, media_access_service.get_unlock_credits()
        )
    }


@router.post("/nsfw/{operation}")
@require_telegram_auth
async def nsfw_operation(
    request: Request,
    background_tasks: BackgroundTasks,
    operation: str,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """Execute an NSFW operation with atomic state and post-commit synchronization."""
    if operation not in ("unlock", "lock"):
        raise HTTPException(status_code=400, detail="不支持的操作类型")
    service = data.get("service")
    if service not in ("plex", "emby"):
        raise HTTPException(status_code=400, detail="不支持的服务类型")
    try:
        result = await media_access_service.perform_nsfw_operation(
            int(user.id), service, operation
        )
        credits = float(result["credits"])
        if operation == "unlock":
            service_name, service_emoji = identity_service.get_service_label(service)
            user_name = get_user_name_from_tg_id(user.id)
            background_tasks.add_task(
                media_access_notifications.notify_nsfw_unlocked,
                f"""🔞 NSFW 权限解锁通知

👤 用户: {user_name}（TG ID: {user.id}）
{service_emoji} 服务: {service_name}
💎 花费: {media_access_service.get_unlock_credits()} 积分
💰 剩余: {credits:.2f} 积分""",
            )
        return {
            "success": True,
            "message": f"NSFW 内容已{'解锁' if operation == 'unlock' else '锁定'}",
            "credits": credits,
        }
    except media_access_exceptions.MediaAccountNotBound:
        raise HTTPException(status_code=404, detail=f"{service.capitalize()}账户未绑定")
    except InsufficientCredits as error:
        raise HTTPException(status_code=400, detail="积分不足") from error
    except ValueError as error:
        message = str(error)
        if message in {"您已拥有全部库权限", "您未解锁NSFW内容"}:
            raise HTTPException(status_code=400, detail=message) from error
        raise HTTPException(status_code=500, detail="操作失败，请稍后再试") from error
    except Exception as error:
        logger.error("执行 NSFW 操作时发生错误: %s", error)
        raise HTTPException(status_code=500, detail="操作失败，请稍后再试") from error


@router.get("/download-permission/status/{service}")
@require_telegram_auth
async def get_download_permission_status(
    service: str,
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取下载权限状态"""
    if service not in ["plex", "emby"]:
        raise HTTPException(status_code=400, detail="服务类型必须是 'plex' 或 'emby'")
    try:
        unlock_status = media_access_service.check_download_unlock(user.id, service)
        return {
            "success": True,
            "is_unlocked": unlock_status["is_unlocked"],
            "is_premium": unlock_status["is_premium"],
            "unlock_time": unlock_status["unlock_time"],
            "unlock_cost": media_access_service.get_download_unlock_credits(),
        }
    except Exception as error:
        logger.error("获取下载权限状态失败: %s", error)
        raise HTTPException(status_code=500, detail="获取下载权限状态失败") from error


@router.post("/download-permission/unlock/{service}")
@require_telegram_auth
async def unlock_download_permission(
    service: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: TelegramUser = Depends(get_telegram_user),
):
    """Unlock download permission atomically with the credit deduction."""
    if service not in ["plex", "emby"]:
        raise HTTPException(status_code=400, detail="服务类型必须是 'plex' 或 'emby'")
    tg_id = int(user.id)
    try:
        unlock_status = media_access_service.check_download_unlock(tg_id, service)
        if unlock_status["is_unlocked"]:
            if unlock_status["is_premium"]:
                return BaseResponse(
                    success=False, message="Premium 用户已自动拥有下载权限，无需解锁"
                )
            return BaseResponse(success=False, message="下载权限已解锁，无需重复解锁")
        mutation = media_access_service.unlock_download(
            tg_id, service, media_access_service.get_download_unlock_credits()
        )
        background_tasks.add_task(
            media_access_service.apply_download_unlock_to_media, tg_id, service
        )
        service_name, service_emoji = identity_service.get_service_label(service)
        user_name = get_user_name_from_tg_id(tg_id)
        background_tasks.add_task(
            media_access_notifications.notify_download_unlocked,
            f"""📥 下载权限解锁通知

👤 用户: {user_name}（TG ID: {tg_id}）
{service_emoji} 服务: {service_name}
💎 花费: {media_access_service.get_download_unlock_credits()} 积分
💰 剩余: {mutation.after:.2f} 积分""",
        )
        return BaseResponse(
            success=True,
            message=(
                f"解锁成功！消耗 {media_access_service.get_download_unlock_credits()} 积分，"
                f"剩余 {mutation.after:.2f} 积分"
            ),
        )
    except media_access_exceptions.MediaAccountNotBound:
        return BaseResponse(success=False, message="请先绑定 Plex/Emby 账户")
    except media_access_exceptions.DownloadAlreadyUnlocked as error:
        return BaseResponse(success=False, message=str(error))
    except Exception:
        logger.exception("解锁下载权限失败")
        return BaseResponse(success=False, message="解锁失败，请联系管理员")
