from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.core.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.core.log import uvicorn_logger as logger
from app.core.schemas import TelegramUser
from app.domains.badge_awards.jobs import check_and_award_game_king_badge
from app.domains.treasure import exceptions as treasure_exceptions
from app.domains.treasure import service as treasure_service
from app.domains.treasure.schemas import (
    TreasureCreateIssueRequest,
    TreasureIssueDetailResponse,
    TreasureIssueItem,
    TreasureIssueListResponse,
    TreasureJoinRequest,
    TreasureJoinResponse,
    TreasureParticipationItem,
    TreasureParticipationListResponse,
)

router = APIRouter(prefix="/treasure", tags=["夺宝奇兵"])


@router.get("/user-stats")
@require_telegram_auth
async def get_user_treasure_stats(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取用户个人夺宝统计数据。"""
    try:
        stats = treasure_service.get_user_treasure_stats(int(current_user.id))
        return {"success": True, "data": stats}
    except treasure_exceptions.TreasureError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        ) from error
    except Exception as error:
        logger.error(f"获取用户夺宝统计失败: {error}")
        raise HTTPException(status_code=500, detail="获取用户夺宝统计失败") from error


@router.get("/list", response_model=TreasureIssueListResponse)
@require_telegram_auth
async def list_issues(
    request: Request,
    include_closed: bool = True,
    limit: int = 50,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        issues = treasure_service.list_treasure_issues(
            limit=limit, include_closed=include_closed
        )
        items = [TreasureIssueItem(**issue) for issue in issues]
        return TreasureIssueListResponse(issues=items, total=len(items))
    except treasure_exceptions.TreasureError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        ) from error
    except Exception as error:
        logger.error(f"获取夺宝期数列表失败: {error}")
        raise HTTPException(status_code=500, detail="获取夺宝期数列表失败") from error


@router.get("/{issue_id}", response_model=TreasureIssueDetailResponse)
@require_telegram_auth
async def get_issue_detail(
    request: Request,
    issue_id: int,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        issue = treasure_service.get_treasure_issue(int(issue_id))
        if not issue:
            raise HTTPException(status_code=404, detail="期数不存在")
        item = TreasureIssueItem(**issue)
        return TreasureIssueDetailResponse(
            issue=item,
            description=issue.get("description"),
            external_random_b=issue.get("external_random_b"),
            settled_at=issue.get("settled_at"),
        )
    except treasure_exceptions.TreasureError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        ) from error


@router.get(
    "/{issue_id}/participations",
    response_model=TreasureParticipationListResponse,
)
@require_telegram_auth
async def list_participations(
    request: Request,
    issue_id: int,
    limit: int = 100,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        rows = treasure_service.list_treasure_participations(
            int(issue_id), limit=int(limit)
        )
        items = [TreasureParticipationItem(**row) for row in rows]
        return TreasureParticipationListResponse(participations=items, total=len(items))
    except treasure_exceptions.TreasureError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        ) from error
    except Exception as error:
        logger.error(f"获取参与记录失败: {error}")
        raise HTTPException(status_code=500, detail="获取参与记录失败") from error


@router.post("/{issue_id}/join", response_model=TreasureJoinResponse)
@require_telegram_auth
async def join_issue(
    request: Request,
    issue_id: int,
    background_tasks: BackgroundTasks,
    data: TreasureJoinRequest,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        result = await treasure_service.join_treasure_issue(
            issue_id=int(issue_id),
            tg_id=int(current_user.id),
            quantity=int(getattr(data, "quantity", 1)),
        )
        background_tasks.add_task(
            check_and_award_game_king_badge,
            user_id=int(current_user.id),
        )
        return TreasureJoinResponse(
            success=True,
            message="参与成功",
            participation=result.get("participation"),
            participations=result.get("participations"),
            issue=result.get("issue"),
            settled=bool(result.get("settled")),
            winner_number=result.get("winner_number"),
            winner_tg_id=result.get("winner_tg_id"),
        )
    except treasure_exceptions.TreasureError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        ) from error
    except Exception as error:
        logger.error(f"参与夺宝失败: {error}")
        raise HTTPException(status_code=500, detail="参与失败") from error


@router.post("/create", response_model=dict)
@require_telegram_auth
async def create_issue(
    request: Request,
    data: TreasureCreateIssueRequest,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    check_admin_permission(current_user)
    try:
        issue_id = await treasure_service.create_treasure_issue(
            title=data.title,
            description=data.description,
            prize_credits=data.prize_credits,
            total_credits_required=data.total_credits_required,
            credits_per_share=data.credits_per_share,
            start_number=data.start_number,
            created_by=int(current_user.id),
        )
        return {"success": True, "issue_id": issue_id}
    except treasure_exceptions.TreasureError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        ) from error
    except Exception as error:
        logger.error(f"创建夺宝期数失败: {error}")
        raise HTTPException(status_code=500, detail="创建失败") from error


@router.post("/{issue_id}/cancel", response_model=dict)
@require_telegram_auth
async def cancel_issue(
    request: Request,
    issue_id: int,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """管理员取消进行中的夺宝期数，并退还参与者积分。"""
    check_admin_permission(current_user)
    try:
        result = treasure_service.cancel_treasure_issue(issue_id=int(issue_id))
        return {"success": True, **result}
    except treasure_exceptions.TreasureError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        ) from error
    except Exception as error:
        logger.error(f"取消夺宝期数失败: {error}")
        raise HTTPException(status_code=500, detail="删除失败") from error
