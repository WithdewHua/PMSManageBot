import time

from app.config import settings
from app.databases import db
from app.databases.db_func import check_and_award_game_king_badge
from app.log import uvicorn_logger as logger
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.routers.admin import check_admin_permission
from app.webapp.schemas import (
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
    TelegramUser,
)
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

router = APIRouter(prefix="/prediction", tags=["大预言家"])


def _get_group_chat_id() -> str | None:
    """获取用于群组通知的 chat_id；未配置则跳过通知。"""
    from app.config import settings

    if getattr(settings, "TG_GROUP_ID", None):
        return str(settings.TG_GROUP_ID)
    return None


async def notify_prediction_market_created(
    *,
    market_id: int,
    title: str,
    betting_deadline: int | None,
) -> None:
    """新题目创建后的群组通知。"""
    from datetime import datetime

    from app.config import settings
    from app.utils.utils import send_message_by_url

    chat_id = _get_group_chat_id()
    if not chat_id:
        logger.info("TG_GROUP not configured; skip prediction created notification")
        return

    deadline_text = "未设置"
    if betting_deadline is not None:
        try:
            deadline_text = datetime.fromtimestamp(
                int(betting_deadline), tz=settings.TZ
            ).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            deadline_text = str(int(betting_deadline))

    text = (
        "🔮 <b>大预言家</b> 新预测已发布\n"
        f"ID：{int(market_id)}\n"
        f"标题：{title}\n"
        f"截止时间：{deadline_text}\n"
        "入口：WebApp 活动页 → 大预言家"
    )
    await send_message_by_url(chat_id=chat_id, text=text, parse_mode="HTML")


async def notify_prediction_markets_closing_soon(
    *,
    markets: list[dict],
    threshold_hours: int = 6,
) -> None:
    """群组通知：押注截止时间临近的题目汇总。"""
    from datetime import datetime

    from app.config import settings
    from app.utils.utils import send_message_by_url

    chat_id = _get_group_chat_id()
    if not chat_id:
        logger.info(
            "TG_GROUP not configured; skip prediction closing soon notification"
        )
        return

    if not markets:
        logger.info("No prediction markets closing soon; skip group notification")
        return

    now_ts = int(time.time())
    lines: list[str] = []
    for idx, market in enumerate(markets, 1):
        market_id = int(market.get("id") or 0)
        title = str(market.get("title") or "")
        betting_deadline = int(market.get("betting_deadline") or 0)

        remain_seconds = max(0, int(betting_deadline) - int(now_ts))
        remain_minutes = remain_seconds // 60
        remain_hours = remain_minutes // 60
        remain_mins = remain_minutes % 60
        remain_text = f"{remain_hours}h {remain_mins}m"

        try:
            deadline_text = datetime.fromtimestamp(
                int(betting_deadline), tz=settings.TZ
            ).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            deadline_text = str(int(betting_deadline))

        lines.append(
            f"{idx}. #{market_id} {title}\n"
            f"   截止：{deadline_text}（剩余 {remain_text}）"
        )

    text = (
        f"⏰ <b>大预言家截止提醒</b>（{int(threshold_hours)}h 内）\n"
        f"共 {len(markets)} 题即将截止押注：\n\n"
        + "\n".join(lines)
        + "\n\n入口：WebApp 活动页 → 大预言家"
    )
    await send_message_by_url(chat_id=chat_id, text=text, parse_mode="HTML")


async def notify_prediction_market_resolved(
    *,
    market_id: int,
    title: str,
    result_option: int,
    total_real_pool: int,
    payout_pool: int,
    total_fee: int,
    fee_burned: int,
    fee_to_glory: int,
    winner_count: int,
    resolution_note: str | None,
) -> None:
    """题目结算后的群组通知。"""
    from app.utils.utils import send_message_by_url

    chat_id = _get_group_chat_id()
    if not chat_id:
        logger.info("TG_GROUP not configured; skip prediction resolved notification")
        return

    result_text = "YES" if int(result_option) == 1 else "NO"
    note_text = (resolution_note or "").strip() or "无"
    text = (
        f"🏁 <b>大预言家 #{int(market_id)}</b> 已结算\n"
        f"标题：{title}\n"
        f"结果：{result_text}\n"
        f"实盘总池：{int(total_real_pool)} 积分\n"
        f"派奖总额：{int(payout_pool)} 积分\n"
        f"总手续费：{int(total_fee)}（燃烧 {int(fee_burned)} / 奖池 {int(fee_to_glory)}）\n"
        f"获胜人数：{int(winner_count)}\n"
        f"裁决备注：{note_text}"
    )
    await send_message_by_url(chat_id=chat_id, text=text, parse_mode="HTML")


