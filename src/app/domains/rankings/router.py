from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.domains.rankings import service as rankings_service
from app.integrations.telegram.profiles import (
    get_user_avatar_from_tg_id,
    get_user_name_from_tg_id,
)
from app.transport.http.auth import get_telegram_user, require_telegram_auth
from app.transport.http.schemas import TelegramUser

router = APIRouter(prefix="/api", tags=["rankings"])


def _safe_name(tg_id: int) -> str:
    try:
        return str(get_user_name_from_tg_id(tg_id) or "")
    except Exception:
        return ""


def _safe_avatar(tg_id: int) -> str:
    try:
        return str(get_user_avatar_from_tg_id(tg_id) or "")
    except Exception:
        return ""


@router.get("/rankings/badge")
@require_telegram_auth
async def get_badge_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取勋章排行榜数据"""
    logger.info(f"{user.username or user.first_name or user.id} 开始获取勋章排行榜数据")

    try:
        badge_rankings = rankings_service.get_badge_rank(
            exclude_admins=True, current_user_id=user.id
        )
        logger.info(
            f"{user.username or user.first_name or user.id} 获取勋章排行榜数据成功"
        )
        return {"badge_rank": badge_rankings}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取勋章排行榜数据时发生未预期的错误: {e!s}")
        raise HTTPException(status_code=500, detail="获取勋章排行榜数据失败")


@router.get("/rankings/credits")
@require_telegram_auth
async def get_credits_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取积分排行榜数据"""
    logger.info(f"{user.username or user.first_name or user.id} 开始获取积分排行榜数据")

    try:
        credits_rankings = rankings_service.get_credits_rank(
            exclude_admins=True, current_user_id=user.id
        )
        logger.info(
            f"{user.username or user.first_name or user.id} 获取积分排行榜数据成功"
        )
        return {"credits_rank": credits_rankings}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取积分排行榜数据时发生未预期的错误: {e!s}")
        raise HTTPException(status_code=500, detail="获取积分排行榜数据失败")


@router.get("/rankings/donation")
@require_telegram_auth
async def get_donation_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取捐赠排行榜数据"""
    logger.info(f"{user.username or user.first_name or user.id} 开始获取捐赠排行榜数据")

    try:
        donation_rankings = rankings_service.get_donation_rank(
            exclude_admins=True, include_zero=False, current_user_id=user.id
        )
        logger.info(
            f"{user.username or user.first_name or user.id} 获取捐赠排行榜数据成功"
        )
        return {"donation_rank": donation_rankings}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取捐赠排行榜数据时发生未预期的错误: {e!s}")
        raise HTTPException(status_code=500, detail="获取捐赠排行榜数据失败")


@router.get("/rankings/watched-time/plex")
@require_telegram_auth
async def get_plex_watched_time_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取Plex观看时长排行榜数据"""
    logger.info(
        f"{user.username or user.first_name or user.id} 开始获取Plex观看时长排行榜数据"
    )

    try:
        watched_time_rank_plex = rankings_service.get_watch_time_rank(
            "plex", include_zero=False, with_avatar=True, current_user_id=user.id
        )
        logger.info(
            f"{user.username or user.first_name or user.id} 获取Plex观看时长排行榜数据成功"
        )
        return {"watched_time_rank_plex": watched_time_rank_plex}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取Plex观看时长排行榜数据时发生未预期的错误: {e!s}")
        raise HTTPException(status_code=500, detail="获取Plex观看时长排行榜数据失败")


