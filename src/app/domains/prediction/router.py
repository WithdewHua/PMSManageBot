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
from app.databases import db
from app.domains.badge_awards.jobs import check_and_award_game_king_badge
from app.domains.prediction.notifications import (
    notify_prediction_bet_placed,
    notify_prediction_market_created,
    notify_prediction_market_resolved,
    notify_prediction_submission_created,
    notify_prediction_submission_reviewed,
    notify_prediction_user_settlement,
)
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
        markets = db.list_prediction_markets(limit=limit, include_closed=include_closed)
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
    market = db.get_prediction_market_by_id(
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
        rows = db.list_prediction_bets(market_id=market_id, limit=limit)
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
        result = db.place_prediction_bet(
            market_id=market_id,
            tg_id=int(current_user.id),
            option=int(data.option),
            amount=int(data.amount),
        )

        # 押注群组通知（失败不影响接口返回）
        try:
            market = result.get("market") or {}
            await notify_prediction_bet_placed(
                market_id=int(market.get("id") or market_id),
                title=str(market.get("title") or ""),
                bettor_tg_id=int(current_user.id),
                option=int(data.option),
                amount=int(data.amount),
                real_yes_pool=int(market.get("real_yes_pool") or 0),
                real_no_pool=int(market.get("real_no_pool") or 0),
            )
        except Exception as e:
            logger.warning(f"Prediction bet notify failed: {e}")

        background_tasks.add_task(
            check_and_award_game_king_badge,
            user_id=int(current_user.id),
        )

        return {"success": True, **result}
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

        market_id = db.create_prediction_market(
            title=data.title,
            description=data.description,
            betting_deadline=data.betting_deadline,
            created_by=int(current_user.id),
            virtual_yes_pool=int(data.virtual_yes_pool),
            virtual_no_pool=int(data.virtual_no_pool),
            max_bet_per_user=int(data.max_bet_per_user),
        )

        # 新题目群组通知（失败不影响创建）
        try:
            market = db.get_prediction_market_by_id(market_id=int(market_id))
            if market:
                await notify_prediction_market_created(
                    market_id=int(market_id),
                    title=str(market.get("title") or ""),
                    betting_deadline=market.get("betting_deadline"),
                )
        except Exception as e:
            logger.warning(f"Prediction create notify failed: {e}")

        return {"success": True, "market_id": int(market_id)}
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

        submission_id = db.submit_prediction_market(
            title=data.title,
            description=data.description,
            betting_deadline=int(data.betting_deadline),
            submitter_tg_id=int(current_user.id),
        )

        try:
            await notify_prediction_submission_created(
                submission_id=int(submission_id),
                title=str(data.title),
                betting_deadline=int(data.betting_deadline),
                submitter_tg_id=int(current_user.id),
            )
        except Exception as e:
            logger.warning(f"Prediction submission notify failed: {e}")

        return {"success": True, "submission_id": int(submission_id)}
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

        rows = db.list_prediction_submissions(
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
        res = db.review_prediction_submission(
            submission_id=int(submission_id),
            admin_tg_id=int(current_user.id),
            approved=bool(data.approved),
            review_note=data.review_note,
            title=data.title,
            description=data.description,
            betting_deadline=data.betting_deadline,
        )

        reward_credits = 0
        if bool(data.approved):
            # 审核通过奖励投稿用户 1 积分（失败不影响审核流程）
            try:
                submitter_tg_id = int(res.get("submitter_tg_id") or 0)
                if submitter_tg_id > 0:
                    current_credits = db.get_user_credits(submitter_tg_id)
                    if current_credits is None:
                        if db.add_user_data(
                            tg_id=submitter_tg_id,
                            credits=1,
                            donation=0,
                        ):
                            reward_credits = 1
                    else:
                        if db.update_user_credits(
                            credits=round(float(current_credits) + 1, 2),
                            tg_id=submitter_tg_id,
                        ):
                            reward_credits = 1
            except Exception as e:
                logger.warning(f"Prediction submission reward credits failed: {e}")

        if bool(data.approved) and res.get("market_id"):
            try:
                market = db.get_prediction_market_by_id(market_id=int(res["market_id"]))
                if market:
                    await notify_prediction_market_created(
                        market_id=int(market.get("id") or res["market_id"]),
                        title=str(market.get("title") or ""),
                        betting_deadline=market.get("betting_deadline"),
                    )
            except Exception as e:
                logger.warning(f"Prediction publish notify failed: {e}")

        # 通知投稿用户审核结果（通过/不通过都通知）
        try:
            await notify_prediction_submission_reviewed(
                submitter_tg_id=int(res.get("submitter_tg_id") or 0),
                submission_id=int(submission_id),
                approved=bool(data.approved),
                title=str(res.get("title") or data.title or ""),
                review_note=data.review_note,
                reward_credits=int(reward_credits),
                market_id=int(res["market_id"]) if res.get("market_id") else None,
            )
        except Exception as e:
            logger.warning(f"Prediction submission review notify failed: {e}")

        return {"success": True, **res}
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
        res = db.close_prediction_market_betting(market_id=market_id)
        return {"success": True, **res}
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
        res = db.resolve_prediction_market(
            market_id=market_id,
            result_option=int(data.result_option),
            resolved_by=int(current_user.id),
            resolution_note=data.resolution_note,
        )

        # 结算群组通知（失败不影响接口返回）
        try:
            market = db.get_prediction_market_by_id(market_id=int(market_id))
            if market:
                background_tasks.add_task(
                    notify_prediction_market_resolved,
                    market_id=int(market_id),
                    title=str(market.get("title") or ""),
                    result_option=int(res.get("result_option") or data.result_option),
                    total_real_pool=int(res.get("total_real_pool") or 0),
                    payout_pool=int(res.get("payout_pool") or 0),
                    total_fee=int(res.get("total_fee") or 0),
                    fee_burned=int(res.get("fee_burned") or 0),
                    fee_to_glory=int(res.get("fee_to_glory") or 0),
                    winner_count=int(res.get("winner_count") or 0),
                    resolution_note=market.get("resolution_note"),
                )

                # 结算个人通知（BackgroundTasks，命中与未命中都通知）
                try:
                    user_positions = db.list_prediction_user_positions(
                        market_id=int(market_id)
                    )
                    result_option = int(res.get("result_option") or data.result_option)
                    total_real_pool = int(res.get("total_real_pool") or 0)
                    payout_pool = float(res.get("payout_pool") or 0)
                    winner_pool = (
                        int(market.get("real_yes_pool") or 0)
                        if result_option == 1
                        else int(market.get("real_no_pool") or 0)
                    )

                    for pos in user_positions:
                        tg_id = int(pos.get("tg_id"))
                        yes_amount = int(pos.get("yes_amount") or 0)
                        no_amount = int(pos.get("no_amount") or 0)
                        win_amount = yes_amount if result_option == 1 else no_amount

                        payout_amount = 0.0
                        if winner_pool > 0 and payout_pool > 0 and win_amount > 0:
                            ratio = float(win_amount) / float(winner_pool)
                            payout_amount = round(float(payout_pool) * ratio, 2)

                        background_tasks.add_task(
                            notify_prediction_user_settlement,
                            tg_id=tg_id,
                            market_id=int(market_id),
                            title=str(market.get("title") or ""),
                            result_option=result_option,
                            yes_amount=yes_amount,
                            no_amount=no_amount,
                            payout_amount=payout_amount,
                        )

                    logger.info(
                        "Prediction resolve personal notifications queued: "
                        f"market_id={int(market_id)}, users={len(user_positions)}, "
                        f"total_real_pool={total_real_pool}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Prediction resolve personal notify queue failed: {e}"
                    )
        except Exception as e:
            logger.warning(f"Prediction resolve notify failed: {e}")

        return {"success": True, **res}
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
        stats = db.get_prediction_user_stats(int(current_user.id))
        return {"success": True, "data": stats}
    except Exception as e:
        logger.error(f"获取大预言家用户统计失败: {e}")
        raise HTTPException(status_code=500, detail="获取大预言家用户统计失败")
