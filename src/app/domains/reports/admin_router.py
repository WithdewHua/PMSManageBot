from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.core.schemas import TelegramUser
from app.databases import db

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/settings")
@require_telegram_auth
async def get_admin_settings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取管理员设置"""
    check_admin_permission(user)

    try:
        # 从数据库获取免费高级线路列表
        free_premium_lines = db.get_free_premium_lines()

        settings_data = {
            "plex_register": settings.PLEX_REGISTER,
            "emby_register": settings.EMBY_REGISTER,
            "premium_free": settings.PREMIUM_FREE,
            "premium_unlock_enabled": settings.PREMIUM_UNLOCK_ENABLED,
            "lines": settings.STREAM_BACKEND,
            "premium_lines": settings.PREMIUM_STREAM_BACKEND,
            "free_premium_lines": free_premium_lines,
            "invitation_credits": settings.INVITATION_CREDITS,
            "unlock_credits": settings.UNLOCK_CREDITS,
            "premium_daily_credits": settings.PREMIUM_DAILY_CREDITS,
            "user_traffic_limit": settings.USER_TRAFFIC_LIMIT,
            "premium_user_traffic_limit": settings.PREMIUM_USER_TRAFFIC_LIMIT,
            "credits_transfer_enabled": settings.CREDITS_TRANSFER_ENABLED,  # 添加积分转移开关
            "line_schedule_unlock_credits": settings.LINE_SCHEDULE_UNLOCK_CREDITS,  # 解锁线路调度功能所需积分
            "download_unlock_credits": settings.DOWNLOAD_UNLOCK_CREDITS,  # 解锁下载/同步功能所需积分
        }

        logger.info(f"管理员 {user.username or user.id} 获取系统设置")
        return settings_data
    except Exception as e:
        logger.error(f"获取管理员设置失败: {e!s}")
        raise HTTPException(status_code=500, detail="获取设置失败")
