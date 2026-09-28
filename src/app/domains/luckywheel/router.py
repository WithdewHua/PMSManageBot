import time

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
from app.domains.badge_awards.jobs import check_and_award_game_king_badge
from app.domains.luckywheel import constants as luckywheel_constants
from app.domains.luckywheel import exceptions as luckywheel_exceptions
from app.domains.luckywheel import notifications as luckywheel_notifications
from app.domains.luckywheel import service as luckywheel_service
from app.domains.luckywheel.schemas import (
    LuckyWheelConfig,
    LuckyWheelConfigUpdateRequest,
    LuckyWheelFreespinSummaryResponse,
    LuckyWheelItem,  # noqa: F401 - legacy import path used by activity callers
    LuckyWheelSpinResult,
    LuckyWheelTenSpinResult,
)

DEFAULT_WHEEL_CONFIG = luckywheel_service.DEFAULT_WHEEL_CONFIG
FREE_SPIN_SOURCE_TO_WHEEL_SOURCE = luckywheel_constants.FREE_SPIN_SOURCE_TO_WHEEL_SOURCE
WHEEL_SOURCE_TO_FREE_SPIN_SOURCE = luckywheel_constants.WHEEL_SOURCE_TO_FREE_SPIN_SOURCE
RandomnessConfig = luckywheel_service.RandomnessConfig
wheel_source_for_free_spin = luckywheel_constants.wheel_source_for_free_spin
get_wheel_config = luckywheel_service.get_wheel_config
save_wheel_config = luckywheel_service.save_wheel_config
get_randomness_config_from_redis = luckywheel_service.get_randomness_config
save_randomness_config = luckywheel_service.save_randomness_config
random_select_winner = luckywheel_service.random_select_winner
get_randomness_stats = luckywheel_service.get_randomness_stats

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


@router.get("/config", response_model=LuckyWheelConfig)
async def get_config():
    """获取转盘配置"""
    try:
        return luckywheel_service.get_wheel_config()
    except luckywheel_exceptions.LuckywheelError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        ) from error
    except Exception as error:
        logger.error(f"获取转盘配置失败: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取配置失败"
        ) from error


@router.put("/config")
@require_telegram_auth
async def update_config(
    request: Request,
    config_update_request: LuckyWheelConfigUpdateRequest,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """更新转盘配置（仅管理员）"""
    try:
        check_admin_permission(current_user)
        luckywheel_service.update_wheel_config(config_update_request)
        return JSONResponse(
            status_code=status.HTTP_200_OK, content={"message": "转盘配置更新成功"}
        )
    except HTTPException:
        raise
    except luckywheel_exceptions.LuckywheelError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        ) from error
    except Exception as error:
        logger.error(f"更新转盘配置失败: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新配置失败"
        ) from error


@router.get("/free-spins", response_model=LuckyWheelFreespinSummaryResponse)
@require_telegram_auth
async def get_free_spins(
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """免费机会账本概览：可用次数、到期时间、已注册来源的进度。"""
    summary = luckywheel_service.free_spin_summary(int(current_user.id))
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
        spin_result = await luckywheel_service.spin(
            user_id, config=luckywheel_service.get_wheel_config()
        )
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
            user_id, config=luckywheel_service.get_wheel_config()
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
        return luckywheel_service.get_user_status(int(current_user.id))
    except luckywheel_exceptions.LuckywheelError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        ) from error
    except Exception as error:
        logger.error(f"获取用户转盘状态失败: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取用户状态失败"
        ) from error


@router.get("/randomness-stats")
@require_telegram_auth
async def get_randomness_statistics(
    request: Request,
    iterations: int = 10000,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """获取随机性统计信息（仅管理员）"""
    try:
        check_admin_permission(current_user)
        config = luckywheel_service.get_wheel_config()
        randomness_config = luckywheel_service.get_randomness_config()
        stats = luckywheel_service.get_randomness_stats(config.items, iterations)
        deviations = [stat["deviation"] for stat in stats.values()]
        average_deviation = (
            round(sum(deviations) / len(deviations), 2) if deviations else 0
        )
        overall_fairness = all(stat["is_fair"] for stat in stats.values())
        return {
            "iterations": iterations,
            "total_items": len(config.items),
            "valid_items": len([item for item in config.items if item.probability > 0]),
            "average_deviation": average_deviation,
            "overall_fairness": overall_fairness,
            "stats": stats,
            "config": randomness_config,
            "timestamp": str(int(time.time() * 1000)),
        }
    except HTTPException:
        raise
    except luckywheel_exceptions.LuckywheelError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        ) from error
    except Exception as error:
        logger.error(f"获取随机性统计失败: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取统计信息失败"
        ) from error


@router.put("/randomness-config")
@require_telegram_auth
async def update_randomness_config(
    request: Request,
    config_data: dict,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """更新随机性配置（仅管理员）"""
    try:
        check_admin_permission(current_user)
        luckywheel_service.update_randomness_config(config_data)
        logger.info(
            f"管理员 {get_user_name_from_tg_id(current_user.id)} 更新了随机性配置: {config_data}"
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK, content={"message": "随机性配置更新成功"}
        )
    except HTTPException:
        raise
    except luckywheel_exceptions.LuckywheelError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        ) from error
    except Exception as error:
        logger.error(f"更新随机性配置失败: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新配置失败"
        ) from error


@router.get("/randomness-config")
@require_telegram_auth
async def get_randomness_config(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取当前随机性配置（仅管理员）"""
    try:
        check_admin_permission(current_user)
        return luckywheel_service.get_randomness_config()
    except HTTPException:
        raise
    except luckywheel_exceptions.LuckywheelError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        ) from error
    except Exception as error:
        logger.error(f"获取随机性配置失败: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取配置失败"
        ) from error


@router.get("/stats")
@require_telegram_auth
async def get_wheel_statistics(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取转盘统计数据（仅管理员）"""
    try:
        check_admin_permission(current_user)
        return luckywheel_service.get_wheel_stats()
    except HTTPException:
        raise
    except luckywheel_exceptions.LuckywheelError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        ) from error
    except Exception as error:
        logger.error(f"获取转盘统计失败: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取统计数据失败"
        ) from error


@router.get("/user-activity-stats")
@require_telegram_auth
async def get_user_activity_stats(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取用户个人活动统计数据"""
    try:
        stats = luckywheel_service.get_user_wheel_stats(int(current_user.id))
        return {"success": True, "data": stats}
    except luckywheel_exceptions.LuckywheelError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        ) from error
    except Exception as error:
        logger.error(f"获取用户活动统计失败: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取用户活动统计失败",
        ) from error
