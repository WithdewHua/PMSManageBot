"""Profile aggregation workflows."""

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.domains.identity import service as identity_service
from app.domains.invitation import service as invitation_service
from app.domains.media_access import service as media_access_service
from app.domains.premium import service as premium_service
from app.domains.profile import repository, schemas
from app.domains.traffic import service as traffic_service
from app.integrations import emby as emby_integration
from app.integrations.telegram import profiles as telegram_profiles


async def refresh_tg_user_info(
    tg_id: int | None = None, token: str = settings.TG_API_TOKEN
) -> None:
    """Refresh Telegram profile cache for one user or all known users."""
    stats_users = (
        identity_service.list_statistics_tg_ids() if tg_id is None else [tg_id]
    )
    await telegram_profiles.refresh_tg_user_info(stats_users, token=token)


__all__ = ["get_user_profile", "list_users_for_selection", "refresh_tg_user_info"]


def get_user_profile(tg_id: int, display_name: str | None = None) -> schemas.UserInfo:
    """Assemble independently fallible profile sections using owner capabilities."""
    user_id = tg_id
    user_name = display_name
    tg_id = user_id
    is_admin = False
    if tg_id in settings.TG_ADMIN_CHAT_ID:
        is_admin = True
    user_info = schemas.UserInfo(tg_id=tg_id, is_admin=is_admin)

    # 获取Plex信息
    try:
        logger.debug(
            f"正在查询用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的Plex信息"
        )
        plex_info = identity_service.find_plex_by_tg(tg_id)
        if plex_info:
            # 获取今日流量消耗
            daily_traffic = traffic_service.daily_usage(
                user_id=str(plex_info.plex_id), service="plex"
            )
            # 获取今日 Premium 线路流量消耗
            daily_premium_traffic = traffic_service.daily_usage(
                user_id=str(plex_info.plex_id), service="plex", premium_only=True
            )
            # 获取下载权限状态
            download_status = media_access_service.check_download_unlock(tg_id, "plex")
            premium_quota_status = premium_service.get_plex_premium_quota_status(
                plex_info.plex_id
            )
            projected_premium_debt = premium_service.project_daily_debt(
                premium_quota_status["current_debt"],
                daily_premium_traffic,
                premium_quota_status["daily_limit"],
            )

            user_info.plex_info = {
                "username": plex_info.plex_username,
                "email": plex_info.plex_email,
                "watched_time": plex_info.watched_time,
                "all_lib": plex_info.all_lib == 1,
                "line": plex_info.plex_line,
                "is_premium": plex_info.is_premium == 1,
                "premium_expiry": plex_info.premium_expiry_time,
                "daily_traffic": daily_traffic,
                "daily_premium_traffic": daily_premium_traffic,
                "daily_premium_free_remaining": max(
                    premium_quota_status["remaining_free"] - daily_premium_traffic,
                    0,
                ),
                "daily_premium_free_limit": premium_quota_status["daily_limit"],
                "daily_premium_debt": premium_quota_status["current_debt"],
                "daily_premium_projected_debt": projected_premium_debt,
                "last_viewed_at": plex_info.last_viewed_at,
                "download_unlocked": download_status["is_unlocked"],
                "download_unlock_time": download_status["unlock_time"],
            }
            logger.debug(
                f"用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的 Plex 信息获取成功，今日流量: {daily_traffic} bytes, Premium流量: {daily_premium_traffic} bytes"
            )
        else:
            logger.debug(
                f"用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 没有关联的 Plex 账户"
            )
    except Exception as e:
        logger.error(
            f"获取用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的 Plex 信息失败: {e!s}"
        )

    # 获取Emby信息
    try:
        logger.debug(
            f"正在查询用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的 Emby 信息"
        )
        emby_info = identity_service.find_emby_by_tg(tg_id)
        if emby_info:
            # 获取今日流量消耗
            daily_traffic = traffic_service.daily_usage(
                username=emby_info.emby_username, service="emby"
            )
            # 获取今日 Premium 线路流量消耗
            daily_premium_traffic = traffic_service.daily_usage(
                username=emby_info.emby_username, service="emby", premium_only=True
            )
            # 获取下载权限状态
            download_status = media_access_service.check_download_unlock(tg_id, "emby")
            premium_quota_status = premium_service.get_emby_premium_quota_status(
                emby_info.emby_username
            )
            projected_premium_debt = premium_service.project_daily_debt(
                premium_quota_status["current_debt"],
                daily_premium_traffic,
                premium_quota_status["daily_limit"],
            )

            user_info.emby_info = {
                "username": emby_info.emby_username,
                "watched_time": emby_info.emby_watched_time,
                "all_lib": emby_info.emby_is_unlock == 1,
                "line": emby_info.emby_line,
                "is_premium": emby_info.is_premium == 1,
                "premium_expiry": emby_info.premium_expiry_time,
                "daily_traffic": daily_traffic,
                "daily_premium_traffic": daily_premium_traffic,
                "daily_premium_free_remaining": max(
                    premium_quota_status["remaining_free"] - daily_premium_traffic,
                    0,
                ),
                "daily_premium_free_limit": premium_quota_status["daily_limit"],
                "daily_premium_debt": premium_quota_status["current_debt"],
                "daily_premium_projected_debt": projected_premium_debt,
                "last_viewed_at": emby_info.last_viewed_at,
                "download_unlocked": download_status["is_unlocked"],
                "download_unlock_time": download_status["unlock_time"],
            }
            created_at = (
                emby_integration.Emby()
                .get_user_info_from_username(emby_info.emby_username)
                .get("date_created")
            )
            if created_at:
                created_at = created_at.split("T")[0]  # 只保留日期部分
            user_info.emby_info["created_at"] = created_at
            logger.debug(
                f"用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的 Emby 信息获取成功，今日流量: {daily_traffic} bytes, Premium流量: {daily_premium_traffic} bytes"
            )
        else:
            logger.debug(
                f"用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 没有关联的 Emby 账户"
            )
    except Exception as e:
        logger.error(
            f"获取用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的 Emby 信息失败: {e!s}"
        )

    # 获取统计信息
    try:
        logger.debug(
            f"正在查询用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的统计信息"
        )
        stats_info = identity_service.get_statistics(tg_id)
        if stats_info:
            user_info.credits = stats_info.credits
            user_info.donation = stats_info.donation
            logger.debug(
                f"用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的统计信息获取成功"
            )
        else:
            logger.debug(
                f"用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 没有统计信息"
            )
    except Exception as e:
        logger.error(
            f"获取用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的统计信息失败: {e!s}"
        )

    # 获取邀请人数
    try:
        logger.debug(
            f"正在查询用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的邀请人数"
        )
        invitee_count = invitation_service.get_invitee_count_by_owner(tg_id)
        user_info.invitee_count = invitee_count
        logger.debug(
            f"用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的邀请人数获取成功: {invitee_count}"
        )
    except Exception as e:
        logger.error(
            f"获取用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的邀请人数失败: {e!s}"
        )

    # 获取Overseerr信息
    try:
        logger.debug(
            f"正在查询用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的Overseerr信息"
        )
        overseerr_info = identity_service.find_overseerr_by_tg(tg_id)
        if overseerr_info:
            user_info.overseerr_info = {
                "user_id": overseerr_info.user_id,
                "email": overseerr_info.user_email,
            }
            logger.debug(
                f"用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的Overseerr信息获取成功"
            )
        else:
            logger.debug(
                f"用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 没有关联的Overseerr账户"
            )
    except Exception as e:
        logger.error(
            f"获取用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的Overseerr信息失败: {e!s}"
        )

    # 获取邀请码
    try:
        logger.debug(
            f"正在查询用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的邀请码"
        )
        codes = invitation_service.get_invitation_code_by_owner(tg_id)
        if codes:
            user_info.invitation_codes = codes
            logger.debug(
                f"用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的邀请码获取成功，共 {len(codes)} 个"
            )
        else:
            logger.debug(
                f"用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 没有邀请码"
            )
    except Exception as e:
        logger.error(
            f"获取用户 {telegram_profiles.get_user_name_from_tg_id(tg_id)} 的邀请码失败: {e!s}"
        )

    logger.info(f"用户 {user_name or user_id} 的信息获取完成")
    return user_info


