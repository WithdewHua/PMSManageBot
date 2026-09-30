"""Donation HTTP router."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from app.core import errors
from app.core.config import settings
from app.core.log import logger
from app.domains.donation import notifications
from app.domains.donation import service as donation_service
from app.domains.donation.schemas import (
    DonationRegistrationConfirmResponse,
    DonationRegistrationCreate,
    DonationRegistrationCreateResponse,
    DonationRegistrationDetailResponse,
    DonationRegistrationListResponse,
    DonationRegistrationResponse,
    DonationRegistrationUpdate,
)
from app.integrations.telegram.profiles import (
    get_user_name_from_tg_id,
    refresh_tg_user_profile,
)
from app.transport.http.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.transport.http.schemas import TelegramUser

router = APIRouter(prefix="/api/donations", tags=["donations"])


@router.post("/register", response_model=DonationRegistrationCreateResponse)
@require_telegram_auth
async def create_donation_registration(
    request: Request,
    background_tasks: BackgroundTasks,
    registration_data: DonationRegistrationCreate,
    user: TelegramUser = Depends(get_telegram_user),
):
    """创建捐赠自助登记"""
    try:
        user_id = user.id
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="用户信息不完整"
            )
        # 创建后台任务以刷新用户信息
        background_tasks.add_task(refresh_tg_user_profile, tg_id=user_id)

        registration_id = donation_service.create_donation_registration(
            user_id=user_id,
            payment_method=registration_data.payment_method.value,
            amount=registration_data.amount,
            note=registration_data.note,
            is_donation_registration=registration_data.is_donation_registration,
        )
        if registration_id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="创建捐赠登记失败",
            )
        registration = donation_service.get_donation_registration_by_id(
            int(registration_id)
        )
        if registration is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="获取创建的登记记录失败",
            )

        # 发送管理员通知
        await notifications.notify_admins_of_registration(
            user_id=user_id,
            user_name=get_user_name_from_tg_id(user_id),
            payment_method=registration_data.payment_method.value,
            amount=registration_data.amount,
            is_donation_registration=registration_data.is_donation_registration,
        )

        return DonationRegistrationCreateResponse(
            success=True,
            message="捐赠登记提交成功，管理员将在 24 小时内处理",
            data=DonationRegistrationResponse(**registration),
        )

    except HTTPException:
        raise
    except errors.DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except Exception as e:
        logger.error(f"创建捐赠登记失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建捐赠登记失败，请联系管理员",
        )


@router.get("/registrations", response_model=DonationRegistrationListResponse)
@require_telegram_auth
async def get_user_donation_registrations(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取用户的捐赠登记历史"""
    try:
        user_id = user.id
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="用户信息不完整"
            )

        per_page = min(per_page, 100)

        registrations = donation_service.get_donation_registrations_by_user(
            user_id, limit=per_page
        )

        registration_responses = [
            DonationRegistrationResponse(**reg) for reg in registrations
        ]

        return DonationRegistrationListResponse(
            success=True,
            data=registration_responses,
            total=len(registration_responses),
            page=page,
            per_page=per_page,
        )

    except HTTPException:
        raise
    except errors.DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except Exception as e:
        logger.error(f"获取用户捐赠登记历史失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务器内部错误"
        )


@router.get("/registrations/pending", response_model=DonationRegistrationListResponse)
@require_telegram_auth
async def get_pending_donation_registrations(
    request: Request, limit: int = 50, user: TelegramUser = Depends(get_telegram_user)
):
    """获取待处理的捐赠登记列表（管理员专用）"""
    try:
        check_admin_permission(user)
        limit = min(limit, 200)

        registrations = donation_service.get_pending_donation_registrations(limit=limit)

        registration_responses = [
            DonationRegistrationResponse(**reg) for reg in registrations
        ]

        return DonationRegistrationListResponse(
            success=True,
            data=registration_responses,
            total=len(registration_responses),
            page=1,
            per_page=limit,
        )

    except HTTPException:
        raise
    except errors.DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except Exception as e:
        logger.error(f"获取待处理捐赠登记失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务器内部错误"
        )


@router.get(
    "/registrations/{registration_id}",
    response_model=DonationRegistrationDetailResponse,
)
@require_telegram_auth
async def get_donation_registration_detail(
    registration_id: int,
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取捐赠登记详情"""
    try:
        user_id = user.id
        is_admin = user.id in settings.TG_ADMIN_CHAT_ID

        registration = donation_service.get_donation_registration_by_id(registration_id)

        if not registration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="捐赠登记记录不存在"
            )

        # 检查权限：只能查看自己的记录或管理员可以查看所有记录
        if not is_admin and registration["user_id"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="无权限访问此记录"
            )

        return DonationRegistrationDetailResponse(
            success=True, data=DonationRegistrationResponse(**registration)
        )

    except HTTPException:
        raise
    except errors.DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except Exception as e:
        logger.error(f"获取捐赠登记详情失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务器内部错误"
        )


@router.post(
    "/registrations/{registration_id}/confirm",
    response_model=DonationRegistrationConfirmResponse,
)
@require_telegram_auth
async def confirm_donation_registration(
    registration_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    confirm_data: DonationRegistrationUpdate,
    user: TelegramUser = Depends(get_telegram_user),
):
    """确认捐赠登记（管理员专用）"""
    try:
        check_admin_permission(user)
        admin_id = user.id

        updated = await donation_service.confirm_donation_registration(
            registration_id=registration_id,
            admin_id=admin_id,
            approved=confirm_data.approved,
            admin_note=confirm_data.admin_note,
        )

        action = "批准" if confirm_data.approved else "拒绝"
        message = f"捐赠登记已{action}"

        return DonationRegistrationConfirmResponse(
            success=True,
            message=message,
            data=DonationRegistrationResponse(**updated),
        )

    except HTTPException:
        raise
    except errors.DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except Exception as e:
        logger.error(f"确认捐赠登记失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务器内部错误"
        )


@router.get("/statistics")
@require_telegram_auth
async def get_donation_statistics(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取捐赠统计信息（管理员专用）"""
    try:
        check_admin_permission(user)
        stats = donation_service.get_donation_statistics()
        return {"success": True, "data": stats}

    except HTTPException:
        raise
    except errors.DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except Exception as e:
        logger.error(f"获取捐赠统计信息失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务器内部错误"
        )
