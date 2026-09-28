from fastapi import APIRouter, Body, Depends, Request

from app.core.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.core.log import uvicorn_logger as logger
from app.core.schemas import BaseResponse, TelegramUser
from app.domains.media_access import service as media_access_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/settings/unlock-credits")
@require_telegram_auth
async def set_unlock_credits(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置解锁NSFW所需积分"""
    check_admin_permission(user)

    try:
        credits = data.get("credits", media_access_service.get_unlock_credits())

        # 验证积分值的合理性
        if not isinstance(credits, int) or credits < 0:
            return BaseResponse(success=False, message="积分值必须是非负整数")

        media_access_service.set_unlock_credits(credits)

        logger.info(
            f"管理员 {user.username or user.id} 设置解锁 NSFW 所需积分为: {credits}"
        )
        return BaseResponse(
            success=True, message=f"解锁 NSFW 所需积分已设置为 {credits}"
        )
    except Exception as e:
        logger.error(f"设置解锁积分失败: {e!s}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/download-unlock-credits")
@require_telegram_auth
async def set_download_unlock_credits(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置解锁下载/同步功能所需积分"""
    check_admin_permission(user)

    try:
        credits = data.get(
            "credits", media_access_service.get_download_unlock_credits()
        )

        # 验证积分值的合理性
        if not isinstance(credits, int) or credits < 0:
            return BaseResponse(success=False, message="积分值必须是非负整数")

        media_access_service.set_download_unlock_credits(credits)

        logger.info(
            f"管理员 {user.username or user.id} 设置解锁下载/同步功能所需积分为: {credits}"
        )
        return BaseResponse(
            success=True, message=f"解锁下载/同步功能所需积分已设置为 {credits}"
        )
    except Exception as e:
        logger.error(f"设置解锁下载/同步功能积分失败: {e!s}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/nsfw-libs")
@require_telegram_auth
async def set_nsfw_libs(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置不展示/不授权的 NSFW 媒体库列表。"""
    check_admin_permission(user)
    try:
        libs = data.get("libs", media_access_service.get_nsfw_libs())
        if not isinstance(libs, list) or any(
            not isinstance(value, str) or not value.strip() for value in libs
        ):
            return BaseResponse(success=False, message="媒体库列表必须是非空字符串列表")
        media_access_service.set_nsfw_libs([value.strip() for value in libs])
        return BaseResponse(success=True, message="NSFW 媒体库列表已更新")
    except Exception as error:
        logger.error(f"设置 NSFW 媒体库列表失败: {error!s}")
        return BaseResponse(success=False, message="设置失败")
