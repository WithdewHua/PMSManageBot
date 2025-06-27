from app.config import settings
from app.db import DB
from app.emby import Emby
from app.log import uvicorn_logger as logger
from app.plex import Plex
from app.utils import get_user_avatar_from_tg_id, get_user_name_from_tg_id
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.schemas import TelegramUser
from fastapi import APIRouter, Depends, HTTPException, Request

router = APIRouter(prefix="/api", tags=["rankings"])


@router.get("/rankings/credits")
@require_telegram_auth
async def get_credits_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取积分排行榜数据"""
    logger.info(f"{user.username or user.first_name or user.id} 开始获取积分排行榜数据")

    db = DB()
    try:
        credits_rankings = []
        try:
            logger.debug("正在查询积分排行")
            credits_data = db.get_credits_rank()
            if credits_data:
                credits_rankings = [
                    {
                        "name": get_user_name_from_tg_id(info[0]),
                        "credits": info[1],
                        "avatar": get_user_avatar_from_tg_id(info[0]),
                        "is_self": info[0] == user.id,  # tg_id 比较
                    }
                    for info in credits_data
                    if info[1] > 0 and info[0] not in settings.ADMIN_CHAT_ID
                ]
        except Exception as e:
            logger.error(f"获取积分排行失败: {str(e)}")

        logger.info(
            f"{user.username or user.first_name or user.id} 获取积分排行榜数据成功"
        )
        return {"credits_rank": credits_rankings}
    except Exception as e:
        logger.error(f"获取积分排行榜数据时发生未预期的错误: {str(e)}")
        raise HTTPException(status_code=500, detail="获取积分排行榜数据失败")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


@router.get("/rankings/donation")
@require_telegram_auth
async def get_donation_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取捐赠排行榜数据"""
    logger.info(f"{user.username or user.first_name or user.id} 开始获取捐赠排行榜数据")

    db = DB()
    try:
        donation_rankings = []
        try:
            logger.debug("正在查询捐赠排行")
            donation_data = db.get_donation_rank()
            if donation_data:
                donation_rankings = [
                    {
                        "name": get_user_name_from_tg_id(info[0]),
                        "donation": info[1],
                        "avatar": get_user_avatar_from_tg_id(info[0]),
                        "is_self": info[0] == user.id,  # tg_id 比较
                    }
                    for info in donation_data
                    if info[1] > 0
                ]
        except Exception as e:
            logger.error(f"获取捐赠排行失败: {str(e)}")

        logger.info(
            f"{user.username or user.first_name or user.id} 获取捐赠排行榜数据成功"
        )
        return {"donation_rank": donation_rankings}
    except Exception as e:
        logger.error(f"获取捐赠排行榜数据时发生未预期的错误: {str(e)}")
        raise HTTPException(status_code=500, detail="获取捐赠排行榜数据失败")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


@router.get("/rankings/watched-time/plex")
@require_telegram_auth
async def get_plex_watched_time_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取Plex观看时长排行榜数据"""
    logger.info(
        f"{user.username or user.first_name or user.id} 开始获取Plex观看时长排行榜数据"
    )

    db = DB()
    try:
        watched_time_rank_plex = []
        try:
            logger.debug("正在查询Plex播放时长排行")
            plex_watch_time_data = db.get_plex_watched_time_rank()
            if plex_watch_time_data:
                watched_time_rank_plex = [
                    {
                        "name": info[2],
                        "watched_time": info[3],
                        "avatar": Plex.get_user_avatar_by_username(info[2]),
                        "is_premium": bool(info[4])
                        if len(info) > 4 and info[4] is not None
                        else False,
                        "is_self": info[1] == user.id,  # tg_id 比较
                    }
                    for info in plex_watch_time_data
                    if info[3] > 0
                ]
        except Exception as e:
            logger.error(f"获取Plex播放时长排行失败: {str(e)}")

        logger.info(
            f"{user.username or user.first_name or user.id} 获取Plex观看时长排行榜数据成功"
        )
        return {"watched_time_rank_plex": watched_time_rank_plex}
    except Exception as e:
        logger.error(f"获取Plex观看时长排行榜数据时发生未预期的错误: {str(e)}")
        raise HTTPException(status_code=500, detail="获取Plex观看时长排行榜数据失败")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


@router.get("/rankings/watched-time/emby")
@require_telegram_auth
async def get_emby_watched_time_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取Emby观看时长排行榜数据"""
    logger.info(
        f"{user.username or user.first_name or user.id} 开始获取Emby观看时长排行榜数据"
    )

    db = DB()
    try:
        watched_time_rank_emby = []
        emby = Emby()
        try:
            logger.debug("正在查询Emby播放时长排行")
            emby_watch_time_data = db.get_emby_watched_time_rank()
            if emby_watch_time_data:
                watched_time_rank_emby = [
                    {
                        "name": info[1],
                        "watched_time": info[2],
                        "avatar": emby.get_user_avatar_by_username(
                            info[1], from_emby=False
                        ),
                        "is_premium": bool(info[3])
                        if len(info) > 3 and info[3] is not None
                        else False,
                        "is_self": info[4] == user.id
                        if len(info) > 4
                        else False,  # tg_id 比较
                    }
                    for info in emby_watch_time_data
                    if info[2] > 0
                ]
        except Exception as e:
            logger.error(f"获取Emby播放时长排行失败: {str(e)}")

        logger.info(
            f"{user.username or user.first_name or user.id} 获取Emby观看时长排行榜数据成功"
        )
        return {"watched_time_rank_emby": watched_time_rank_emby}
    except Exception as e:
        logger.error(f"获取Emby观看时长排行榜数据时发生未预期的错误: {str(e)}")
        raise HTTPException(status_code=500, detail="获取Emby观看时长排行榜数据失败")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


