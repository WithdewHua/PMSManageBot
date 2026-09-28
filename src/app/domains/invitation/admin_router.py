from fastapi import APIRouter, Body, Depends, Request

from app.core.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.core.log import uvicorn_logger as logger
from app.core.schemas import BaseResponse, TelegramUser
from app.core.telegram import get_user_name_from_tg_id, send_message_by_url
from app.databases import db
from app.domains.invitation import service as invitation_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/settings/invitation-credits")
@require_telegram_auth
async def set_invitation_credits(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置邀请码生成所需积分"""
    check_admin_permission(user)

    try:
        credits = data.get("credits", 288)

        # 验证积分值的合理性
        if isinstance(credits, bool) or not isinstance(credits, int) or credits < 0:
            return BaseResponse(success=False, message="积分值必须是非负整数")

        invitation_service.set_invitation_credits(credits)

        logger.info(
            f"管理员 {user.username or user.id} 设置邀请码生成所需积分为: {credits}"
        )
        return BaseResponse(
            success=True, message=f"邀请码生成所需积分已设置为 {credits}"
        )
    except Exception as e:
        logger.error(f"设置邀请码积分失败: {e!s}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/invite-codes/generate")
@require_telegram_auth
async def generate_admin_invite_codes(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """管理员生成邀请码"""
    check_admin_permission(user)

    try:
        tg_id = data.get("tg_id")
        count = data.get("count", 1)
        is_premium = data.get("is_premium", False)
        note = data.get("note", "")

        if not tg_id or count <= 0 or count > 100:
            return BaseResponse(success=False, message="参数错误")

        # 导入生成邀请码的函数
        from app.domains.invitation.service import add_redeem_code

        # 检查目标用户是否存在
        stats_info = db.get_stats_by_tg_id(tg_id)
        if not stats_info:
            return BaseResponse(success=False, message="目标用户不存在")

        # 使用 add_redeem_code 生成邀请码
        try:
            add_redeem_code(tg_id=tg_id, num=count, is_privileged=is_premium)
            success_count = count
        except Exception as e:
            logger.error(f"生成邀请码失败: {e!s}")
            return BaseResponse(success=False, message=f"生成邀请码失败: {e!s}")

        # 获取用户显示名称
        user_name = get_user_name_from_tg_id(tg_id)

        logger.info(
            f"管理员 {user.username or user.id} 为用户 {user_name}({tg_id}) 生成了 {success_count} 个{'特权' if is_premium else '普通'}邀请码"
            + (f", 备注: {note}" if note else "")
        )

        # 发送通知给用户
        try:
            await send_message_by_url(
                chat_id=tg_id,
                text=f"""
🎫 管理员为您生成了{"特权" if is_premium else "普通"}邀请码！

📊 生成数量: {success_count} 个

您可以在面板中查看完整的邀请码列表。
"""
                + (f"""📝 备注: {note}""" if note else ""),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"发送邀请码通知失败: {e!s}")

        message = f"成功为 {user_name} 生成 {success_count} 个{'特权' if is_premium else '普通'}邀请码"

        return BaseResponse(success=True, message=message)

    except Exception as e:
        logger.error(f"管理员生成邀请码失败: {e!s}")
        return BaseResponse(success=False, message=f"生成邀请码失败: {e!s}")
