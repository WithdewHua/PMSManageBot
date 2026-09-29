from fastapi import APIRouter, Body, Depends, Request

from app.core.log import uvicorn_logger as logger
from app.domains.accounts import service as accounts_service
from app.transport.http.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.transport.http.schemas import BaseResponse, TelegramUser

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/settings/plex-register")
@require_telegram_auth
async def set_plex_register(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置Plex注册开关"""
    check_admin_permission(user)

    try:
        enabled = data.get("enabled", False)
        accounts_service.set_registration_enabled("plex", bool(enabled))

        logger.info(
            f"管理员 {user.username or user.id} 设置 Plex 注册状态为: {enabled}"
        )
        return BaseResponse(
            success=True, message=f"Plex 注册已{'开启' if enabled else '关闭'}"
        )
    except Exception as e:
        logger.error(f"设置 Plex 注册状态失败: {e!s}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/emby-register")
@require_telegram_auth
async def set_emby_register(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置Emby注册开关"""
    check_admin_permission(user)

    try:
        enabled = data.get("enabled", False)
        accounts_service.set_registration_enabled("emby", bool(enabled))

        logger.info(
            f"管理员 {user.username or user.id} 设置 Emby 注册状态为: {enabled}"
        )
        return BaseResponse(
            success=True, message=f"Emby 注册已{'开启' if enabled else '关闭'}"
        )
    except Exception as e:
        logger.error(f"设置 Emby 注册状态失败: {e!s}")
        return BaseResponse(success=False, message="设置失败")