def list_users_for_selection() -> list[dict]:
    """Build the publicly visible transfer-recipient list without admin filtering."""
    users = []
    for tg_id, donation, credits in repository.list_user_balances():
        if not tg_id:
            continue
        tg_info = telegram_profiles.get_user_info_from_tg_id(tg_id)
        users.append(
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
    return users


def get_info_message(tg_id: int) -> str | None:
    """Render the bot-specific account view without HTTP-only enrichment."""
    _plex_info = identity_service.find_plex_by_tg(tg_id)
    _emby_info = identity_service.find_emby_by_tg(tg_id)
    _stats_info = identity_service.get_statistics(tg_id)
    _codes = invitation_service.get_invitation_code_by_owner(tg_id)
    if _plex_info is None and _emby_info is None:
        return None
    _credits = float(_stats_info.credits) if _stats_info else 0.0
    _donation = _stats_info.donation if _stats_info else 0
    _codes = "" if not _codes else "\n".join(_codes)
    body_text = f"""
{"=" * 44}
<strong>可用积分: </strong>{_credits:.2f}
<strong>捐赠金额: </strong>{_donation}
<strong>可用邀请码：</strong>
{_codes}
{"=" * 44}

"""
    if _plex_info:
        body_text += f"""
{"=" * 20} Plex {"=" * 20}
<strong>Plex 用户名：</strong>{_plex_info.plex_username}
<strong>总观看时长：</strong>{_plex_info.watched_time:.2f}h
<strong>当前权限：</strong>{"全部" if _plex_info.all_lib == 1 else "部分"}

"""
    if _emby_info:
        body_text += f"""
{"=" * 20} Emby {"=" * 20}
<strong>Emby 用户名: </strong>{_emby_info.emby_username}
<strong>总观看时长：</strong>{_emby_info.emby_watched_time:.2f}h
<strong>当前权限：</strong>{"全部" if _emby_info.emby_is_unlock == 1 else "部分"}
<strong>当前线路：</strong>{_emby_info.emby_line}
"""
    return body_text
