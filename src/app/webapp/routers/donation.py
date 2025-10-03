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
            is_donation_registration=registration_data.is_donation_registration,
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
        registration_type = (
            "捐赠开号" if registration_data.is_donation_registration else "普通捐赠"
        )
        for admin in settings.TG_ADMIN_CHAT_ID:
            await send_message_by_url(
                chat_id=admin,
                text=f"用户 {get_user_name_from_tg_id(user_id)} 提交了{registration_type}登记: {registration_data.payment_method.value} {registration_data.amount}元",
            )

        logger.info(
            f"用户 {user_id} 提交了{'捐赠开号' if registration_data.is_donation_registration else '普通捐赠'}登记: {registration_data.payment_method.value} {registration_data.amount}元"
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

        # 第一步：只更新登记状态
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

        # 第二步：如果批准，处理积分和邀请码
        if confirm_data.approved:
            user_id = registration["user_id"]
            amount = registration["amount"]
            is_donation_registration = registration.get(
                "is_donation_registration", False
            )

            # 更新捐赠金额和积分
            current_stats = db.get_stats_by_tg_id(user_id)
            if current_stats:
                new_donation = current_stats[1] + amount

                if is_donation_registration:
                    # 捐赠开号：只记录捐赠金额，不增加积分
                    new_credits = current_stats[2]  # 保持积分不变
                else:
                    # 普通捐赠：增加捐赠积分
                    new_credits = (
                        current_stats[2] + amount * settings.DONATION_MULTIPLIER
                    )  # 捐赠积分 1:DONATION_MULTIPLIER

                db.cur.execute(
                    "UPDATE statistics SET donation = ?, credits = ? WHERE tg_id = ?",
                    (new_donation, new_credits, user_id),
                )
            else:
                # 如果用户统计记录不存在，创建一个
                if is_donation_registration:
                    # 捐赠开号：只记录捐赠金额
                    db.add_user_data(
                        user_id,
                        credits=0,
                        donation=amount,
                    )
                else:
                    # 普通捐赠：记录捐赠金额和积分
                    db.add_user_data(
                        user_id,
                        credits=amount * settings.DONATION_MULTIPLIER,
                        donation=amount,
                    )

            # 如果是捐赠开号，生成一个普通邀请码
            if is_donation_registration:
                from app.databases.db_func import add_redeem_code

                try:
                    add_redeem_code(tg_id=user_id, num=1, is_privileged=False)
                    logger.info(f"为捐赠开号用户 {user_id} 生成邀请码成功")
                except Exception as e:
                    logger.error(f"为捐赠开号用户 {user_id} 生成邀请码失败: {e}")

            # 提交所有更改
            db.con.commit()

        # 获取更新后的记录
        updated_registration = db.get_donation_registration_by_id(registration_id)
        db.close()

        action = "批准" if confirm_data.approved else "拒绝"
        message = f"捐赠登记已{action}"

        # 记录管理员操作
        logger.info(f"管理员 {admin_id} {action}了捐赠登记 {registration_id}")

        # 发送用户通知
        try:
            user_id = registration["user_id"]
            user_name = get_user_name_from_tg_id(user_id)
            admin_name = get_user_name_from_tg_id(admin_id)

            if confirm_data.approved:
                # 获取登记信息以判断是否为捐赠开号
                is_donation_registration = registration.get(
                    "is_donation_registration", False
                )

                # 批准通知
                notification_text = f"""✅ 您的{'捐赠开号' if is_donation_registration else '捐赠'}登记已批准

📝 登记编号: #{registration_id}
💰 捐赠金额: {registration['amount']}元
💳 支付方式: {registration['payment_method']}
📋 登记类型: {'捐赠开号' if is_donation_registration else '普通捐赠'}
👨‍💼 处理管理员: {admin_name}
⏰ 处理时间: {updated_registration['processed_at']}"""

                if confirm_data.admin_note:
                    notification_text += f"\n📋 管理员备注: {confirm_data.admin_note}"

                if is_donation_registration:
                    notification_text += "\n\n🎫 已为您生成邀请码，可在个人中心查看。"
                    notification_text += "\n📝 捐赠开号只记录捐赠金额，不增加积分。"
                else:
                    notification_text += "\n\n💎 您的捐赠金额和积分已更新。"

                notification_text += "\n\n感谢您的支持！"
            else:
                # 获取登记信息以判断是否为捐赠开号
                is_donation_registration = registration.get(
                    "is_donation_registration", False
                )

                # 拒绝通知
                notification_text = f"""❌ 您的{'捐赠开号' if is_donation_registration else '捐赠'}登记被拒绝

📝 登记编号: #{registration_id}
💰 捐赠金额: {registration['amount']}元
💳 支付方式: {registration['payment_method']}
📋 登记类型: {'捐赠开号' if is_donation_registration else '普通捐赠'}
👨‍💼 处理管理员: {admin_name}
⏰ 处理时间: {updated_registration['processed_at']}"""

                if confirm_data.admin_note:
                    notification_text += f"\n📋 拒绝原因: {confirm_data.admin_note}"
                else:
                    notification_text += "\n📋 拒绝原因: 未提供具体原因"

                notification_text += "\n\n如有疑问，请联系管理员。"

            await send_message_by_url(
                chat_id=user_id,
                text=notification_text,
                parse_mode="HTML",
            )

            logger.info(f"已向用户 {user_name}({user_id}) 发送捐赠登记{action}通知")

        except Exception as e:
            logger.warning(f"发送用户捐赠登记{action}通知失败: {e}")
            # 即使通知发送失败，也不影响主要业务逻辑

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
