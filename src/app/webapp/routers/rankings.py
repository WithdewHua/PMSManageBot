from datetime import datetime

from app.config import settings
from app.databases import db
from app.log import uvicorn_logger as logger
from app.modules.emby import Emby
from app.modules.plex import Plex
from app.utils.utils import get_user_avatar_from_tg_id, get_user_name_from_tg_id
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.schemas import TelegramUser
from fastapi import APIRouter, Depends, HTTPException, Query, Request

router = APIRouter(prefix="/api", tags=["rankings"])


@router.get("/rankings/badge")
@require_telegram_auth
async def get_badge_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取勋章排行榜数据"""
    logger.info(f"{user.username or user.first_name or user.id} 开始获取勋章排行榜数据")

    try:
        badge_rankings = []
        try:
            logger.debug("正在查询勋章排行")
            badge_data = db.get_badge_rank()
            if badge_data:
                badge_rankings = [
                    {
                        "tg_id": info["tg_id"],
                        "name": get_user_name_from_tg_id(info["tg_id"]),
                        "badge_count": info["badge_count"],
                        "badges": info["badges"],
                        "avatar": get_user_avatar_from_tg_id(info["tg_id"]),
                        "is_self": info["tg_id"] == user.id,
                    }
                    for info in badge_data
                    if info["tg_id"] not in settings.TG_ADMIN_CHAT_ID
                ]
        except Exception as e:
            logger.error(f"获取勋章排行失败: {str(e)}")

        logger.info(
            f"{user.username or user.first_name or user.id} 获取勋章排行榜数据成功"
        )
        return {"badge_rank": badge_rankings}
    except Exception as e:
        logger.error(f"获取勋章排行榜数据时发生未预期的错误: {str(e)}")
        raise HTTPException(status_code=500, detail="获取勋章排行榜数据失败")


@router.get("/rankings/credits")
@require_telegram_auth
async def get_credits_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取积分排行榜数据"""
    logger.info(f"{user.username or user.first_name or user.id} 开始获取积分排行榜数据")

    try:
        credits_rankings = []
        try:
            logger.debug("正在查询积分排行")
            credits_data = db.get_credits_rank()
            if credits_data:
                credits_rankings = [
                    {
                        "tg_id": info[0],  # 添加 tg_id 字段用于加载勋章
                        "name": get_user_name_from_tg_id(info[0]),
                        "credits": info[1],
                        "avatar": get_user_avatar_from_tg_id(info[0]),
                        "is_self": info[0] == user.id,  # tg_id 比较
                    }
                    for info in credits_data
                    if info[0] not in settings.TG_ADMIN_CHAT_ID
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


@router.get("/rankings/donation")
@require_telegram_auth
async def get_donation_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取捐赠排行榜数据"""
    logger.info(f"{user.username or user.first_name or user.id} 开始获取捐赠排行榜数据")

    try:
        donation_rankings = []
        try:
            logger.debug("正在查询捐赠排行")
            donation_data = db.get_donation_rank()
            if donation_data:
                donation_rankings = [
                    {
                        "tg_id": info[0],  # 添加 tg_id 字段用于加载勋章
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


@router.get("/rankings/invitation")
@require_telegram_auth
async def get_invitation_rankings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取邀请排行榜数据"""
    logger.info(f"{user.username or user.first_name or user.id} 开始获取邀请排行榜数据")

    try:
        invitation_rankings = []
        try:
            logger.debug("正在查询邀请排行")
            invitation_data = db.get_invitation_rank()
            if invitation_data:
                invitation_rankings = [
                    {
                        "name": get_user_name_from_tg_id(info[0]),
                        "invite_count": info[1],
                        "avatar": get_user_avatar_from_tg_id(info[0]),
                        "is_self": info[0] == user.id,  # tg_id 比较
                    }
                    for info in invitation_data
                    if info[0] not in settings.TG_ADMIN_CHAT_ID and info[1] > 0
                ]
        except Exception as e:
            logger.error(f"获取邀请排行失败: {str(e)}")

        logger.info(
            f"{user.username or user.first_name or user.id} 获取邀请排行榜数据成功"
        )
        return {"invitation_rank": invitation_rankings}
    except Exception as e:
        logger.error(f"获取邀请排行榜数据时发生未预期的错误: {str(e)}")
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
        wheel_credits_rank = []
        wheel_invite_code_rank = []

        try:
            logger.debug("正在查询幸运大转盘积分赚取排行")
            wheel_credits_data = db.get_wheel_credits_rank()
            if wheel_credits_data:
                wheel_credits_rank = [
                    {
                        "tg_id": info[0],
                        "name": get_user_name_from_tg_id(info[0]),
                        "earned_credits": float(info[1]),
                        "play_count": int(info[2]),
                        "avatar": get_user_avatar_from_tg_id(info[0]),
                        "is_self": info[0] == user.id,
                    }
                    for info in wheel_credits_data
                    if info[0] not in settings.TG_ADMIN_CHAT_ID
                ]
        except Exception as e:
            logger.error(f"获取幸运大转盘积分赚取排行失败: {str(e)}")

        try:
            logger.debug("正在查询幸运大转盘邀请码获得排行")
            wheel_invite_code_data = db.get_wheel_invite_code_rank()
            if wheel_invite_code_data:
                wheel_invite_code_rank = [
                    {
                        "tg_id": info[0],
                        "name": get_user_name_from_tg_id(info[0]),
                        "invite_code_count": int(info[1]),
                        "avatar": get_user_avatar_from_tg_id(info[0]),
                        "is_self": info[0] == user.id,
                    }
                    for info in wheel_invite_code_data
                    if info[0] not in settings.TG_ADMIN_CHAT_ID
                ]
        except Exception as e:
            logger.error(f"获取幸运大转盘邀请码获得排行失败: {str(e)}")

        logger.info(
            f"{user.username or user.first_name or user.id} 获取幸运大转盘排行榜数据成功"
        )
        return {
            "wheel_credits_rank": wheel_credits_rank,
            "wheel_invite_code_rank": wheel_invite_code_rank,
        }
    except Exception as e:
        logger.error(f"获取幸运大转盘排行榜数据时发生未预期的错误: {str(e)}")
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
        treasure_win_issue_rank = []
        treasure_win_credits_rank = []

        try:
            logger.debug("正在查询夺宝奇兵中奖期数排行")
            treasure_win_issue_data = db.get_treasure_win_issue_rank()
            if treasure_win_issue_data:
                treasure_win_issue_rank = [
                    {
                        "tg_id": info[0],
                        "name": get_user_name_from_tg_id(info[0]),
                        "win_issue_count": int(info[1]),
                        "avatar": get_user_avatar_from_tg_id(info[0]),
                        "is_self": info[0] == user.id,
                    }
                    for info in treasure_win_issue_data
                    if info[0] not in settings.TG_ADMIN_CHAT_ID
                ]
        except Exception as e:
            logger.error(f"获取夺宝奇兵中奖期数排行失败: {str(e)}")

        try:
            logger.debug("正在查询夺宝奇兵中奖积分排行")
            treasure_win_credits_data = db.get_treasure_win_credits_rank()
            if treasure_win_credits_data:
                treasure_win_credits_rank = [
                    {
                        "tg_id": info[0],
                        "name": get_user_name_from_tg_id(info[0]),
                        "win_credits": int(info[1]),
                        "avatar": get_user_avatar_from_tg_id(info[0]),
                        "is_self": info[0] == user.id,
                    }
                    for info in treasure_win_credits_data
                    if info[0] not in settings.TG_ADMIN_CHAT_ID
                ]
        except Exception as e:
            logger.error(f"获取夺宝奇兵中奖积分排行失败: {str(e)}")

        logger.info(
            f"{user.username or user.first_name or user.id} 获取夺宝奇兵排行榜数据成功"
        )
        return {
            "treasure_win_issue_rank": treasure_win_issue_rank,
            "treasure_win_credits_rank": treasure_win_credits_rank,
        }
    except Exception as e:
        logger.error(f"获取夺宝奇兵排行榜数据时发生未预期的错误: {str(e)}")
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

        try:
            logger.debug("正在查询大预言家净盈亏排行")
            net_profit_data = db.get_prediction_net_profit_rank()
            if net_profit_data:
                prediction_net_profit_rank = [
                    {
                        "tg_id": info["tg_id"],
                        "name": get_user_name_from_tg_id(info["tg_id"]),
                        "net_profit": float(info.get("net_profit") or 0),
                        "win_rate": float(info.get("win_rate") or 0),
                        "settled_markets": int(info.get("settled_markets") or 0),
                        "win_markets": int(info.get("win_markets") or 0),
                        "total_bet_amount": float(info.get("total_bet_amount") or 0),
                        "total_payout_amount": float(
                            info.get("total_payout_amount") or 0
                        ),
                        "avatar": get_user_avatar_from_tg_id(info["tg_id"]),
                        "is_self": info["tg_id"] == user.id,
                    }
                    for info in net_profit_data
                    if info["tg_id"] not in settings.TG_ADMIN_CHAT_ID
                ]
        except Exception as e:
            logger.error(f"获取大预言家净盈亏排行失败: {str(e)}")

        try:
            logger.debug("正在查询大预言家胜率排行")
            win_rate_data = db.get_prediction_win_rate_rank()
            if win_rate_data:
                prediction_win_rate_rank = [
                    {
                        "tg_id": info["tg_id"],
                        "name": get_user_name_from_tg_id(info["tg_id"]),
                        "win_rate": float(info.get("win_rate") or 0),
                        "net_profit": float(info.get("net_profit") or 0),
                        "settled_markets": int(info.get("settled_markets") or 0),
                        "win_markets": int(info.get("win_markets") or 0),
                        "total_bet_amount": float(info.get("total_bet_amount") or 0),
                        "total_payout_amount": float(
                            info.get("total_payout_amount") or 0
                        ),
                        "avatar": get_user_avatar_from_tg_id(info["tg_id"]),
                        "is_self": info["tg_id"] == user.id,
                    }
                    for info in win_rate_data
                    if info["tg_id"] not in settings.TG_ADMIN_CHAT_ID
                ]
        except Exception as e:
            logger.error(f"获取大预言家胜率排行失败: {str(e)}")

        logger.info(
            f"{user.username or user.first_name or user.id} 获取大预言家排行榜数据成功"
        )
        return {
            "prediction_net_profit_rank": prediction_net_profit_rank,
            "prediction_win_rate_rank": prediction_win_rate_rank,
        }
    except Exception as e:
        logger.error(f"获取大预言家排行榜数据时发生未预期的错误: {str(e)}")
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

        # 准确率榜与胜率榜共用同一份聚合，一次扫描算出两个榜
        try:
            logger.debug("正在查询 21 点决策准确率与胜率排行")
            skill_ranks = db.get_blackjack_skill_ranks()
            accuracy_data = skill_ranks.get("accuracy") or []
            win_rate_data = skill_ranks.get("win_rate") or []
        except Exception as e:
            logger.error(f"获取 21 点技巧类排行失败: {str(e)}")
            accuracy_data, win_rate_data = [], []

        try:
            if accuracy_data:
                blackjack_accuracy_rank = [
                    {
                        "tg_id": info["tg_id"],
                        "name": get_user_name_from_tg_id(info["tg_id"]),
                        "accuracy": float(info["accuracy"]),
                        "win_rate": float(info["win_rate"]),
                        "hand_count": int(info["hand_count"]),
                        "decisions_total": int(info["decisions_total"]),
                        "avatar": get_user_avatar_from_tg_id(info["tg_id"]),
                        "is_self": info["tg_id"] == user.id,
                    }
                    for info in accuracy_data
                    if info["tg_id"] not in settings.TG_ADMIN_CHAT_ID
                ]
        except Exception as e:
            logger.error(f"渲染 21 点决策准确率排行失败: {str(e)}")

        try:
            if win_rate_data:
                blackjack_win_rate_rank = [
                    {
                        "tg_id": info["tg_id"],
                        "name": get_user_name_from_tg_id(info["tg_id"]),
                        "win_rate": float(info["win_rate"]),
                        "accuracy": float(info["accuracy"]),
                        "hand_count": int(info["hand_count"]),
                        "avatar": get_user_avatar_from_tg_id(info["tg_id"]),
                        "is_self": info["tg_id"] == user.id,
                    }
                    for info in win_rate_data
                    if info["tg_id"] not in settings.TG_ADMIN_CHAT_ID
                ]
        except Exception as e:
            logger.error(f"渲染 21 点胜率排行失败: {str(e)}")

        try:
            logger.debug("正在查询 21 点单手最大赢利排行")
            max_win_data = db.get_blackjack_max_win_rank()
            if max_win_data:
                blackjack_max_win_rank = [
                    {
                        "tg_id": info[0],
                        "name": get_user_name_from_tg_id(info[0]),
                        "max_win": float(info[1]),
                        "hand_count": int(info[2]),
                        "avatar": get_user_avatar_from_tg_id(info[0]),
                        "is_self": info[0] == user.id,
                    }
                    for info in max_win_data
                    if info[0] not in settings.TG_ADMIN_CHAT_ID
                ]
        except Exception as e:
            logger.error(f"获取 21 点单手最大赢利排行失败: {str(e)}")

        logger.info(
            f"{user.username or user.first_name or user.id} 获取 21 点排行榜数据成功"
        )
        return {
            "blackjack_accuracy_rank": blackjack_accuracy_rank,
            "blackjack_win_rate_rank": blackjack_win_rate_rank,
            "blackjack_max_win_rank": blackjack_max_win_rank,
        }
    except Exception as e:
        logger.error(f"获取 21 点排行榜数据时发生未预期的错误: {str(e)}")
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
        # 解析日期参数
        parsed_start_date = None
        parsed_end_date = None

        if start_date:
            try:
                parsed_start_date = datetime.strptime(start_date, "%Y-%m-%d")
                parsed_start_date = parsed_start_date.replace(tzinfo=settings.TZ)
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="开始日期格式错误，应为 YYYY-MM-DD"
                )

        if end_date:
            try:
                parsed_end_date = datetime.strptime(end_date, "%Y-%m-%d")
                parsed_end_date = parsed_end_date.replace(
                    hour=23, minute=59, second=59, tzinfo=settings.TZ
                )
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="结束日期格式错误，应为 YYYY-MM-DD"
                )

        traffic_rank_plex = []
        try:
            logger.debug(
                f"正在查询 Plex 流量排行 (日期范围: {parsed_start_date} - {parsed_end_date})"
            )
            plex_traffic_data = db.get_plex_traffic_rank(
                parsed_start_date, parsed_end_date
            )
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
        # 解析日期参数
        parsed_start_date = None
        parsed_end_date = None

        if start_date:
            try:
                parsed_start_date = datetime.strptime(start_date, "%Y-%m-%d")
                parsed_start_date = parsed_start_date.replace(tzinfo=settings.TZ)
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="开始日期格式错误，应为 YYYY-MM-DD"
                )

        if end_date:
            try:
                parsed_end_date = datetime.strptime(end_date, "%Y-%m-%d")
                parsed_end_date = parsed_end_date.replace(
                    hour=23, minute=59, second=59, tzinfo=settings.TZ
                )
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="结束日期格式错误，应为 YYYY-MM-DD"
                )

        traffic_rank_emby = []
        emby = Emby()
        try:
            logger.debug(
                f"正在查询 Emby 流量排行 (日期范围: {parsed_start_date} - {parsed_end_date})"
            )
            emby_traffic_data = db.get_emby_traffic_rank(
                parsed_start_date, parsed_end_date
            )
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