@router.get("/rankings/watched-time/emby")
@require_telegram_auth
async def get_emby_watched_time_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取Emby观看时长排行榜数据"""
    logger.info(
        f"{user.username or user.first_name or user.id} 开始获取Emby观看时长排行榜数据"
    )

    try:
        watched_time_rank_emby = rankings_service.get_watch_time_rank(
            "emby", include_zero=False, with_avatar=True, current_user_id=user.id
        )
        logger.info(
            f"{user.username or user.first_name or user.id} 获取Emby观看时长排行榜数据成功"
        )
        return {"watched_time_rank_emby": watched_time_rank_emby}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取Emby观看时长排行榜数据时发生未预期的错误: {e!s}")
        raise HTTPException(status_code=500, detail="获取Emby观看时长排行榜数据失败")


@router.get("/rankings/invitation")
@require_telegram_auth
async def get_invitation_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取邀请排行榜数据"""
    logger.info(f"{user.username or user.first_name or user.id} 开始获取邀请排行榜数据")

    try:
        invitation_rankings = rankings_service.get_invitation_rank(
            exclude_admins=True, current_user_id=user.id
        )
        logger.info(
            f"{user.username or user.first_name or user.id} 获取邀请排行榜数据成功"
        )
        return {"invitation_rank": invitation_rankings}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取邀请排行榜数据时发生未预期的错误: {e!s}")
        raise HTTPException(status_code=500, detail="获取邀请排行榜数据失败")


@router.get("/rankings/game/wheel")
@require_telegram_auth
async def get_wheel_game_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取幸运大转盘游戏排行榜数据"""
    logger.info(
        f"{user.username or user.first_name or user.id} 开始获取幸运大转盘排行榜数据"
    )

    try:
        game_rankings = rankings_service.get_wheel_game_rankings(
            exclude_admins=True, current_user_id=user.id
        )
        logger.info(
            f"{user.username or user.first_name or user.id} 获取幸运大转盘排行榜数据成功"
        )
        return game_rankings
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取幸运大转盘排行榜数据时发生未预期的错误: {e!s}")
        raise HTTPException(status_code=500, detail="获取幸运大转盘排行榜数据失败")


@router.get("/rankings/game/treasure")
@require_telegram_auth
async def get_treasure_game_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取夺宝奇兵游戏排行榜数据"""
    logger.info(
        f"{user.username or user.first_name or user.id} 开始获取夺宝奇兵排行榜数据"
    )

    try:
        game_rankings = rankings_service.get_treasure_game_rankings(
            exclude_admins=True, current_user_id=user.id
        )
        logger.info(
            f"{user.username or user.first_name or user.id} 获取夺宝奇兵排行榜数据成功"
        )
        return game_rankings
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取夺宝奇兵排行榜数据时发生未预期的错误: {e!s}")
        raise HTTPException(status_code=500, detail="获取夺宝奇兵排行榜数据失败")


