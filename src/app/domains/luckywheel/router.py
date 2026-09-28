import json
import re
import time
import traceback

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.core.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.core.log import logger
from app.core.schemas import TelegramUser
from app.core.telegram import get_user_name_from_tg_id, send_message_by_url
from app.databases import db
from app.domains.badge_awards.jobs import check_and_award_game_king_badge
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.luckywheel import config as luckywheel_config
from app.domains.luckywheel import constants as luckywheel_constants
from app.domains.luckywheel import exceptions as luckywheel_exceptions
from app.domains.luckywheel import notifications as luckywheel_notifications
from app.domains.luckywheel import rules as luckywheel_rules
from app.domains.luckywheel import service as luckywheel_service
from app.domains.luckywheel.schemas import (
    LuckyWheelConfig,
    LuckyWheelConfigUpdateRequest,
    LuckyWheelFreespinSummaryResponse,
    LuckyWheelItem,
    LuckyWheelSpinResult,
    LuckyWheelTenSpinResult,
)
from app.domains.premium.service import update_premium_status

DEFAULT_WHEEL_CONFIG = luckywheel_config.DEFAULT_WHEEL_CONFIG
FREE_SPIN_SOURCE_TO_WHEEL_SOURCE = luckywheel_constants.FREE_SPIN_SOURCE_TO_WHEEL_SOURCE
WHEEL_SOURCE_TO_FREE_SPIN_SOURCE = luckywheel_constants.WHEEL_SOURCE_TO_FREE_SPIN_SOURCE
RandomnessConfig = luckywheel_rules.RandomnessConfig
wheel_source_for_free_spin = luckywheel_constants.wheel_source_for_free_spin
get_wheel_config = luckywheel_config.get_wheel_config
save_wheel_config = luckywheel_config.save_wheel_config

router = APIRouter(prefix="/luckywheel", tags=["幸运大转盘"])


async def execute_single_spin(
    config: LuckyWheelConfig,
    user_id: int,
    current_credits: float,
    *,
    cost_credits: float | None = None,
    source: str = "paid",
) -> tuple[LuckyWheelSpinResult, float, bool]:
    """Legacy compatibility entry point for already-claimed free spins."""
    previous = luckywheel_notifications.send_message_by_url
    luckywheel_notifications.send_message_by_url = send_message_by_url
    try:
        return await luckywheel_service.execute_single_spin(
            config,
            user_id,
            current_credits,
            cost_credits=cost_credits,
            source=source,
        )
    finally:
        luckywheel_notifications.send_message_by_url = previous


def _handle_premium_reward(tg_id: int, name: str) -> float:
    """Legacy compatibility helper; new spins grant Premium in the repository."""
    days_match = re.search(r"(\d+)", name)
    if not days_match:
        return 0.0
    days = int(days_match.group(1))
    for service_name in ("plex", "emby"):
        try:
            update_premium_status(int(tg_id), service_name, days)
        except NameError:
            continue
        except Exception as error:
            logger.error(f"更新 Premium 状态失败: {error}")
    return 0.0


@router.get("/config", response_model=LuckyWheelConfig)
async def get_config():
    """获取转盘配置"""
    try:
        config = get_wheel_config()
        return config
    except Exception as e:
        logger.error(f"获取转盘配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取配置失败"
        )


