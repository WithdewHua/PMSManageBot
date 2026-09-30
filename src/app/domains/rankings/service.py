"""Ranking workflows exposed to interface modules."""

from __future__ import annotations

from datetime import datetime

from app.core.config import settings
from app.core.log import logger
from app.domains.blackjack import service as blackjack_service
from app.domains.invitation import service as invitation_service
from app.domains.luckywheel import service as luckywheel_service
from app.domains.prediction import service as prediction_service
from app.domains.rankings import repository as rankings_repository
from app.domains.traffic import service as traffic_service
from app.domains.treasure import service as treasure_service
from app.integrations.emby import Emby
from app.integrations.plex import Plex
from app.integrations.telegram.profiles import (
    get_user_names_from_tg_ids,
    load_tg_user_info_cache,
)


def _enrich_profiles_batch(tg_ids: list[int | None]) -> dict[int, tuple[str, str]]:
    """Batch lookup display names and avatars from the Telegram profile cache.

    Returns {tg_id: (display_name, avatar_url)}.
    Per-row failures fallback to empty strings.
    """
    valid_ids = list({int(i) for i in tg_ids if i is not None})
    if not valid_ids:
        return {}

    try:
        names = get_user_names_from_tg_ids(valid_ids)
    except Exception as error:
        logger.error(f"批量读取 Telegram 用户名失败: {error}")
        names = {}

    try:
        cache = load_tg_user_info_cache()
    except Exception as error:
        logger.error(f"读取 Telegram 用户缓存失败: {error}")
        cache = {}

    profiles: dict[int, tuple[str, str]] = {}
    for uid in valid_ids:
        info = cache.get(uid) or {}
        try:
            name = str(names.get(uid) or "")
        except Exception:
            name = ""
        try:
            avatar = str(info.get("photo_url") or "")
        except Exception:
            avatar = ""
        profiles[uid] = (name, avatar)
    return profiles


def _safe_plex_avatar(username: str) -> str:
    try:
        return str(Plex.get_user_avatar_by_username(username) or "")
    except Exception:
        return ""


def _safe_emby_avatar(client: Emby | None, username: str) -> str:
    try:
        if client is None:
            client = Emby()
        return str(client.get_user_avatar_by_username(username, from_emby=False) or "")
    except Exception:
        return ""


def get_credits_rank(
    *,
    limit: int | None = None,
    exclude_admins: bool = True,
    current_user_id: int | None = None,
) -> list[dict]:
    """获取积分榜。"""
    raw_data = rankings_repository.get_credits_rank()
    filtered = [
        row
        for row in raw_data
        if not (exclude_admins and row[0] in settings.TG_ADMIN_CHAT_ID)
    ]
    if limit is not None:
        filtered = filtered[:limit]

    profiles = _enrich_profiles_batch([row[0] for row in filtered])
    return [
        {
            "name": profiles.get(row[0], ("", ""))[0],
            "credits": float(row[1]),
            "avatar": profiles.get(row[0], ("", ""))[1],
            "is_self": bool(current_user_id is not None and row[0] == current_user_id),
            "tg_id": int(row[0]),
        }
        for row in filtered
    ]


def get_donation_rank(
    *,
    limit: int | None = None,
    exclude_admins: bool = True,
    include_zero: bool = False,
    current_user_id: int | None = None,
) -> list[dict]:
    """获取捐赠榜。"""
    raw_data = rankings_repository.get_donation_rank()
    filtered = [
        row
        for row in raw_data
        if (include_zero or row[1] > 0)
        and not (exclude_admins and row[0] in settings.TG_ADMIN_CHAT_ID)
    ]
    if limit is not None:
        filtered = filtered[:limit]

    profiles = _enrich_profiles_batch([row[0] for row in filtered])
    return [
        {
            "name": profiles.get(row[0], ("", ""))[0],
            "donation": float(row[1]),
            "avatar": profiles.get(row[0], ("", ""))[1],
            "is_self": bool(current_user_id is not None and row[0] == current_user_id),
            "tg_id": int(row[0]),
        }
        for row in filtered
    ]


