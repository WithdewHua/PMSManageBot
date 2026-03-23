import time

from app.databases import db
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
    TelegramUser,
)
from fastapi import APIRouter, Depends, HTTPException, Request

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


@router.get("/{market_id}", response_model=PredictionMarketDetailResponse)
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


@router.get("/{market_id}/bets", response_model=PredictionBetListResponse)
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


@router.post("/{market_id}/bet", response_model=dict)
@require_telegram_auth
async def place_bet(
    request: Request,
    market_id: int,
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


@router.post("/{market_id}/close", response_model=dict)
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


@router.post("/{market_id}/resolve", response_model=dict)
@require_telegram_auth
async def resolve_market(
    request: Request,
    market_id: int,
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
                await notify_prediction_market_resolved(
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
