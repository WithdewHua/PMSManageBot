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
        # 获取Plex用户数量
        plex_users_count = db.get_plex_users_num()

        # 获取Emby用户数量
        emby_users_count = db.get_emby_users_num()

        # 获取总用户数量（去重，避免同时绑定两个服务的用户被重复计算）
        total_users_query = """
        SELECT COUNT(DISTINCT tg_id) FROM (
            SELECT tg_id FROM user WHERE tg_id IS NOT NULL
            UNION
            SELECT tg_id FROM emby_user WHERE tg_id IS NOT NULL
        )
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
        }

        logger.info("获取系统状态信息")
        return status_data
    except Exception as e:
        logger.error(f"获取系统状态信息失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取系统状态信息失败")
