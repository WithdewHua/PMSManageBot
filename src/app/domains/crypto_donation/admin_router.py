"""Administrator endpoints for crypto-donation settings."""

from fastapi import APIRouter, Body, Depends, Request

from app.core.log import uvicorn_logger as logger
from app.domains.crypto_donation import service as crypto_donation_service
from app.transport.http.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.transport.http.schemas import BaseResponse, TelegramUser

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/settings/upay-crypto-types")
@require_telegram_auth
async def set_upay_crypto_types(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置可用的加密货币类型。"""
    check_admin_permission(user)
    try:
        values = data.get(
            "crypto_types", crypto_donation_service.get_supported_crypto_types()
        )
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            return BaseResponse(
                success=False, message="加密货币列表必须是非空字符串列表"
            )
        crypto_donation_service.set_supported_crypto_types(
            [value.strip() for value in values]
        )
        return BaseResponse(success=True, message="加密货币类型列表已更新")
    except Exception as error:
        logger.error(f"设置加密货币类型失败: {error!s}")
        return BaseResponse(success=False, message="设置失败")
