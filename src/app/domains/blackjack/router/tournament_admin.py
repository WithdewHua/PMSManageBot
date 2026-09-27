"""Admin endpoints for blackjack tournaments, included after player endpoints."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.core.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.core.log import uvicorn_logger as logger
from app.core.schemas import TelegramUser
from app.domains.blackjack import service as blackjack_service
from app.domains.blackjack.notifications.tournament import (
    _broadcast_group,
    _format_cancelled,
    _format_created,
    _send_many,
)
from app.domains.blackjack.router.tournament import _raise_for_value_error
from app.domains.blackjack.schemas import (
    TournamentAdminResponse,
    TournamentConsistencyResponse,
    TournamentCreateRequest,
    TournamentResponse,
    TournamentUpdateRequest,
)

router = APIRouter(prefix="/blackjack/tournament", tags=["21点锦标赛"])


def _notify_enabled() -> bool:
    return bool(
        blackjack_service.get_blackjack_config_dict().get(
            "tournament_notify_enabled", True
        )
    )


# ============================================================
# 管理端点
# ============================================================


@router.post("/admin/create", response_model=TournamentAdminResponse)
@require_telegram_auth
async def admin_create(
    request: Request,
    data: TournamentCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """创建赛事，并向群组播报（提醒用户参与）。"""
    check_admin_permission(current_user)
    try:
        t = blackjack_service.create_blackjack_tournament(
            data.model_dump(exclude_none=True), created_by=current_user.id
        )
    except ValueError as e:
        _raise_for_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建锦标赛失败: {e}")
        raise HTTPException(status_code=500, detail="创建赛事失败，请稍后再试")

    if _notify_enabled():
        background_tasks.add_task(_broadcast_group, _format_created(t), "赛事创建")

    return TournamentAdminResponse(
        success=True,
        message="赛事已创建",
        tournament=TournamentResponse.from_tournament(t),
    )


@router.put("/admin/{tournament_id}", response_model=TournamentAdminResponse)
@require_telegram_auth
async def admin_update(
    request: Request,
    tournament_id: int,
    data: TournamentUpdateRequest,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """修改赛事。仅报名中的赛事可改。"""
    check_admin_permission(current_user)
    try:
        t = blackjack_service.update_blackjack_tournament(
            int(tournament_id), data.model_dump(exclude_none=True)
        )
    except ValueError as e:
        _raise_for_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"修改锦标赛失败 (id={tournament_id}): {e}")
        raise HTTPException(status_code=500, detail="修改赛事失败，请稍后再试")
    return TournamentAdminResponse(
        success=True,
        message="赛事已更新",
        tournament=TournamentResponse.from_tournament(t),
    )


@router.post("/admin/{tournament_id}/cancel", response_model=TournamentAdminResponse)
@require_telegram_auth
async def admin_cancel(
    request: Request,
    tournament_id: int,
    background_tasks: BackgroundTasks,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """管理员主动取消赛事，全额退还报名费。"""
    check_admin_permission(current_user)
    try:
        result = blackjack_service.cancel_blackjack_tournament(
            int(tournament_id), reason="admin_cancelled"
        )
    except ValueError as e:
        _raise_for_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消锦标赛失败 (id={tournament_id}): {e}")
        raise HTTPException(status_code=500, detail="取消赛事失败，请稍后再试")

    if result.get("cancelled") and _notify_enabled():
        tt = result["tournament"]
        refunds = result["refunds"]
        # 文案在此处先渲染好再交给后台任务：BackgroundTasks 是**延迟执行**的，
        # 传 lambda 进去等于把求值推迟到响应之后，闭包届时读到的未必还是这份数据
        text = _format_cancelled(tt, float(tt["buy_in_credits"]))
        background_tasks.add_task(
            _send_many,
            [r["tg_id"] for r in refunds],
            lambda _tg, _text=text: _text,
            "取消退款",
        )

    return TournamentAdminResponse(
        success=True,
        message="赛事已取消，报名费已全额退还",
        tournament=TournamentResponse.from_tournament(result["tournament"]),
    )


@router.get(
    "/admin/{tournament_id}/consistency",
    response_model=TournamentConsistencyResponse,
)
@require_telegram_auth
async def admin_consistency(
    request: Request,
    tournament_id: int,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """比对 `entrant_count` 与 entry 实际行数。

    两者只在同一事务内一起变动，本不该漂移；但 `entrant_count` 是奖池推导的因子，
    一旦漂移会直接影响派奖金额，故提供一处显式校验而非等出问题再查。
    """
    check_admin_permission(current_user)
    result = blackjack_service.check_blackjack_tournament_consistency(
        int(tournament_id)
    )
    if not result:
        raise HTTPException(status_code=404, detail="赛事不存在")
    return TournamentConsistencyResponse(success=True, **result)
