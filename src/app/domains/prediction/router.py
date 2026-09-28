import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.core.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.core.schemas import TelegramUser
from app.domains.badge_awards.jobs import check_and_award_game_king_badge
from app.domains.prediction import service as prediction_service
from app.domains.prediction.exceptions import PredictionError
from app.domains.prediction.schemas import (
    PredictionBetItem,
    PredictionBetListResponse,
    PredictionBetRequest,
    PredictionCreateMarketRequest,
    PredictionMarketDetailResponse,
    PredictionMarketItem,
    PredictionMarketListResponse,
    PredictionResolveRequest,
    PredictionSubmissionItem,
    PredictionSubmissionListResponse,
    PredictionSubmissionReviewRequest,
    PredictionSubmitRequest,
)

router = APIRouter(prefix="/prediction", tags=["大预言家"])


@router.get("/list", response_model=PredictionMarketListResponse)
@require_telegram_auth
async def list_markets(
    request: Request,
    include_closed: bool = True,
    limit: int = 50,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        markets = prediction_service.list_prediction_markets(
            limit=limit, include_closed=include_closed
        )
        items = [PredictionMarketItem(**m) for m in markets]
        return PredictionMarketListResponse(markets=items, total=len(items))
    except Exception as e:
        logger.error(f"获取预测题目列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取预测题目列表失败")


@router.get("/{market_id:int}", response_model=PredictionMarketDetailResponse)
@require_telegram_auth
async def get_market_detail(
    request: Request,
    market_id: int,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    market = prediction_service.get_prediction_market_by_id(
        market_id=market_id, tg_id=int(current_user.id)
    )
    if not market:
        raise HTTPException(status_code=404, detail="预测题目不存在")

    return PredictionMarketDetailResponse(
        market=PredictionMarketItem(
            id=int(market["id"]),
            title=str(market["title"]),
            description=market.get("description"),
            status=int(market["status"]),
            result_option=market.get("result_option"),
            betting_deadline=market.get("betting_deadline"),
            real_yes_pool=int(market["real_yes_pool"]),
            real_no_pool=int(market["real_no_pool"]),
            virtual_yes_pool=int(market["virtual_yes_pool"]),
            virtual_no_pool=int(market["virtual_no_pool"]),
            yes_odds=float(market["yes_odds"]),
            no_odds=float(market["no_odds"]),
            max_bet_per_user=int(market["max_bet_per_user"]),
            created_at=market["created_at"],
        ),
        my_yes_amount=int(market.get("my_yes_amount") or 0),
        my_no_amount=int(market.get("my_no_amount") or 0),
        fee_rate_bp=int(market.get("fee_rate_bp") or 0),
        fee_burn_bp=int(market.get("fee_burn_bp") or 0),
        fee_glory_bp=int(market.get("fee_glory_bp") or 0),
        resolution_note=market.get("resolution_note"),
        total_fee_collected=int(market.get("total_fee_collected") or 0),
        fee_burned=int(market.get("fee_burned") or 0),
        fee_to_glory=int(market.get("fee_to_glory") or 0),
    )


@router.get("/{market_id:int}/bets", response_model=PredictionBetListResponse)
@require_telegram_auth
async def list_market_bets(
    request: Request,
    market_id: int,
    limit: int = 100,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        rows = prediction_service.list_prediction_bets(market_id, limit=limit)
        items = [PredictionBetItem(**r) for r in rows]
        return PredictionBetListResponse(bets=items, total=len(items))
    except Exception as e:
        logger.error(f"获取押注记录失败: {e}")
        raise HTTPException(status_code=500, detail="获取押注记录失败")


@router.post("/{market_id:int}/bet", response_model=dict)
@require_telegram_auth
async def place_bet(
    request: Request,
    market_id: int,
    background_tasks: BackgroundTasks,
    data: PredictionBetRequest,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        result = await prediction_service.place_prediction_bet(
            market_id=market_id,
            tg_id=int(current_user.id),
            option=int(data.option),
            amount=int(data.amount),
        )

        background_tasks.add_task(
            check_and_award_game_king_badge,
            user_id=int(current_user.id),
        )

        return {"success": True, **result}
    except PredictionError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=e.payload.get("detail", e.message),
        ) from e
    except ValueError as e:
        msg = str(e).lower()
        if "not found" in msg:
            raise HTTPException(status_code=404, detail="预测题目不存在")
        if "not open" in msg or "closed" in msg:
            raise HTTPException(status_code=400, detail="当前不可押注")
        if "insufficient" in msg:
            raise HTTPException(status_code=400, detail="积分不足")
        if "max bet" in msg:
            raise HTTPException(status_code=400, detail="超过该题目个人押注上限")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"押注失败: {e}")
        raise HTTPException(status_code=500, detail="押注失败")


@router.post("/create", response_model=dict)
@require_telegram_auth
async def create_market(
    request: Request,
    data: PredictionCreateMarketRequest,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    check_admin_permission(current_user)
    try:
        if int(data.betting_deadline) <= int(time.time()):
            raise HTTPException(status_code=400, detail="截止时间必须晚于当前时间")

        market_id = await prediction_service.create_prediction_market(
            title=data.title,
            description=data.description,
            betting_deadline=data.betting_deadline,
            created_by=int(current_user.id),
            virtual_yes_pool=int(data.virtual_yes_pool),
            virtual_no_pool=int(data.virtual_no_pool),
            max_bet_per_user=int(data.max_bet_per_user),
        )

        return {"success": True, "market_id": int(market_id)}
    except PredictionError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=e.payload.get("detail", e.message),
        ) from e
    except ValueError as e:
        msg = str(e).lower()
        if "betting_deadline" in msg:
            raise HTTPException(status_code=400, detail="请设置有效的截止时间")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"创建预测题目失败: {e}")
        raise HTTPException(status_code=500, detail="创建预测题目失败")


@router.post("/submit", response_model=dict)
@require_telegram_auth
async def submit_market(
    request: Request,
    data: PredictionSubmitRequest,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        if int(data.betting_deadline) <= int(time.time()):
            raise HTTPException(status_code=400, detail="截止时间必须晚于当前时间")

        submission_id = await prediction_service.submit_prediction_market(
            title=data.title,
            description=data.description,
            betting_deadline=int(data.betting_deadline),
            submitter_tg_id=int(current_user.id),
        )

        return {"success": True, "submission_id": int(submission_id)}
    except PredictionError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=e.payload.get("detail", e.message),
        ) from e
    except ValueError as e:
        msg = str(e).lower()
        if "betting_deadline" in msg:
            raise HTTPException(status_code=400, detail="请设置有效的截止时间")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"提交预测题目失败: {e}")
        raise HTTPException(status_code=500, detail="提交预测题目失败")