def get_watch_time_rank(
    service: str,
    *,
    limit: int | None = None,
    include_zero: bool = True,
    with_avatar: bool = True,
    current_user_id: int | None = None,
) -> list[dict]:
    """获取观看时长榜。"""
    normalized_service = service.lower().strip()
    if normalized_service == "plex":
        raw_data = rankings_repository.get_plex_watched_time_rank()
        filtered = [row for row in raw_data if include_zero or row[3] > 0]
        if limit is not None:
            filtered = filtered[:limit]
        return [
            {
                "name": str(row[2] or ""),
                "watched_time": float(row[3] or 0),
                "avatar": _safe_plex_avatar(str(row[2])) if with_avatar else "",
                "is_premium": (
                    bool(row[4]) if len(row) > 4 and row[4] is not None else False
                ),
                "is_self": bool(
                    current_user_id is not None
                    and row[1] is not None
                    and row[1] == current_user_id
                ),
            }
            for row in filtered
        ]
    elif normalized_service == "emby":
        raw_data = rankings_repository.get_emby_watched_time_rank()
        filtered = [row for row in raw_data if include_zero or row[2] > 0]
        if limit is not None:
            filtered = filtered[:limit]
        emby_client = Emby() if with_avatar else None
        return [
            {
                "name": str(row[1] or ""),
                "watched_time": float(row[2] or 0),
                "avatar": (
                    _safe_emby_avatar(emby_client, str(row[1])) if with_avatar else ""
                ),
                "is_premium": (
                    bool(row[3]) if len(row) > 3 and row[3] is not None else False
                ),
                "is_self": bool(
                    current_user_id is not None
                    and len(row) > 4
                    and row[4] is not None
                    and row[4] == current_user_id
                ),
            }
            for row in filtered
        ]
    else:
        raise ValueError(f"Unsupported media service: {service}")


def get_badge_rank(
    *,
    limit: int | None = None,
    exclude_admins: bool = True,
    current_user_id: int | None = None,
) -> list[dict]:
    """获取勋章榜。"""
    raw_data = rankings_repository.get_badge_rank()
    filtered = [
        item
        for item in raw_data
        if item.get("badge_count", 0) > 0
        and not (exclude_admins and item.get("tg_id") in settings.TG_ADMIN_CHAT_ID)
    ]
    if limit is not None:
        filtered = filtered[:limit]

    profiles = _enrich_profiles_batch([item["tg_id"] for item in filtered])
    return [
        {
            "name": profiles.get(item["tg_id"], ("", ""))[0],
            "badge_count": int(item["badge_count"]),
            "avatar": profiles.get(item["tg_id"], ("", ""))[1],
            "is_self": bool(
                current_user_id is not None and item["tg_id"] == current_user_id
            ),
            "badges": item.get("badges", []),
            "tg_id": int(item["tg_id"]),
        }
        for item in filtered
    ]


def get_invitation_rank(
    *,
    limit: int | None = None,
    exclude_admins: bool = True,
    current_user_id: int | None = None,
) -> list[dict]:
    """获取邀请榜。"""
    raw_data = invitation_service.invitee_counts()
    filtered = [
        row
        for row in raw_data
        if row[1] > 0 and not (exclude_admins and row[0] in settings.TG_ADMIN_CHAT_ID)
    ]
    if limit is not None:
        filtered = filtered[:limit]

    profiles = _enrich_profiles_batch([row[0] for row in filtered])
    return [
        {
            "name": profiles.get(row[0], ("", ""))[0],
            "invite_count": int(row[1]),
            "avatar": profiles.get(row[0], ("", ""))[1],
            "is_self": bool(current_user_id is not None and row[0] == current_user_id),
        }
        for row in filtered
    ]


def get_wheel_credits_rank(
    *,
    limit: int | None = None,
    exclude_admins: bool = True,
    current_user_id: int | None = None,
) -> list[dict]:
    """获取幸运大转盘积分变动榜。"""
    raw_data = rankings_repository.get_wheel_credits_rank()
    filtered = [
        row
        for row in raw_data
        if (row[1] != 0 or row[2] > 0)
        and not (exclude_admins and row[0] in settings.TG_ADMIN_CHAT_ID)
    ]
    if limit is not None:
        filtered = filtered[:limit]

    profiles = _enrich_profiles_batch([row[0] for row in filtered])
    return [
        {
            "name": profiles.get(row[0], ("", ""))[0],
            "earned_credits": float(row[1]),
            "play_count": int(row[2]),
            "avatar": profiles.get(row[0], ("", ""))[1],
            "is_self": bool(current_user_id is not None and row[0] == current_user_id),
            "tg_id": int(row[0]),
        }
        for row in filtered
    ]


