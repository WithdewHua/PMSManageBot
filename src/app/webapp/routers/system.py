from app.config import settings
from app.databases import db
from app.databases.session import get_session
from app.log import uvicorn_logger as logger
from app.models.models import EmbyUser, PlexUser
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.schemas import TelegramUser
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/stats")
@require_telegram_auth
async def get_system_stats(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取系统统计信息（不需要管理员权限）"""
    logger.info(f"{user.username or user.first_name or user.id} 获取系统统计信息")

    try:
        # 获取所有Plex用户数量
        plex_users_count = db.get_plex_users_num()

        # 获取所有Emby用户数量
        emby_users_count = db.get_emby_users_num()

        # 获取 NSFW 解锁用户数量
        nsfw_unlocked_users_count = db.get_nsfw_unlocked_users_num()

        # 获取线路调度解锁用户数量
        line_schedule_unlocked_users_count = db.get_line_schedule_unlocked_users_num()

        # 获取 Vaultwarden 兑换次数
        vaultwarden_redeemed_count = db.get_vaultwarden_redeemed_users_num()

        # 获取总用户数量（去重，避免同时绑定两个服务的用户被重复计算）
        with get_session() as session:
            # 1. 统计有 tg_id 的唯一用户（通过 UNION 去重）
            plex_tg_ids = select(PlexUser.tg_id).where(PlexUser.tg_id.isnot(None))
            emby_tg_ids = select(EmbyUser.tg_id).where(EmbyUser.tg_id.isnot(None))
            union_query = plex_tg_ids.union(emby_tg_ids)
            # 修复笛卡尔积警告：直接对子查询计数
            union_subquery = union_query.subquery()
            unique_tg_count = session.execute(
                select(func.count()).select_from(union_subquery)
            ).scalar()

            # 2. 统计没有 tg_id 的用户
            plex_no_tg = session.execute(
                select(func.count())
                .select_from(PlexUser)
                .where(PlexUser.tg_id.is_(None))
            ).scalar()
            emby_no_tg = session.execute(
                select(func.count())
                .select_from(EmbyUser)
                .where(EmbyUser.tg_id.is_(None))
            ).scalar()

            total_users_count = unique_tg_count + plex_no_tg + emby_no_tg

        stats = {
            "plex_users": plex_users_count,
            "emby_users": emby_users_count,
            "total_users": total_users_count,
            "nsfw_unlocked_users": nsfw_unlocked_users_count,
            "line_schedule_unlocked_users": line_schedule_unlocked_users_count,
            "vaultwarden_redeemed_count": vaultwarden_redeemed_count,
        }

        logger.info(f"系统统计信息: {stats}")
        return stats

    except Exception as e:
        logger.error(f"获取系统统计信息失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取系统统计信息失败")


@router.get("/status")
async def get_system_status():
    """获取系统状态信息（公开接口，不需要登录）"""
    try:
        status_data = {
            "site_name": settings.SITE_NAME,
            "emby_entry_url": settings.EMBY_ENTRY_URL or settings.EMBY_BASE_URL,
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