@router.put("/config")
@require_telegram_auth
async def update_config(
    request: Request,
    config_update_request: LuckyWheelConfigUpdateRequest,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """更新转盘配置（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        # 验证概率总和
        total_probability = sum(
            item.probability for item in config_update_request.items
        )
        if abs(total_probability - 100.0) > 0.01:  # 允许小的浮点数误差
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"奖品概率总和必须为 100%，当前为 {total_probability}%",
            )

        # 获取当前配置
        current_config = get_wheel_config()

        # 更新配置
        new_config = LuckyWheelConfig(
            items=config_update_request.items,
            cost_credits=config_update_request.cost_credits
            or current_config.cost_credits,
            min_credits_required=config_update_request.min_credits_required
            or current_config.min_credits_required,
            gen_privileged_code=config_update_request.gen_privileged_code,
        )

        # 保存配置
        if save_wheel_config(new_config) is False:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="保存配置失败",
            )

        return JSONResponse(
            status_code=status.HTTP_200_OK, content={"message": "转盘配置更新成功"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新转盘配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新配置失败"
        )


@router.get("/free-spins", response_model=LuckyWheelFreespinSummaryResponse)
@require_telegram_auth
async def get_free_spins(
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """21 点打满手数获得的免费机会概览：可用次数、到期时间、手数进度。"""
    summary = luckywheel_service.get_blackjack_freespin_summary(int(current_user.id))
    return LuckyWheelFreespinSummaryResponse(
        enabled=bool(summary.get("enabled")),
        available=int(summary.get("available") or 0),
        expires_at_ms_list=[int(ms) for ms in summary.get("expires_at_ms_list") or []],
        hands_since_freespin=int(summary.get("hands_since_freespin") or 0),
        hand_threshold=int(summary.get("hand_threshold") or 0),
    )


@router.post("/spin", response_model=LuckyWheelSpinResult)
@require_telegram_auth
async def spin_wheel(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """转动转盘。数据库工作与奖励发放由 luckywheel service 原子完成。"""
    try:
        user_id = int(current_user.id)
        spin_result = await luckywheel_service.spin(user_id, config=get_wheel_config())
        logger.info(
            f"用户 {get_user_name_from_tg_id(user_id)} 转盘结果: "
            f"{spin_result.item.name}, 积分变化: {spin_result.credits_change}, "
            f"最终积分: {spin_result.current_credits}"
        )
        background_tasks.add_task(check_and_award_game_king_badge, user_id=user_id)
        return spin_result
    except HTTPException:
        raise
    except luckywheel_exceptions.LuckywheelError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        ) from error
    except Exception as error:
        logger.error(f"转盘操作失败: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="转盘操作失败"
        )


@router.post("/spin-ten", response_model=LuckyWheelTenSpinResult)
@require_telegram_auth
async def spin_wheel_ten_times(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """转盘十连抽；十次抽奖共享一个数据库事务。"""
    try:
        user_id = int(current_user.id)
        result = await luckywheel_service.spin_ten_times(
            user_id, config=get_wheel_config()
        )
        logger.info(
            f"用户 {get_user_name_from_tg_id(user_id)} 十连抽完成, "
            f"总积分变化: {result.total_credits_change}, "
            f"最终积分: {result.current_credits}"
        )
        background_tasks.add_task(check_and_award_game_king_badge, user_id=user_id)
        return result
    except HTTPException:
        raise
    except luckywheel_exceptions.LuckywheelError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        ) from error
    except Exception as error:
        logger.error(f"转盘十连抽操作失败: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="转盘十连抽操作失败",
        )


@router.get("/user-status")
@require_telegram_auth
async def get_user_status(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取用户转盘参与状态"""
    try:
        user_id = current_user.id

        # 获取转盘配置
        config = get_wheel_config()

        # 获取用户当前积分
        current_credits = credits_service.read_optional(CreditAccount.tg(int(user_id)))
        if current_credits is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"未找到用户 {user_id}"
            )

        can_participate = current_credits >= config.min_credits_required

        return {
            "can_participate": can_participate,
            "current_credits": current_credits,
            "min_credits_required": config.min_credits_required,
            "cost_credits": config.cost_credits,
        }

    except Exception as e:
        logger.error(f"获取用户转盘状态失败: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取用户状态失败"
        )


def get_randomness_config_from_redis() -> dict:
    """从数据库获取随机性配置"""
    try:
        config_str = db.get_lucky_wheel_config("randomness_config")
        if config_str:
            config_dict = json.loads(config_str)
            # 更新类配置
            RandomnessConfig.from_dict(config_dict)
            return config_dict
        else:
            # 如果没有配置，使用默认配置并保存到数据库
            default_config = RandomnessConfig.to_dict()
            save_randomness_config(default_config)
            return default_config
    except Exception as e:
        logger.error(f"获取随机性配置失败: {e}")
        return RandomnessConfig.to_dict()


def save_randomness_config(config_dict: dict):
    """保存随机性配置到数据库"""
    try:
        # 验证配置参数的合理性
        if "protection_threshold" in config_dict:
            threshold = float(config_dict["protection_threshold"])
            if not (0 < threshold <= 50):
                raise ValueError("保护阈值必须在0-50之间")

        if "protection_factor" in config_dict:
            factor = float(config_dict["protection_factor"])
            if not (1.0 <= factor <= 3.0):
                raise ValueError("保护系数必须在1.0-3.0之间")

        # 更新类配置
        RandomnessConfig.from_dict(config_dict)

        # 保存到数据库
        config_json = json.dumps(config_dict)
        success = db.set_lucky_wheel_config("randomness_config", config_json)
        if success:
            logger.info("随机性配置已保存到数据库")
        else:
            raise RuntimeError("保存随机性配置失败")
    except Exception as e:
        logger.error(f"保存随机性配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="保存随机性配置失败",
        )