@router.get("/rankings/game/prediction")
@require_telegram_auth
async def get_prediction_game_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取大预言家游戏排行榜数据"""
    logger.info(
        f"{user.username or user.first_name or user.id} 开始获取大预言家排行榜数据"
    )

    try:
        prediction_net_profit_rank = []
        prediction_win_rate_rank = []

        logger.debug("正在查询大预言家净盈亏排行")
        net_profit_data = rankings_service.get_prediction_net_profit_rank()
        if net_profit_data:
            prediction_net_profit_rank = [
                {
                    "tg_id": info["tg_id"],
                    "name": _safe_name(info["tg_id"]),
                    "net_profit": float(info.get("net_profit") or 0),
                    "win_rate": float(info.get("win_rate") or 0),
                    "settled_markets": int(info.get("settled_markets") or 0),
                    "win_markets": int(info.get("win_markets") or 0),
                    "total_bet_amount": float(info.get("total_bet_amount") or 0),
                    "total_payout_amount": float(info.get("total_payout_amount") or 0),
                    "avatar": _safe_avatar(info["tg_id"]),
                    "is_self": info["tg_id"] == user.id,
                }
                for info in net_profit_data
                if info["tg_id"] not in settings.TG_ADMIN_CHAT_ID
            ]

        logger.debug("正在查询大预言家胜率排行")
        win_rate_data = rankings_service.get_prediction_win_rate_rank()
        if win_rate_data:
            prediction_win_rate_rank = [
                {
                    "tg_id": info["tg_id"],
                    "name": _safe_name(info["tg_id"]),
                    "win_rate": float(info.get("win_rate") or 0),
                    "net_profit": float(info.get("net_profit") or 0),
                    "settled_markets": int(info.get("settled_markets") or 0),
                    "win_markets": int(info.get("win_markets") or 0),
                    "total_bet_amount": float(info.get("total_bet_amount") or 0),
                    "total_payout_amount": float(info.get("total_payout_amount") or 0),
                    "avatar": _safe_avatar(info["tg_id"]),
                    "is_self": info["tg_id"] == user.id,
                }
                for info in win_rate_data
                if info["tg_id"] not in settings.TG_ADMIN_CHAT_ID
            ]

        logger.info(
            f"{user.username or user.first_name or user.id} 获取大预言家排行榜数据成功"
        )
        return {
            "prediction_net_profit_rank": prediction_net_profit_rank,
            "prediction_win_rate_rank": prediction_win_rate_rank,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取大预言家排行榜数据时发生未预期的错误: {e!s}")
        raise HTTPException(status_code=500, detail="获取大预言家排行榜数据失败")


@router.get("/rankings/game/blackjack")
@require_telegram_auth
async def get_blackjack_game_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取 21 点游戏排行榜数据

    提供决策准确率榜（主）、胜率榜与单手最大赢利榜。

    不提供净积分变动榜与连胜榜：两者都奖励运气与刷量而非技巧。在负期望的前提下
    累计净积分几乎必然为负，且其排名在现实手数下由随机波动主导；连胜长度则重度
    依赖累计手数。
    """
    logger.info(
        f"{user.username or user.first_name or user.id} 开始获取 21 点排行榜数据"
    )

    try:
        blackjack_accuracy_rank = []
        blackjack_win_rate_rank = []
        blackjack_max_win_rank = []

        logger.debug("正在查询 21 点决策准确率与胜率排行")
        skill_ranks = rankings_service.get_blackjack_skill_ranks()
        accuracy_data = skill_ranks.get("accuracy") or []
        win_rate_data = skill_ranks.get("win_rate") or []

        if accuracy_data:
            blackjack_accuracy_rank = [
                {
                    "tg_id": info["tg_id"],
                    "name": _safe_name(info["tg_id"]),
                    "accuracy": float(info["accuracy"]),
                    "win_rate": float(info["win_rate"]),
                    "hand_count": int(info["hand_count"]),
                    "decisions_total": int(info["decisions_total"]),
                    "avatar": _safe_avatar(info["tg_id"]),
                    "is_self": info["tg_id"] == user.id,
                }
                for info in accuracy_data
                if info["tg_id"] not in settings.TG_ADMIN_CHAT_ID
            ]

        if win_rate_data:
            blackjack_win_rate_rank = [
                {
                    "tg_id": info["tg_id"],
                    "name": _safe_name(info["tg_id"]),
                    "win_rate": float(info["win_rate"]),
                    "accuracy": float(info["accuracy"]),
                    "hand_count": int(info["hand_count"]),
                    "avatar": _safe_avatar(info["tg_id"]),
                    "is_self": info["tg_id"] == user.id,
                }
                for info in win_rate_data
                if info["tg_id"] not in settings.TG_ADMIN_CHAT_ID
            ]

        logger.debug("正在查询 21 点单手最大赢利排行")
        max_win_data = rankings_service.get_blackjack_max_win_rank()
        if max_win_data:
            blackjack_max_win_rank = [
                {
                    "tg_id": info[0],
                    "name": _safe_name(info[0]),
                    "max_win": float(info[1]),
                    "hand_count": int(info[2]),
                    "avatar": _safe_avatar(info[0]),
                    "is_self": info[0] == user.id,
                }
                for info in max_win_data
                if info[0] not in settings.TG_ADMIN_CHAT_ID
            ]

        logger.info(
            f"{user.username or user.first_name or user.id} 获取 21 点排行榜数据成功"
        )
        return {
            "blackjack_accuracy_rank": blackjack_accuracy_rank,
            "blackjack_win_rate_rank": blackjack_win_rate_rank,
            "blackjack_max_win_rank": blackjack_max_win_rank,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 21 点排行榜数据时发生未预期的错误: {e!s}")
        raise HTTPException(status_code=500, detail="获取 21 点排行榜数据失败")


@router.get("/rankings/traffic/plex")
@require_telegram_auth
async def get_plex_traffic_rankings(
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
    start_date: str = Query(None, description="开始日期，格式: YYYY-MM-DD"),
    end_date: str = Query(None, description="结束日期，格式: YYYY-MM-DD"),
):
    """获取 Plex 流量排行榜数据

    Args:
        start_date: 开始日期，格式: YYYY-MM-DD，默认为今日
        end_date: 结束日期，格式: YYYY-MM-DD，默认为今日
    """
    logger.info(
        f"{user.username or user.first_name or user.id} 开始获取 Plex 流量排行榜数据 (日期范围: {start_date} - {end_date})"
    )

    try:
        parsed_start_date = None
        parsed_end_date = None

        if start_date:
            try:
                parsed_start_date = datetime.strptime(
                    f"{start_date} +0000", "%Y-%m-%d %z"
                ).replace(tzinfo=settings.TZ)
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="开始日期格式错误，应为 YYYY-MM-DD"
                )

        if end_date:
            try:
                parsed_end_date = datetime.strptime(
                    f"{end_date} +0000", "%Y-%m-%d %z"
                ).replace(hour=23, minute=59, second=59, tzinfo=settings.TZ)
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="结束日期格式错误，应为 YYYY-MM-DD"
                )

        logger.debug(
            f"正在查询 Plex 流量排行 (日期范围: {parsed_start_date} - {parsed_end_date})"
        )
        traffic_rank_plex = rankings_service.get_traffic_rank(
            "plex", parsed_start_date, parsed_end_date, current_user_id=user.id
        )

        logger.info(
            f"{user.username or user.first_name or user.id} 获取 Plex 流量排行榜数据成功"
        )
        return {"traffic_rank_plex": traffic_rank_plex}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 Plex 流量排行榜数据时发生未预期的错误: {e!s}")
        raise HTTPException(status_code=500, detail="获取 Plex 流量排行榜数据失败")