@router.get("/submissions", response_model=PredictionSubmissionListResponse)
@require_telegram_auth
async def list_submissions(
    request: Request,
    status: int | None = None,
    limit: int = 50,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        submitter_tg_id = None
        admin_ids = {int(x) for x in (settings.TG_ADMIN_CHAT_ID or [])}
        if int(current_user.id) not in admin_ids:
            submitter_tg_id = int(current_user.id)

        rows = prediction_service.list_prediction_submissions(
            status=status,
            limit=limit,
            submitter_tg_id=submitter_tg_id,
        )
        items = [PredictionSubmissionItem(**r) for r in rows]
        return PredictionSubmissionListResponse(submissions=items, total=len(items))
    except Exception as e:
        logger.error(f"获取预测投稿列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取预测投稿列表失败")


@router.post("/submissions/{submission_id:int}/review", response_model=dict)
@require_telegram_auth
async def review_submission(
    request: Request,
    submission_id: int,
    data: PredictionSubmissionReviewRequest,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    check_admin_permission(current_user)
    try:
        res = await prediction_service.review_prediction_submission(
            submission_id=int(submission_id),
            admin_tg_id=int(current_user.id),
            approved=bool(data.approved),
            review_note=data.review_note,
            title=data.title,
            description=data.description,
            betting_deadline=data.betting_deadline,
        )
        return {"success": True, **res}
    except PredictionError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=e.payload.get("detail", e.message),
        ) from e
    except ValueError as e:
        msg = str(e).lower()
        if "not found" in msg:
            raise HTTPException(status_code=404, detail="投稿不存在")
        if "already reviewed" in msg:
            raise HTTPException(status_code=400, detail="该投稿已审核")
        if "betting_deadline" in msg:
            raise HTTPException(status_code=400, detail="截止时间必须晚于当前时间")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"审核预测投稿失败: {e}")
        raise HTTPException(status_code=500, detail="审核预测投稿失败")


@router.post("/{market_id:int}/close", response_model=dict)
@require_telegram_auth
async def close_market_betting(
    request: Request,
    market_id: int,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    check_admin_permission(current_user)
    try:
        res = prediction_service.close_prediction_market_betting(market_id)
        return {"success": True, **res}
    except PredictionError as e:
        detail = (
            e.message
            if e.code == "prediction.market_not_open"
            else e.payload.get("detail", e.message)
        )
        raise HTTPException(status_code=e.status_code, detail=detail) from e
    except ValueError as e:
        msg = str(e).lower()
        if "not found" in msg:
            raise HTTPException(status_code=404, detail="预测题目不存在")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"截止押注失败: {e}")
        raise HTTPException(status_code=500, detail="截止押注失败")


@router.post("/{market_id:int}/resolve", response_model=dict)
@require_telegram_auth
async def resolve_market(
    request: Request,
    market_id: int,
    background_tasks: BackgroundTasks,
    data: PredictionResolveRequest,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    check_admin_permission(current_user)
    try:
        res = await prediction_service.resolve_prediction_market(
            market_id=market_id,
            result_option=int(data.result_option),
            resolved_by=int(current_user.id),
            resolution_note=data.resolution_note,
        )
        return {"success": True, **res}
    except PredictionError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=e.payload.get("detail", e.message),
        ) from e
    except ValueError as e:
        msg = str(e).lower()
        if "not found" in msg:
            raise HTTPException(status_code=404, detail="预测题目不存在")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"裁决失败: {e}")
        raise HTTPException(status_code=500, detail="裁决失败")


@router.get("/user-stats")
@require_telegram_auth
async def get_user_prediction_stats(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取用户大预言家个人统计。"""
    try:
        stats = prediction_service.get_prediction_user_stats(int(current_user.id))
        return {"success": True, "data": stats}
    except Exception as e:
        logger.error(f"获取大预言家用户统计失败: {e}")
        raise HTTPException(status_code=500, detail="获取大预言家用户统计失败")