def random_select_winner(
    items: list[LuckyWheelItem], user_id: int | None = None
) -> LuckyWheelItem:
    """Compatibility wrapper for the pure rules picker used by admin statistics."""
    get_randomness_config_from_redis()
    return luckywheel_rules.pick_prize(items, user_id=user_id)


def get_randomness_stats(items: list[LuckyWheelItem], iterations: int = 10000) -> dict:
    """
    获取随机性统计信息，用于测试和验证随机算法的公平性

    Args:
        items: 奖品列表
        iterations: 测试迭代次数

    Returns:
        包含统计信息的字典
    """
    if not items or iterations <= 0:
        return {}

    # 统计每个奖品的中奖次数
    win_counts = {item.name: 0 for item in items}

    for _ in range(iterations):
        try:
            winner = random_select_winner(items)
            win_counts[winner.name] += 1
        except Exception as e:
            logger.warning(f"转盘随机性模拟单次抽取失败: {e}")
            continue

    # 计算实际中奖率和期望中奖率
    total_probability = sum(item.probability for item in items if item.probability > 0)
    stats = {}

    for item in items:
        if item.probability > 0:
            actual_rate = (win_counts[item.name] / iterations) * 100
            expected_rate = (item.probability / total_probability) * 100
            deviation = abs(actual_rate - expected_rate)

            stats[item.name] = {
                "expected_rate": round(expected_rate, 2),
                "actual_rate": round(actual_rate, 2),
                "deviation": round(deviation, 2),
                "win_count": win_counts[item.name],
                "is_fair": deviation < 1.0,  # 偏差小于1%认为是公平的
            }

    return stats


@router.get("/randomness-stats")
@require_telegram_auth
async def get_randomness_statistics(
    request: Request,
    iterations: int = 10000,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """获取随机性统计信息（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        # 获取当前配置
        config = get_wheel_config()

        # 从Redis获取随机性配置
        randomness_config = get_randomness_config_from_redis()

        # 生成统计信息
        stats = get_randomness_stats(config.items, iterations)

        # 计算平均偏差
        deviations = [stat["deviation"] for stat in stats.values()]
        average_deviation = (
            round(sum(deviations) / len(deviations), 2) if deviations else 0
        )

        # 判断整体公平性
        overall_fairness = all(stat["is_fair"] for stat in stats.values())

        return {
            "iterations": iterations,
            "total_items": len(config.items),
            "valid_items": len([item for item in config.items if item.probability > 0]),
            "average_deviation": average_deviation,
            "overall_fairness": overall_fairness,
            "stats": stats,
            "config": randomness_config,
            "timestamp": str(int(time.time() * 1000)),  # 添加时间戳
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取随机性统计失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取统计信息失败"
        )


@router.put("/randomness-config")
@require_telegram_auth
async def update_randomness_config(
    request: Request,
    config_data: dict,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """更新随机性配置（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        # 获取当前配置
        current_config = get_randomness_config_from_redis()

        # 更新配置，保留未指定的字段
        updated_config = current_config.copy()
        updated_config.update(config_data)

        # 保存配置到Redis（包含验证）
        save_randomness_config(updated_config)

        logger.info(
            f"管理员 {get_user_name_from_tg_id(current_user.id)} 更新了随机性配置: {config_data}"
        )

        return JSONResponse(
            status_code=status.HTTP_200_OK, content={"message": "随机性配置更新成功"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新随机性配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新配置失败"
        )


@router.get("/randomness-config")
@require_telegram_auth
async def get_randomness_config(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取当前随机性配置（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        # 从Redis获取配置
        config = get_randomness_config_from_redis()

        return config

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取随机性配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取配置失败"
        )


@router.get("/stats")
@require_telegram_auth
async def get_wheel_statistics(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取转盘统计数据（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        stats = db.get_wheel_stats()

        return stats

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取转盘统计失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取统计数据失败"
        )


@router.get("/user-activity-stats")
@require_telegram_auth
async def get_user_activity_stats(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取用户个人活动统计数据"""
    try:
        user_id = current_user.id

        # 获取用户转盘统计数据
        stats = db.get_user_wheel_stats(user_id)

        return {"success": True, "data": stats}

    except Exception as e:
        logger.error(f"获取用户活动统计失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取用户活动统计失败",
        )
