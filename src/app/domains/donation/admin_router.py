import asyncio

from fastapi import APIRouter, Body, Depends, Request

from app.core.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.core.schemas import BaseResponse, TelegramUser
from app.databases import db
from app.utils.utils import (
    get_user_name_from_tg_id,
    send_message_by_url,
)

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

        # 获取当前捐赠金额
        stats_info = db.get_stats_by_tg_id(tg_id)
        if not stats_info:
            return BaseResponse(success=False, message="用户不存在")

        current_donation = stats_info[1] if stats_info[1] else 0
        new_donation = round(current_donation + float(amount), 2)
        current_credits = stats_info[2] if stats_info[2] else 0
        new_credits = round(
            current_credits + float(amount) * settings.DONATION_MULTIPLIER, 2
        )  # 捐赠金额的倍数作为积分

        # 更新捐赠金额
        success = db.update_user_donation(new_donation, tg_id)

        if success:
            # 更新积分
            db.update_user_credits(new_credits, tg_id=tg_id)

            # 获取用户显示名称
            user_name = get_user_name_from_tg_id(tg_id)

            logger.info(
                f"管理员 {user.username or user.id} 为用户 {user_name}({tg_id}) 添加捐赠记录: {amount}元"
                + (f", 备注: {note}" if note else "")
            )

            # 发送通知给用户
            try:
                await send_message_by_url(
                    chat_id=tg_id,
                    text=f"""
感谢您的捐赠！

💰 本次捐赠: {amount}元
💳 累计捐赠: {new_donation}元
"""
                    + (f"""📝 备注: {note}""" if note else ""),
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning(f"发送捐赠通知失败: {e!s}")

            # 检查并授予至尊贡献者勋章（异步后台任务）
            from app.databases.db_func import (
                check_and_award_supreme_contributor_badge,
            )

            asyncio.create_task(check_and_award_supreme_contributor_badge(tg_id))

            return BaseResponse(
                success=True, message=f"成功为 {user_name} 添加 {amount}元 捐赠记录"
            )
        else:
            return BaseResponse(success=False, message="更新捐赠记录失败")

    except Exception as e:
        logger.error(f"提交捐赠记录失败: {e!s}")
        return BaseResponse(success=False, message="提交失败")
