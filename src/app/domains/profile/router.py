from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select

from app.core.config import settings
from app.core.db import get_session
from app.core.log import uvicorn_logger as logger
from app.databases import db
from app.domains.identity.models import Statistics
from app.domains.profile.schemas import UserInfo
from app.domains.profile.service import refresh_tg_user_info
from app.domains.traffic import service as traffic_service
from app.integrations.emby import Emby
from app.integrations.telegram.profiles import (
    get_user_info_from_tg_id,
    get_user_name_from_tg_id,
)
from app.transport.http.auth import get_telegram_user, require_telegram_auth
from app.transport.http.schemas import TelegramUser

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/info")
@require_telegram_auth
async def get_user_info(
    request: Request,
    background_tasks: BackgroundTasks,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取用户信息"""
    user_id = user.id
    user_name = user.username or user.first_name
    # 刷新 TG 用户信息
    background_tasks.add_task(refresh_tg_user_info, tg_id=user_id)
    # 从数据库获取更多用户信息
    logger.info(f"开始获取用户 {user_name or user_id} 的详细信息")
    # 连接数据库

    try:
        tg_id = user_id
        is_admin = False
        if tg_id in settings.TG_ADMIN_CHAT_ID:
            is_admin = True
        user_info = UserInfo(tg_id=tg_id, is_admin=is_admin)

        # 获取Plex信息
        try:
            logger.debug(f"正在查询用户 {get_user_name_from_tg_id(tg_id)} 的Plex信息")
            plex_info = db.get_plex_info_by_tg_id(tg_id)
            if plex_info:
                # 获取今日流量消耗
                daily_traffic = traffic_service.daily_usage(
                    user_id=str(plex_info[0]), service="plex"
                )
                # 获取今日 Premium 线路流量消耗
                daily_premium_traffic = traffic_service.daily_usage(
                    user_id=str(plex_info[0]), service="plex", premium_only=True
                )
                # 获取下载权限状态
                download_status = db.check_download_unlock(tg_id, "plex")
                premium_quota_status = db.get_plex_premium_quota_status(plex_info[0])
                projected_premium_debt = min(
                    max(
                        premium_quota_status["current_debt"]
                        + daily_premium_traffic
                        - premium_quota_status["daily_limit"],
                        0,
                    ),
                    premium_quota_status["daily_limit"] * 2,
                )

                user_info.plex_info = {
                    "username": plex_info[4],
                    "email": plex_info[3],
                    "watched_time": plex_info[7],
                    "all_lib": plex_info[5] == 1,
                    "line": plex_info[8],
                    "is_premium": plex_info[9] == 1,
                    "premium_expiry": plex_info[10],
                    "daily_traffic": daily_traffic,
                    "daily_premium_traffic": daily_premium_traffic,
                    "daily_premium_free_remaining": max(
                        premium_quota_status["remaining_free"] - daily_premium_traffic,
                        0,
                    ),
                    "daily_premium_free_limit": premium_quota_status["daily_limit"],
                    "daily_premium_debt": premium_quota_status["current_debt"],
                    "daily_premium_projected_debt": projected_premium_debt,
                    "last_viewed_at": plex_info[11],
                    "download_unlocked": download_status["is_unlocked"],
                    "download_unlock_time": download_status["unlock_time"],
                }
                logger.debug(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 的 Plex 信息获取成功，今日流量: {daily_traffic} bytes, Premium流量: {daily_premium_traffic} bytes"
                )
            else:
                logger.debug(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 没有关联的 Plex 账户"
                )
        except Exception as e:
            logger.error(
                f"获取用户 {get_user_name_from_tg_id(tg_id)} 的 Plex 信息失败: {e!s}"
            )

        # 获取Emby信息
        try:
            logger.debug(f"正在查询用户 {get_user_name_from_tg_id(tg_id)} 的 Emby 信息")
            emby_info = db.get_emby_info_by_tg_id(tg_id)
            if emby_info:
                # 获取今日流量消耗
                daily_traffic = traffic_service.daily_usage(
                    username=emby_info[0], service="emby"
                )
                # 获取今日 Premium 线路流量消耗
                daily_premium_traffic = traffic_service.daily_usage(
                    username=emby_info[0], service="emby", premium_only=True
                )
                # 获取下载权限状态
                download_status = db.check_download_unlock(tg_id, "emby")
                premium_quota_status = db.get_emby_premium_quota_status(emby_info[0])
                projected_premium_debt = min(
                    max(
                        premium_quota_status["current_debt"]
                        + daily_premium_traffic
                        - premium_quota_status["daily_limit"],
                        0,
                    ),
                    premium_quota_status["daily_limit"] * 2,
                )

                user_info.emby_info = {
                    "username": emby_info[0],
                    "watched_time": emby_info[5],
                    "all_lib": emby_info[3] == 1,
                    "line": emby_info[7],
                    "is_premium": emby_info[8] == 1,
                    "premium_expiry": emby_info[9],
                    "daily_traffic": daily_traffic,
                    "daily_premium_traffic": daily_premium_traffic,
                    "daily_premium_free_remaining": max(
                        premium_quota_status["remaining_free"] - daily_premium_traffic,
                        0,
                    ),
                    "daily_premium_free_limit": premium_quota_status["daily_limit"],
                    "daily_premium_debt": premium_quota_status["current_debt"],
                    "daily_premium_projected_debt": projected_premium_debt,
                    "last_viewed_at": emby_info[10],
                    "download_unlocked": download_status["is_unlocked"],
                    "download_unlock_time": download_status["unlock_time"],
                }
                created_at = (
                    Emby().get_user_info_from_username(emby_info[0]).get("date_created")
                )
                if created_at:
                    created_at = created_at.split("T")[0]  # 只保留日期部分
                user_info.emby_info["created_at"] = created_at
                logger.debug(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 的 Emby 信息获取成功，今日流量: {daily_traffic} bytes, Premium流量: {daily_premium_traffic} bytes"
                )
            else:
                logger.debug(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 没有关联的 Emby 账户"
                )
        except Exception as e:
            logger.error(
                f"获取用户 {get_user_name_from_tg_id(tg_id)} 的 Emby 信息失败: {e!s}"
            )

        # 获取统计信息
        try:
            logger.debug(f"正在查询用户 {get_user_name_from_tg_id(tg_id)} 的统计信息")
            stats_info = db.get_stats_by_tg_id(tg_id)
            if stats_info:
                user_info.credits = stats_info[2]
                user_info.donation = stats_info[1]
                logger.debug(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 的统计信息获取成功"
                )
            else:
                logger.debug(f"用户 {get_user_name_from_tg_id(tg_id)} 没有统计信息")
        except Exception as e:
            logger.error(
                f"获取用户 {get_user_name_from_tg_id(tg_id)} 的统计信息失败: {e!s}"
            )

        # 获取邀请人数
        try:
            logger.debug(f"正在查询用户 {get_user_name_from_tg_id(tg_id)} 的邀请人数")
            invitee_count = db.get_invitee_count_by_owner(tg_id)
            user_info.invitee_count = invitee_count
            logger.debug(
                f"用户 {get_user_name_from_tg_id(tg_id)} 的邀请人数获取成功: {invitee_count}"
            )
        except Exception as e:
            logger.error(
                f"获取用户 {get_user_name_from_tg_id(tg_id)} 的邀请人数失败: {e!s}"
            )

        # 获取Overseerr信息
        try:
            logger.debug(
                f"正在查询用户 {get_user_name_from_tg_id(tg_id)} 的Overseerr信息"
            )
            overseerr_info = db.get_overseerr_info_by_tg_id(tg_id)
            if overseerr_info:
                user_info.overseerr_info = {
                    "user_id": overseerr_info[0],
                    "email": overseerr_info[1],
                }
                logger.debug(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 的Overseerr信息获取成功"
                )
            else:
                logger.debug(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 没有关联的Overseerr账户"
                )
        except Exception as e:
            logger.error(
                f"获取用户 {get_user_name_from_tg_id(tg_id)} 的Overseerr信息失败: {e!s}"
            )

        # 获取邀请码
        try:
            logger.debug(f"正在查询用户 {get_user_name_from_tg_id(tg_id)} 的邀请码")
            codes = db.get_invitation_code_by_owner(tg_id)
            if codes:
                user_info.invitation_codes = codes
                logger.debug(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 的邀请码获取成功，共 {len(codes)} 个"
                )
            else:
                logger.debug(f"用户 {get_user_name_from_tg_id(tg_id)} 没有邀请码")
        except Exception as e:
            logger.error(
                f"获取用户 {get_user_name_from_tg_id(tg_id)} 的邀请码失败: {e!s}"
            )

        logger.info(f"用户 {user_name or user_id} 的信息获取完成")
        return user_info
    except Exception as e:
        logger.error(f"获取用户信息时发生未预期的错误: {e!s}")
        raise HTTPException(status_code=500, detail="获取用户信息失败")


@router.get("/users")
@require_telegram_auth
async def get_all_users(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取所有用户信息（用于用户选择）"""

    try:
        with get_session() as session:
            stmt = select(Statistics.tg_id, Statistics.donation, Statistics.credits)
            stats_users = session.execute(stmt).all()

        user_list = []
        for tg_id, donation, credits in stats_users:
            if tg_id:  # 确保tg_id不为空
                # 获取用户的Telegram信息
                tg_info = get_user_info_from_tg_id(tg_id)

                user_list.append(
                    {
                        "tg_id": tg_id,
                        "display_name": tg_info.get("first_name")
                        or tg_info.get("username")
                        or str(tg_id),
                        "photo_url": tg_info.get("photo_url"),
                        "current_donation": float(donation) if donation else 0.0,
                        "current_credits": float(credits) if credits else 0.0,
                    }
                )

        logger.info(
            f"用户 {get_user_name_from_tg_id(user.id)} 获取了 {len(user_list)} 个用户信息"
        )
        return user_list

    except Exception as e:
        logger.error(f"获取用户列表失败: {e!s}")
        raise HTTPException(status_code=500, detail="获取用户列表失败")