def get_wheel_invite_code_rank(
    *,
    limit: int | None = None,
    exclude_admins: bool = True,
    current_user_id: int | None = None,
) -> list[dict]:
    """获取幸运大转盘邀请码获得榜。"""
    raw_data = luckywheel_service.get_wheel_invite_code_rank()
    filtered = [
        row
        for row in raw_data
        if row[1] > 0 and not (exclude_admins and row[0] in settings.TG_ADMIN_CHAT_ID)
    ]
    if limit is not None:
        filtered = filtered[:limit]

    profiles = _enrich_profiles_batch([row[0] for row in filtered])
    return [
        {
            "name": profiles.get(row[0], ("", ""))[0],
            "invite_code_count": int(row[1]),
            "avatar": profiles.get(row[0], ("", ""))[1],
            "is_self": bool(current_user_id is not None and row[0] == current_user_id),
            "tg_id": int(row[0]),
        }
        for row in filtered
    ]


def get_wheel_game_rankings(
    *,
    limit: int | None = None,
    exclude_admins: bool = True,
    current_user_id: int | None = None,
) -> dict[str, list[dict]]:
    """获取转盘游戏综合排行。"""
    return {
        "wheel_credits_rank": get_wheel_credits_rank(
            limit=limit,
            exclude_admins=exclude_admins,
            current_user_id=current_user_id,
        ),
        "wheel_invite_code_rank": get_wheel_invite_code_rank(
            limit=limit,
            exclude_admins=exclude_admins,
            current_user_id=current_user_id,
        ),
    }


def get_treasure_win_issue_rank(
    *,
    limit: int | None = None,
    exclude_admins: bool = True,
    current_user_id: int | None = None,
) -> list[dict]:
    """获取夺宝奇兵中奖期数榜。"""
    raw_data = treasure_service.get_treasure_win_issue_rank()
    filtered = [
        row
        for row in raw_data
        if row[1] > 0 and not (exclude_admins and row[0] in settings.TG_ADMIN_CHAT_ID)
    ]
    if limit is not None:
        filtered = filtered[:limit]

    profiles = _enrich_profiles_batch([row[0] for row in filtered])
    return [
        {
            "name": profiles.get(row[0], ("", ""))[0],
            "win_issue_count": int(row[1]),
            "avatar": profiles.get(row[0], ("", ""))[1],
            "is_self": bool(current_user_id is not None and row[0] == current_user_id),
            "tg_id": int(row[0]),
        }
        for row in filtered
    ]


def get_treasure_win_credits_rank(
    *,
    limit: int | None = None,
    exclude_admins: bool = True,
    current_user_id: int | None = None,
) -> list[dict]:
    """获取夺宝奇兵中奖积分榜。"""
    raw_data = treasure_service.get_treasure_win_credits_rank()
    filtered = [
        row
        for row in raw_data
        if row[1] > 0 and not (exclude_admins and row[0] in settings.TG_ADMIN_CHAT_ID)
    ]
    if limit is not None:
        filtered = filtered[:limit]

    profiles = _enrich_profiles_batch([row[0] for row in filtered])
    return [
        {
            "name": profiles.get(row[0], ("", ""))[0],
            "win_credits": int(row[1]),
            "avatar": profiles.get(row[0], ("", ""))[1],
            "is_self": bool(current_user_id is not None and row[0] == current_user_id),
            "tg_id": int(row[0]),
        }
        for row in filtered
    ]


def get_treasure_game_rankings(
    *,
    limit: int | None = None,
    exclude_admins: bool = True,
    current_user_id: int | None = None,
) -> dict[str, list[dict]]:
    """获取夺宝奇兵综合排行。"""
    return {
        "treasure_win_issue_rank": get_treasure_win_issue_rank(
            limit=limit,
            exclude_admins=exclude_admins,
            current_user_id=current_user_id,
        ),
        "treasure_win_credits_rank": get_treasure_win_credits_rank(
            limit=limit,
            exclude_admins=exclude_admins,
            current_user_id=current_user_id,
        ),
    }


