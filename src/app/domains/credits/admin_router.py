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


@router.post("/settings/credits-transfer-enabled")
@require_telegram_auth
async def set_credits_transfer_enabled(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置积分转移功能开关"""
    check_admin_permission(user)

    try:
        enabled = data.get("enabled", False)
        settings.CREDITS_TRANSFER_ENABLED = bool(enabled)
        settings.save_config_to_env_file(
            {"CREDITS_TRANSFER_ENABLED": str(enabled).lower()}
        )

        logger.info(
            f"管理员 {user.username or user.id} 设置积分转移功能状态为: {enabled}"
        )
        return BaseResponse(
            success=True, message=f"积分转移功能已{'开启' if enabled else '关闭'}"
        )
    except Exception as e:
        logger.error(f"设置积分转移功能状态失败: {e!s}")
        return BaseResponse(success=False, message="设置失败")