async def notify_prediction_user_settlement(
    *,
    tg_id: int,
    market_id: int,
    title: str,
    result_option: int,
    yes_amount: int,
    no_amount: int,
    payout_amount: float,
) -> None:
    """题目结算后的个人通知（无论命中与否都发送）。"""
    from app.utils.utils import send_message_by_url

    result_text = "YES" if int(result_option) == 1 else "NO"
    win_amount = int(yes_amount) if int(result_option) == 1 else int(no_amount)
    lose_amount = int(no_amount) if int(result_option) == 1 else int(yes_amount)
    hit = win_amount > 0
    status_text = "✅ 你猜中了" if hit else "❌ 你没有猜中"

    text = (
        f"🏁 <b>大预言家 #{int(market_id)}</b> 已结算\n"
        f"标题：{title}\n"
        f"开奖结果：{result_text}\n"
        f"你的押注：YES {int(yes_amount)} / NO {int(no_amount)}\n"
        f"命中金额：{int(win_amount)} 积分\n"
        f"未中金额：{int(lose_amount)} 积分\n"
        f"结算返还：{float(payout_amount):.2f} 积分\n"
        f"结果：{status_text}"
    )
    await send_message_by_url(chat_id=int(tg_id), text=text, parse_mode="HTML")


async def notify_prediction_bet_placed(
    *,
    market_id: int,
    title: str,
    bettor_tg_id: int,
    option: int,
    amount: int,
    real_yes_pool: int,
    real_no_pool: int,
) -> None:
    """用户押注后的群组通知。"""
    from app.utils.utils import get_user_name_from_tg_id, send_message_by_url

    chat_id = _get_group_chat_id()
    if not chat_id:
        logger.info("TG_GROUP not configured; skip prediction bet notification")
        return

    option_text = "YES" if int(option) == 1 else "NO"
    bettor_name = get_user_name_from_tg_id(int(bettor_tg_id)) or int(bettor_tg_id)
    text = (
        f"🎯 <b>大预言家 #{int(market_id)}</b> 有新押注\n"
        f"标题：{title}\n"
        f"参与用户：<code>{bettor_name}</code>\n"
        f"方向：{option_text}\n"
        f"金额：{int(amount)} 积分\n"
        f"实盘池：YES {int(real_yes_pool)} / NO {int(real_no_pool)}"
    )
    await send_message_by_url(chat_id=chat_id, text=text, parse_mode="HTML")


async def notify_prediction_submission_created(
    *,
    submission_id: int,
    title: str,
    betting_deadline: int,
    submitter_tg_id: int,
) -> None:
    """用户提交预测题目后，通知管理员审核。"""
    from datetime import datetime

    from app.config import settings
    from app.utils.utils import get_user_name_from_tg_id, send_message_by_url

    submitter_name = get_user_name_from_tg_id(int(submitter_tg_id)) or int(
        submitter_tg_id
    )
    try:
        deadline_text = datetime.fromtimestamp(
            int(betting_deadline), tz=settings.TZ
        ).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        deadline_text = str(int(betting_deadline))

    text = (
        "📝 <b>大预言家</b> 收到新题目投稿\n"
        f"投稿ID：{int(submission_id)}\n"
        f"标题：{title}\n"
        f"截止时间：{deadline_text}\n"
        f"提交用户：<code>{submitter_name}</code> ({int(submitter_tg_id)})\n"
        "请到管理端审核并发布。"
    )

    admin_chat_ids = getattr(settings, "TG_ADMIN_CHAT_ID", []) or []
    for admin_chat_id in admin_chat_ids:
        try:
            await send_message_by_url(
                chat_id=int(admin_chat_id),
                text=text,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(
                f"Prediction submission notify admin failed: {admin_chat_id}, error={e}"
            )


async def notify_prediction_submission_reviewed(
    *,
    submitter_tg_id: int,
    submission_id: int,
    approved: bool,
    title: str,
    review_note: str | None,
    reward_credits: int = 0,
    market_id: int | None = None,
) -> None:
    """投稿审核完成后，通知提交用户审核结果。"""
    from app.utils.utils import send_message_by_url

    status_text = "✅ 通过" if bool(approved) else "❌ 未通过"
    note_text = (review_note or "").strip() or "无"
    reward_text = (
        f"\n奖励积分：+{int(reward_credits)}" if int(reward_credits) > 0 else ""
    )
    market_text = (
        f"\n已发布题目ID：{int(market_id)}"
        if bool(approved) and market_id is not None
        else ""
    )

    text = (
        "🧾 <b>大预言家</b> 投稿审核结果\n"
        f"投稿ID：{int(submission_id)}\n"
        f"标题：{title}\n"
        f"审核结果：{status_text}{market_text}{reward_text}\n"
        f"审核备注：{note_text}"
    )
    await send_message_by_url(
        chat_id=int(submitter_tg_id), text=text, parse_mode="HTML"
    )


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