def get_prediction_net_profit_rank() -> list[dict]:
    """暴露预测市场领域的原始净收益排行。"""
    return prediction_service.get_prediction_net_profit_rank()


def get_prediction_win_rate_rank() -> list[dict]:
    """暴露预测市场领域的原始胜率排行。"""
    return prediction_service.get_prediction_win_rate_rank()


def get_blackjack_skill_ranks(min_hands: int | None = None) -> dict:
    """暴露 21 点领域的技巧排行。"""
    return blackjack_service.get_blackjack_skill_ranks(min_hands)


def get_blackjack_max_win_rank() -> list:
    """暴露 21 点领域的单手最大赢利排行。"""
    return blackjack_service.get_blackjack_max_win_rank()


def get_traffic_rank(
    service: str,
    start_date: datetime | None,
    end_date: datetime | None,
    *,
    current_user_id: int | None = None,
) -> list[dict]:
    """获取流量排行榜。"""
    normalized_service = service.lower().strip()
    traffic_data = traffic_service.traffic_rank(
        normalized_service, start_date, end_date
    )
    if not traffic_data:
        return []

    if normalized_service == "plex":
        return [
            {
                "name": info[0],
                "traffic": info[2],
                "avatar": _safe_plex_avatar(info[0]),
                "is_premium": (bool(info[3]) if info[3] is not None else False),
                "is_self": bool(info[4] == current_user_id if info[4] else False),
            }
            for info in traffic_data
            if info[2] > 0
        ]
    elif normalized_service == "emby":
        emby = Emby()
        return [
            {
                "name": info[0],
                "traffic": info[2],
                "avatar": _safe_emby_avatar(emby, info[0]),
                "is_premium": (bool(info[3]) if info[3] is not None else False),
                "is_self": bool(info[4] == current_user_id if info[4] else False),
            }
            for info in traffic_data
            if info[2] > 0
        ]
    else:
        raise ValueError(f"Unsupported media service: {service}")


def get_device_rank(*, limit: int = 30) -> list[dict]:
    """获取 Emby 设备排行数据。"""
    emby = Emby()
    devices_data = sorted(
        emby.get_devices_per_user(),
        key=lambda x: len(x.get("devices") or []),
        reverse=True,
    )
    if limit is not None:
        devices_data = devices_data[:limit]
    return [
        {
            "user_name": user_devices.get("user_name"),
            "device_count": len(user_devices.get("devices") or []),
            "client_count": len(user_devices.get("clients") or []),
            "ip_count": len(user_devices.get("ip") or []),
        }
        for user_devices in devices_data
    ]


__all__ = [
    "get_badge_rank",
    "get_blackjack_max_win_rank",
    "get_blackjack_skill_ranks",
    "get_credits_rank",
    "get_device_rank",
    "get_donation_rank",
    "get_invitation_rank",
    "get_prediction_net_profit_rank",
    "get_prediction_win_rate_rank",
    "get_traffic_rank",
    "get_treasure_game_rankings",
    "get_treasure_win_credits_rank",
    "get_treasure_win_issue_rank",
    "get_watch_time_rank",
    "get_wheel_credits_rank",
    "get_wheel_game_rankings",
    "get_wheel_invite_code_rank",
]


def render_recent_media_rankings() -> str:
    from app.domains.reports import service as reports_service

    body_text = """
======================
<strong>🔥Ranking 24h🔥</strong>
======================

-----------<strong>Plex</strong>-----------
<strong>👤用户榜</strong>
{user_stats}

<strong>🎥电影榜</strong>
{watched_movie_stats}

<strong>📺剧集榜</strong>
{watched_tv_stats}
    """

    emby_body_text = """
-----------<strong>Emby</strong>-----------
<strong>👤用户榜</strong>
{emby_user_stats}

<strong>🎥电影榜</strong>
{emby_watched_movie_stats}

<strong>📺剧集榜</strong>
{emby_watched_tv_stats}
    """

    body_text = reports_service.stats_report(
        days=1,
        top=10,
        user_stats=True,
        watched_stats=True,
        body_text=body_text,
        emby_body_text=emby_body_text,
        emby=True,
    )
    return body_text
