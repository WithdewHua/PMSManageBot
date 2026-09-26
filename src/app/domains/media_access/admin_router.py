from fastapi import APIRouter, Body, Depends, Request

from app.core.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.core.schemas import BaseResponse, TelegramUser

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
        credits = data.get("credits", 100)

        # 验证积分值的合理性
        if not isinstance(credits, int) or credits < 0:
            return BaseResponse(success=False, message="积分值必须是非负整数")

        settings.UNLOCK_CREDITS = credits
        settings.save_config_to_env_file({"UNLOCK_CREDITS": str(credits)})

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
        credits = data.get("credits", settings.DOWNLOAD_UNLOCK_CREDITS)

        # 验证积分值的合理性
        if not isinstance(credits, int) or credits < 0:
            return BaseResponse(success=False, message="积分值必须是非负整数")

        settings.DOWNLOAD_UNLOCK_CREDITS = credits
        settings.save_config_to_env_file({"DOWNLOAD_UNLOCK_CREDITS": str(credits)})

        logger.info(
            f"管理员 {user.username or user.id} 设置解锁下载/同步功能所需积分为: {credits}"
        )
        return BaseResponse(
            success=True, message=f"解锁下载/同步功能所需积分已设置为 {credits}"
        )
    except Exception as e:
        logger.error(f"设置解锁下载/同步功能积分失败: {e!s}")
        return BaseResponse(success=False, message="设置失败")
