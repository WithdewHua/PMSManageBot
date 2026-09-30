"""Donation admin router."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request

from app.core.log import uvicorn_logger as logger
from app.domains.donation import (
    exceptions as donation_exceptions,
)
from app.domains.donation import (
    service as donation_service,
)
from app.transport.http.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.transport.http.schemas import BaseResponse, TelegramUser

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/donation")
@require_telegram_auth
async def submit_donation_record(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """提交捐赠记录"""
    check_admin_permission(user)

    try:
        tg_id = data.get("tg_id")
        amount = data.get("amount", 0)
        note = data.get("note", "")

        if not tg_id or amount <= 0:
            return BaseResponse(success=False, message="参数错误")

        result = await donation_service.admin_record_donation(
            tg_id=int(tg_id),
            amount=float(amount),
            admin_id=user.id,
            note=note,
        )

        return BaseResponse(
            success=True,
            message=f"成功为 {result['user_name']} 添加 {amount}元 捐赠记录",
        )
    except donation_exceptions.DonationUserNotFound:
        return BaseResponse(success=False, message="用户不存在")
    except donation_exceptions.DonationInvalidAmount:
        return BaseResponse(success=False, message="参数错误")
    except Exception as e:
        logger.error(f"提交捐赠记录失败: {e!s}")
        return BaseResponse(success=False, message="提交失败")


@router.post("/settings/donation-multiplier")
@require_telegram_auth
async def set_donation_multiplier(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置捐赠金额兑换积分的倍率。"""
    check_admin_permission(user)
    try:
        multiplier = data.get("multiplier", donation_service.get_donation_multiplier())
        if (
            isinstance(multiplier, bool)
            or not isinstance(multiplier, int)
            or multiplier < 0
        ):
            return BaseResponse(success=False, message="倍率必须是非负整数")
        donation_service.set_donation_multiplier(multiplier)
        return BaseResponse(success=True, message=f"捐赠积分倍率已设置为 {multiplier}")
    except Exception as error:
        logger.error(f"设置捐赠积分倍率失败: {error!s}")
        return BaseResponse(success=False, message="设置失败")
