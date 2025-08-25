from app.config import settings
from app.db import DB
from app.log import uvicorn_logger as logger
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.schemas import TelegramUser
from fastapi import APIRouter, Depends, HTTPException, Request

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/stats")
@require_telegram_auth
async def get_system_stats(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取系统统计信息（不需要管理员权限）"""
    logger.info(f"{user.username or user.first_name or user.id} 获取系统统计信息")

    db = DB()
    try:
        # 获取所有Plex用户数量
        plex_users_count = db.get_plex_users_num()

        # 获取所有Emby用户数量
        emby_users_count = db.get_emby_users_num()

        # 获取总用户数量（去重，避免同时绑定两个服务的用户被重复计算）
        # 1. 先统计有 tg_id 的用户（通过 tg_id 去重）
        # 2. 再统计没有 tg_id 的用户（这些用户无法去重，按账户数量计算）
        total_users_query = """
        SELECT 
            (SELECT COUNT(DISTINCT tg_id) FROM (
                SELECT tg_id FROM user WHERE tg_id IS NOT NULL
                UNION
                SELECT tg_id FROM emby_user WHERE tg_id IS NOT NULL
            )) +
            (SELECT COUNT(*) FROM user WHERE tg_id IS NULL) +
            (SELECT COUNT(*) FROM emby_user WHERE tg_id IS NULL)
        """
        rslt = db.cur.execute(total_users_query)
        total_users_count = rslt.fetchone()[0]

        stats = {
            "plex_users": plex_users_count,
            "emby_users": emby_users_count,
            "total_users": total_users_count,
        }

        logger.info(f"系统统计信息: {stats}")
        return stats

    except Exception as e:
        logger.error(f"获取系统统计信息失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取系统统计信息失败")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


@router.get("/status")
async def get_system_status():
    """获取系统状态信息（公开接口，不需要登录）"""
    try:
        status_data = {
            "plex_register": settings.PLEX_REGISTER,
            "emby_register": settings.EMBY_REGISTER,
            "premium_unlock_enabled": settings.PREMIUM_UNLOCK_ENABLED,
            "premium_daily_credits": settings.PREMIUM_DAILY_CREDITS,
            "credits_transfer_enabled": settings.CREDITS_TRANSFER_ENABLED,
            "community_links": {
                "group": getattr(settings, "TG_GROUP", ""),
                "channel": getattr(
                    settings, "TG_CHANNEL", getattr(settings, "TG_GROUP", "")
                ),  # 如果没有单独的频道，使用群组链接
            },
        }

        logger.info("获取系统状态信息")
        return status_data
    except Exception as e:
        logger.error(f"获取系统状态信息失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取系统状态信息失败")


@router.get("/traffic-overview")
@require_telegram_auth
async def get_traffic_overview(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取流量统计概览数据（不需要管理员权限）"""
    logger.info(f"{user.username or user.first_name or user.id} 获取流量统计概览")

    db = DB()
    try:
        traffic_stats = db.get_traffic_statistics()
        logger.info("流量统计概览数据获取成功")

        return {
            "success": True,
            "message": "获取成功",
            "data": traffic_stats,
        }
    except Exception as e:
        logger.error(f"获取流量统计概览失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取流量统计失败")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")
