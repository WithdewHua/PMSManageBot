from fastapi import APIRouter, Body, Depends, Request

from app.core.log import uvicorn_logger as logger
from app.domains.invitation import service as invitation_service
from app.domains.invitation.exceptions import (
    InvitationAccountNotFound,
    InvitationError,
)
from app.integrations.telegram.messaging import send_message_by_url
from app.integrations.telegram.profiles import get_user_name_from_tg_id
from app.transport.http.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.transport.http.schemas import BaseResponse, TelegramUser

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/settings/invitation-credits")
@require_telegram_auth
async def set_invitation_credits(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    check_admin_permission(user)
    try:
        credits = data.get("credits", 288)
        if isinstance(credits, bool) or not isinstance(credits, int) or credits < 0:
            return BaseResponse(success=False, message="积分值必须是非负整数")
        invitation_service.set_invitation_credits(credits)
        logger.info(
            "管理员 %s 设置邀请码生成所需积分为: %s",
            user.username or user.id,
            credits,
        )
        return BaseResponse(
            success=True, message=f"邀请码生成所需积分已设置为 {credits}"
        )
    except Exception as error:
        logger.error("设置邀请码积分失败: %s", error)
        return BaseResponse(success=False, message="设置失败")


@router.post("/invite-codes/generate")
@require_telegram_auth
async def generate_admin_invite_codes(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    check_admin_permission(user)
    try:
        tg_id = data.get("tg_id")
        count = data.get("count", 1)
        privileged = bool(data.get("is_premium", False))
        note = data.get("note", "")
        if not tg_id or not isinstance(count, int) or count <= 0 or count > 100:
            return BaseResponse(success=False, message="参数错误")

        codes = invitation_service.generate_codes(
            int(tg_id),
            count,
            charge=0,
            privileged=privileged,
            require_account=True,
        )
        user_name = get_user_name_from_tg_id(tg_id)
        logger.info(
            "管理员 %s 为用户 %s(%s) 生成了 %s 个%s邀请码%s",
            user.username or user.id,
            user_name,
            tg_id,
            len(codes),
            "特权" if privileged else "普通",
            f", 备注: {note}" if note else "",
        )
        try:
            await send_message_by_url(
                chat_id=tg_id,
                text=(
                    f"🎫 管理员为您生成了{'特权' if privileged else '普通'}邀请码！\n\n"
                    f"📊 生成数量: {len(codes)} 个\n\n"
                    "您可以在面板中查看完整的邀请码列表。"
                    + (f"📝 备注: {note}" if note else "")
                ),
                parse_mode="HTML",
            )
        except Exception as error:
            logger.warning("发送邀请码通知失败: %s", error)
        return BaseResponse(
            success=True,
            message=f"成功为 {user_name} 生成 {len(codes)} 个{'特权' if privileged else '普通'}邀请码",
        )
    except InvitationAccountNotFound:
        return BaseResponse(success=False, message="目标用户不存在")
    except InvitationError as error:
        return BaseResponse(success=False, message=str(error))
    except Exception as error:
        logger.error("管理员生成邀请码失败: %s", error)
        return BaseResponse(success=False, message="生成邀请码失败，请稍后再试")
