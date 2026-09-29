from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.databases import db
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
        # 从数据库获取免费高级线路列表
        free_premium_lines = db.get_free_premium_lines()
        business_config = reports_service.get_business_config_overview()

        settings_data = {
            "plex_register": business_config["plex_register"],
            "emby_register": business_config["emby_register"],
            "premium_free": business_config["premium_free"],
            "premium_unlock_enabled": business_config["premium_unlock_enabled"],
            "lines": settings.STREAM_BACKEND,
            "premium_lines": settings.PREMIUM_STREAM_BACKEND,
            "free_premium_lines": free_premium_lines,
            "invitation_credits": business_config["invitation_credits"],
            "unlock_credits": business_config["unlock_credits"],
            "premium_daily_credits": business_config["premium_daily_credits"],
            "user_traffic_limit": business_config["user_traffic_limit"],
            "premium_user_traffic_limit": business_config["premium_user_traffic_limit"],
            "credits_transfer_enabled": business_config["credits_transfer_enabled"],
            "line_schedule_unlock_credits": business_config[
                "line_schedule_unlock_credits"
            ],
            "download_unlock_credits": business_config["download_unlock_credits"],
            "credits_cost_per_10gb": business_config["credits_cost_per_10gb"],
            "nsfw_libs": business_config["nsfw_libs"],
            "donation_multiplier": business_config["donation_multiplier"],
            "upay_crypto_types": business_config["upay_crypto_types"],
            "vaultwarden_enabled": business_config["vaultwarden_enabled"],
            "vaultwarden_redeem_credits": business_config["vaultwarden_redeem_credits"],
        }

        logger.info(f"管理员 {user.username or user.id} 获取系统设置")
        return settings_data
    except Exception as e:
        logger.error(f"获取管理员设置失败: {e!s}")
        raise HTTPException(status_code=500, detail="获取设置失败")
