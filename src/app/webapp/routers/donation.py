from app.config import settings
from app.databases.db import DB
from app.log import logger
from app.utils.utils import get_user_name_from_tg_id, send_message_by_url
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.routers.admin import check_admin_permission
from app.webapp.schemas import TelegramUser
from app.webapp.schemas.donation import (
    DonationRegistrationConfirmResponse,
    DonationRegistrationCreate,
    DonationRegistrationCreateResponse,
    DonationRegistrationDetailResponse,
    DonationRegistrationListResponse,
    DonationRegistrationResponse,
    DonationRegistrationUpdate,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status

router = APIRouter(prefix="/api/donations", tags=["donations"])


@router.post("/register", response_model=DonationRegistrationCreateResponse)
@require_telegram_auth
async def create_donation_registration(
    request: Request,
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

        db = DB()

        # 创建捐赠登记记录
        success = db.create_donation_registration(
            user_id=user_id,
            payment_method=registration_data.payment_method.value,
            amount=registration_data.amount,
            note=registration_data.note,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="创建捐赠登记失败",
            )

        # 获取刚创建的记录
        registrations = db.get_donation_registrations_by_user(user_id, limit=1)
        if not registrations:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="获取创建的登记记录失败",
            )

        registration = registrations[0]

        # 发送管理员通知
        for admin in settings.TG_ADMIN_CHAT_ID:
            await send_message_by_url(
                chat_id=admin,
                text=f"用户 {get_user_name_from_tg_id(user_id)} 提交了捐赠登记: {registration_data.payment_method.value} {registration_data.amount}元",
            )

        logger.info(
            f"用户 {user_id} 提交了捐赠登记: {registration_data.payment_method.value} {registration_data.amount}元"
        )

        db.close()

        return DonationRegistrationCreateResponse(
            success=True,
            message="捐赠登记提交成功，管理员将在 24 小时内处理",
            data=DonationRegistrationResponse(**registration),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建捐赠登记失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务器内部错误"
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

        # 限制分页参数
        per_page = min(per_page, 100)

        db = DB()
        registrations = db.get_donation_registrations_by_user(user_id, limit=per_page)
        db.close()

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
        # 检查管理员权限
        check_admin_permission(user)
        # 限制查询数量
        limit = min(limit, 200)

        db = DB()
        registrations = db.get_pending_donation_registrations(limit=limit)
        db.close()

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

        db = DB()
        registration = db.get_donation_registration_by_id(registration_id)
        db.close()

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
    confirm_data: DonationRegistrationUpdate,
    user: TelegramUser = Depends(get_telegram_user),
):
    """确认捐赠登记（管理员专用）"""
    try:
        # 检查管理员权限
        check_admin_permission(user)
        admin_id = user.id

        db = DB()

        # 检查登记记录是否存在
        registration = db.get_donation_registration_by_id(registration_id)
        if not registration:
            db.close()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="捐赠登记记录不存在"
            )

        # 检查状态是否为待处理
        if registration["status"] != "pending":
            db.close()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"此登记记录状态为 {registration['status']}，无法处理",
            )

        # 确认登记
        success = db.confirm_donation_registration(
            registration_id=registration_id,
            approved=confirm_data.approved,
            admin_note=confirm_data.admin_note,
            processed_by=admin_id,
        )

        if not success:
            db.close()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="处理捐赠登记失败",
            )

        # 获取更新后的记录
        updated_registration = db.get_donation_registration_by_id(registration_id)
        db.close()

        action = "批准" if confirm_data.approved else "拒绝"
        message = f"捐赠登记已{action}"

        # 记录管理员操作
        logger.info(f"管理员 {admin_id} {action}了捐赠登记 {registration_id}")

        # TODO: 发送用户通知

        return DonationRegistrationConfirmResponse(
            success=True,
            message=message,
            data=DonationRegistrationResponse(**updated_registration),
        )

    except HTTPException:
        raise
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
        # 检查管理员权限
        check_admin_permission(user)
        db = DB()
        stats = db.get_donation_statistics()
        db.close()

        return {"success": True, "data": stats}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取捐赠统计信息失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务器内部错误"
        )
