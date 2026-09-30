from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.log import uvicorn_logger as logger
from app.domains.reports import service as reports_service
from app.transport.http.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.transport.http.schemas import TelegramUser

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/settings")
@require_telegram_auth
async def get_admin_settings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取管理员设置"""
    check_admin_permission(user)

    try:
        settings_data = reports_service.get_admin_settings_overview()
        logger.info(f"管理员 {user.username or user.id} 获取系统设置")
        return settings_data
    except Exception as e:
        logger.error(f"获取管理员设置失败: {e!s}")
        raise HTTPException(status_code=500, detail="获取设置失败")
