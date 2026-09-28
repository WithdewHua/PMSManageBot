"""Administrator endpoints for Vaultwarden business settings."""

from fastapi import APIRouter, Body, Depends, Request

from app.core.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.core.log import uvicorn_logger as logger
from app.core.schemas import BaseResponse, TelegramUser
from app.domains.vaultwarden import service as vaultwarden_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/settings/vaultwarden-enabled")
@require_telegram_auth
async def set_vaultwarden_enabled(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置 Vaultwarden 兑换开关。"""
    check_admin_permission(user)
    try:
        enabled = data.get("enabled", False)
        if not isinstance(enabled, bool):
            return BaseResponse(success=False, message="开关值必须是布尔值")
        vaultwarden_service.set_enabled(enabled)
        return BaseResponse(
            success=True, message=f"Vaultwarden 兑换已{'开启' if enabled else '关闭'}"
        )
    except Exception as error:
        logger.error(f"设置 Vaultwarden 开关失败: {error!s}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/vaultwarden-redeem-credits")
@require_telegram_auth
async def set_vaultwarden_redeem_credits(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置 Vaultwarden 兑换所需积分。"""
    check_admin_permission(user)
    try:
        credits = data.get("credits", vaultwarden_service.get_redeem_credits())
        if isinstance(credits, bool) or not isinstance(credits, int) or credits < 0:
            return BaseResponse(success=False, message="积分值必须是非负整数")
        vaultwarden_service.set_redeem_credits(credits)
        return BaseResponse(
            success=True, message=f"Vaultwarden 兑换积分已设置为 {credits}"
        )
    except Exception as error:
        logger.error(f"设置 Vaultwarden 兑换积分失败: {error!s}")
        return BaseResponse(success=False, message="设置失败")
