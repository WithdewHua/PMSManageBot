from app.db import DB
from app.log import uvicorn_logger as logger
from app.utils import get_user_name_from_tg_id
from app.webapp.middlewares import require_telegram_auth
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api", tags=["rankings"])


@router.get("/rankings")
@require_telegram_auth
async def get_rankings(request: Request):
    """获取排行榜数据"""
    logger.info("开始获取排行榜数据")

    # 从请求状态中获取验证过的 Telegram 数据
    # telegram_data = request.state.telegram_data

    # 可以选择在此处验证用户权限

    # 连接数据库
    db = DB()
    try:
        # 获取捐赠排行
        donation_rankings = []
        try:
            logger.debug("正在查询捐赠排行")
            donation_data = db.get_donation_rank()
            if donation_data:
                donation_rankings = [
                    {"name": get_user_name_from_tg_id(info[0]), "donation": info[1]}
                    for info in donation_data
                ]
        except Exception as e:
            logger.error(f"获取捐赠排行失败: {str(e)}")

        # 获取播放时长排行
        watched_time_rank_plex, watched_time_rank_emby = [], []
        try:
            logger.debug("正在查询播放时长排行")
            plex_watch_time_data = db.get_plex_watched_time_rank()
            emby_watch_time_data = db.get_emby_watched_time_rank()
            if plex_watch_time_data:
                watched_time_rank_plex = [
                    {"name": info[2], "watched_time": info[3]}
                    for info in plex_watch_time_data
                ]
            if emby_watch_time_data:
                watched_time_rank_emby = [
                    {"name": info[1], "watched_time": info[2]}
                    for info in emby_watch_time_data
                ]
        except Exception as e:
            logger.error(f"获取播放时长排行失败: {str(e)}")

        # 获取积分排行
        credits_rankings = []
        try:
            logger.debug("正在查询积分排行")
            credits_data = db.get_credits_rank()
            if credits_data:
                credits_rankings = [
                    {"name": get_user_name_from_tg_id(info[0]), "credits": info[1]}
                    for info in credits_data
                ]
        except Exception as e:
            logger.error(f"获取积分排行失败: {str(e)}")

        return {
            "donation_rank": donation_rankings,
            "credits_rank": credits_rankings,
            "watched_time_rank_plex": watched_time_rank_plex,
            "watched_time_rank_emby": watched_time_rank_emby,
        }
    except Exception as e:
        logger.error(f"获取排行榜数据时发生未预期的错误: {str(e)}")
        raise HTTPException(status_code=500, detail="获取排行榜数据失败")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")
