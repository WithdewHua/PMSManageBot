from app.db import DB
from app.log import uvicorn_logger as logger
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.models import TelegramUser, UserInfo
from fastapi import APIRouter, Depends, HTTPException, Request

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/info")
@require_telegram_auth
async def get_user_info(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取用户信息"""
    user_id = user.id
    user_name = user.username or user.first_name
    # 从数据库获取更多用户信息
    logger.info(f"开始获取用户 {user_name or user_id} 的详细信息")
    # 连接数据库
    db = DB()
    try:
        tg_id = user_id
        user_info = UserInfo(tg_id=tg_id)

        # 获取Plex信息
        try:
            logger.debug(f"正在查询用户 {tg_id} 的Plex信息")
            plex_info = db.get_plex_info_by_tg_id(tg_id)
            if plex_info:
                user_info.plex_info = {
                    "username": plex_info[4],
                    "email": plex_info[3],
                    "watched_time": plex_info[7],
                    "all_lib": plex_info[5] == 1,
                }
                logger.debug(f"用户 {tg_id} 的Plex信息获取成功")
            else:
                logger.debug(f"用户 {tg_id} 没有关联的Plex账户")
        except Exception as e:
            logger.error(f"获取用户 {tg_id} 的Plex信息失败: {str(e)}")

        # 获取Emby信息
        try:
            logger.debug(f"正在查询用户 {tg_id} 的Emby信息")
            emby_info = db.get_emby_info_by_tg_id(tg_id)
            if emby_info:
                user_info.emby_info = {
                    "username": emby_info[0],
                    "watched_time": emby_info[5],
                    "all_lib": emby_info[3] == 1,
                    "line": emby_info[7],
                }
                logger.debug(f"用户 {tg_id} 的Emby信息获取成功")
            else:
                logger.debug(f"用户 {tg_id} 没有关联的Emby账户")
        except Exception as e:
            logger.error(f"获取用户 {tg_id} 的Emby信息失败: {str(e)}")

        # 获取统计信息
        try:
            logger.debug(f"正在查询用户 {tg_id} 的统计信息")
            stats_info = db.get_stats_by_tg_id(tg_id)
            if stats_info:
                user_info.credits = stats_info[2]
                user_info.donation = stats_info[1]
                logger.debug(f"用户 {tg_id} 的统计信息获取成功")
            else:
                logger.debug(f"用户 {tg_id} 没有统计信息")
        except Exception as e:
            logger.error(f"获取用户 {tg_id} 的统计信息失败: {str(e)}")

        # 获取Overseerr信息
        try:
            logger.debug(f"正在查询用户 {tg_id} 的Overseerr信息")
            overseerr_info = db.get_overseerr_info_by_tg_id(tg_id)
            if overseerr_info:
                user_info.overseerr_info = {
                    "user_id": overseerr_info[0],
                    "email": overseerr_info[1],
                }
                logger.debug(f"用户 {tg_id} 的Overseerr信息获取成功")
            else:
                logger.debug(f"用户 {tg_id} 没有关联的Overseerr账户")
        except Exception as e:
            logger.error(f"获取用户 {tg_id} 的Overseerr信息失败: {str(e)}")

        # 获取邀请码
        try:
            logger.debug(f"正在查询用户 {tg_id} 的邀请码")
            codes = db.get_invitation_code_by_owner(tg_id)
            if codes:
                user_info.invitation_codes = codes
                logger.debug(f"用户 {tg_id} 的邀请码获取成功，共 {len(codes)} 个")
            else:
                logger.debug(f"用户 {tg_id} 没有邀请码")
        except Exception as e:
            logger.error(f"获取用户 {tg_id} 的邀请码失败: {str(e)}")

        logger.info(f"用户 {user_name or user_id} 的信息获取完成")
        return user_info
    except Exception as e:
        logger.error(f"获取用户信息时发生未预期的错误: {str(e)}")
        raise HTTPException(status_code=500, detail="获取用户信息失败")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")
