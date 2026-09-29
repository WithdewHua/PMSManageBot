from fastapi import APIRouter, Body, Depends, Request

from app.core.log import uvicorn_logger as logger
from app.domains.traffic import service as traffic_service
from app.transport.http.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.transport.http.schemas import BaseResponse, TelegramUser

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/settings/user-traffic-limit")
@require_telegram_auth
async def set_user_traffic_limit(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置普通用户每日免费 Premium 流量额度"""
    check_admin_permission(user)

    try:
        traffic_limit = data.get(
            "traffic_limit", traffic_service.get_user_traffic_limit()
        )

        if (
            isinstance(traffic_limit, bool)
            or not isinstance(traffic_limit, int)
            or traffic_limit < 0
        ):
            return BaseResponse(success=False, message="流量额度必须是非负整数")

        traffic_service.set_user_traffic_limit(traffic_limit)

        logger.info(
            f"管理员 {user.username or user.id} 设置普通用户每日免费 Premium 流量额度为: {traffic_limit} 字节"
        )
        return BaseResponse(
            success=True,
            message=f"普通用户每日免费 Premium 流量额度已设置为 {traffic_limit} 字节",
        )
    except Exception as e:
        logger.error(f"设置普通用户每日免费 Premium 流量额度失败: {e!s}")
        return BaseResponse(success=False, message="设置失败")
