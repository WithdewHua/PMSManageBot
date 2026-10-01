from fastapi import APIRouter, Body, Depends, Request

from app.core.log import uvicorn_logger as logger
from app.domains.premium import service as premium_service
from app.transport.http.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.transport.http.schemas import BaseResponse, TelegramUser

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/settings/premium-daily-credits")
@require_telegram_auth
async def set_premium_daily_credits(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置解锁 Premium 每日所需积分"""
    check_admin_permission(user)

    try:
        credits = data.get("credits", premium_service.get_premium_daily_credits())

        # 验证积分值的合理性
        if isinstance(credits, bool) or not isinstance(credits, int) or credits < 0:
            return BaseResponse(success=False, message="积分值必须是非负整数")

        premium_service.set_premium_daily_credits(credits)

        logger.info(
            f"管理员 {user.username or user.id} 设置解锁 Premium 每日所需积分为: {credits}"
        )
        return BaseResponse(
            success=True, message=f"解锁 Premium 每日所需积分已设置为 {credits}"
        )
    except Exception as e:
        logger.error(f"设置 Premium 每日积分失败: {e!s}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/premium-unlock-enabled")
@require_telegram_auth
async def set_premium_unlock_enabled(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置 Premium 解锁开放状态"""
    check_admin_permission(user)

    try:
        enabled = bool(data.get("enabled", False))
        premium_service.set_premium_unlock_enabled(enabled)

        logger.info(
            f"管理员 {user.username or user.id} 设置 Premium 解锁开放状态为: {enabled}"
        )
        return BaseResponse(
            success=True, message=f"Premium 解锁已{'开放' if enabled else '关闭'}"
        )
    except Exception as e:
        logger.error(f"设置 Premium 解锁开放状态失败: {e!s}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/credits-cost-per-10gb")
@require_telegram_auth
async def set_credits_cost_per_10gb(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置每 10GB 超额流量扣除的积分。"""
    check_admin_permission(user)
    try:
        credits = data.get("credits", premium_service.get_credits_cost_per_10gb())
        if isinstance(credits, bool) or not isinstance(credits, int) or credits < 0:
            return BaseResponse(success=False, message="积分值必须是非负整数")
        premium_service.set_credits_cost_per_10gb(credits)
        return BaseResponse(success=True, message=f"每 10GB 流量扣费已设置为 {credits}")
    except Exception as error:
        logger.error(f"设置每 10GB 流量扣费失败: {error!s}")
        return BaseResponse(success=False, message="设置失败")
