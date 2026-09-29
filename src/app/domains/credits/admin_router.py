from fastapi import APIRouter, Body, Depends, Request

from app.core.log import uvicorn_logger as logger
from app.domains.credits import service as credits_service
from app.transport.http.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.transport.http.schemas import BaseResponse, TelegramUser

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
        credits_service.set_transfer_enabled(bool(enabled))

        logger.info(
            f"管理员 {user.username or user.id} 设置积分转移功能状态为: {enabled}"
        )
        return BaseResponse(
            success=True, message=f"积分转移功能已{'开启' if enabled else '关闭'}"
        )
    except Exception as e:
        logger.error(f"设置积分转移功能状态失败: {e!s}")
        return BaseResponse(success=False, message="设置失败")