@router.get("/rankings/traffic/plex")
@require_telegram_auth
async def get_plex_traffic_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取 Plex 今日流量排行榜数据"""
    logger.info(
        f"{user.username or user.first_name or user.id} 开始获取 Plex 流量排行榜数据"
    )

    db = DB()
    try:
        traffic_rank_plex = []
        try:
            logger.debug("正在查询 Plex 流量排行")
            plex_traffic_data = db.get_plex_traffic_rank()
            if plex_traffic_data:
                traffic_rank_plex = [
                    {
                        "name": info[0],  # username
                        "traffic": info[2],  # total_traffic
                        "avatar": Plex.get_user_avatar_by_username(info[0]),
                        "is_premium": bool(info[3])
                        if info[3] is not None
                        else False,  # is_premium
                        "is_self": info[4] == user.id
                        if info[4]
                        else False,  # tg_id 比较
                    }
                    for info in plex_traffic_data
                    if info[2] > 0  # 流量大于0
                ]
        except Exception as e:
            logger.error(f"获取 Plex 流量排行失败: {str(e)}")

        logger.info(
            f"{user.username or user.first_name or user.id} 获取 Plex 流量排行榜数据成功"
        )
        return {"traffic_rank_plex": traffic_rank_plex}
    except Exception as e:
        logger.error(f"获取 Plex 流量排行榜数据时发生未预期的错误: {str(e)}")
        raise HTTPException(status_code=500, detail="获取 Plex 流量排行榜数据失败")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


@router.get("/rankings/traffic/emby")
@require_telegram_auth
async def get_emby_traffic_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取 Emby 今日流量排行榜数据"""
    logger.info(
        f"{user.username or user.first_name or user.id} 开始获取 Emby 流量排行榜数据"
    )

    db = DB()
    try:
        traffic_rank_emby = []
        emby = Emby()
        try:
            logger.debug("正在查询 Emby 流量排行")
            emby_traffic_data = db.get_emby_traffic_rank()
            if emby_traffic_data:
                traffic_rank_emby = [
                    {
                        "name": info[0],  # username
                        "traffic": info[2],  # total_traffic
                        "avatar": emby.get_user_avatar_by_username(
                            info[0], from_emby=False
                        ),
                        "is_premium": bool(info[3])
                        if info[3] is not None
                        else False,  # is_premium
                        "is_self": info[4] == user.id
                        if info[4]
                        else False,  # tg_id 比较
                    }
                    for info in emby_traffic_data
                    if info[2] > 0  # 流量大于0
                ]
        except Exception as e:
            logger.error(f"获取 Emby 流量排行失败: {str(e)}")

        logger.info(
            f"{user.username or user.first_name or user.id} 获取 Emby 流量排行榜数据成功"
        )
        return {"traffic_rank_emby": traffic_rank_emby}
    except Exception as e:
        logger.error(f"获取 Emby 流量排行榜数据时发生未预期的错误: {str(e)}")
        raise HTTPException(status_code=500, detail="获取 Emby 流量排行榜数据失败")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")