@router.get("/rankings/traffic/emby")
@require_telegram_auth
async def get_emby_traffic_rankings(
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
    start_date: str = Query(None, description="开始日期，格式: YYYY-MM-DD"),
    end_date: str = Query(None, description="结束日期，格式: YYYY-MM-DD"),
):
    """获取 Emby 流量排行榜数据

    Args:
        start_date: 开始日期，格式: YYYY-MM-DD，默认为今日
        end_date: 结束日期，格式: YYYY-MM-DD，默认为今日
    """
    logger.info(
        f"{user.username or user.first_name or user.id} 开始获取 Emby 流量排行榜数据 (日期范围: {start_date} - {end_date})"
    )

    try:
        parsed_start_date = None
        parsed_end_date = None

        if start_date:
            try:
                parsed_start_date = datetime.strptime(
                    f"{start_date} +0000", "%Y-%m-%d %z"
                ).replace(tzinfo=settings.TZ)
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="开始日期格式错误，应为 YYYY-MM-DD"
                )

        if end_date:
            try:
                parsed_end_date = datetime.strptime(
                    f"{end_date} +0000", "%Y-%m-%d %z"
                ).replace(hour=23, minute=59, second=59, tzinfo=settings.TZ)
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="结束日期格式错误，应为 YYYY-MM-DD"
                )

        logger.debug(
            f"正在查询 Emby 流量排行 (日期范围: {parsed_start_date} - {parsed_end_date})"
        )
        traffic_rank_emby = rankings_service.get_traffic_rank(
            "emby", parsed_start_date, parsed_end_date, current_user_id=user.id
        )

        logger.info(
            f"{user.username or user.first_name or user.id} 获取 Emby 流量排行榜数据成功"
        )
        return {"traffic_rank_emby": traffic_rank_emby}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 Emby 流量排行榜数据时发生未预期的错误: {e!s}")
        raise HTTPException(status_code=500, detail="获取 Emby 流量排行榜数据失败")
