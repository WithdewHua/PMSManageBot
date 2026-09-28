"""21 点活动路由

只做参数校验、权限、异常翻译与超时任务编排；业务逻辑与事务在 `blackjack_service.py` 的
`blackjack_*` 方法里，规则判定在 `blackjack_engine.py`。

响应一律经 `BlackjackHandResponse.from_hand()` 构造，庄家暗牌与随机种子的过滤
落在该构造入口，不在本模块逐处 if 判断（设计决策 10）。
"""

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.core.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.core.log import uvicorn_logger as logger
from app.core.schemas import TelegramUser
from app.domains.badge_awards.jobs import check_and_award_game_king_badge
from app.domains.blackjack import service as blackjack_service
from app.domains.blackjack.exceptions import BlackjackError
from app.domains.blackjack.rules import BlackjackRuleError
from app.domains.blackjack.schemas import (
    BlackjackActionResponse,
    BlackjackAdminConfig,
    BlackjackAdminStatsResponse,
    BlackjackConfigUpdateRequest,
    BlackjackCurrentHandResponse,
    BlackjackDealRequest,
    BlackjackDecisionFeedback,
    BlackjackFreespinGrant,
    BlackjackHandResponse,
    BlackjackJackpotSeedRequest,
    BlackjackPublicConfigResponse,
    BlackjackUserStatsResponse,
)

router = APIRouter(prefix="/blackjack", tags=["21点"])


from app.domains.blackjack.jobs.cash import (
    _schedule_blackjack_timeout,
)


def _raise_typed_error(error: BlackjackError) -> None:
    payload = error.payload
    code = error.code
    details = {
        "blackjack_disabled": "21 点活动当前未开放",
        "blackjack_hand_in_progress": "你还有一手牌未结束，请先完成",
        "blackjack_hand_in_progress_in_tournament": "你在锦标赛中还有一手牌未结束，请先到锦标赛里打完",
        "blackjack_hand_already_finished": "该手牌已结束",
        "blackjack_not_player_turn": "当前不是你的回合",
        "blackjack_already_doubled": "本手牌已加倍，不能重复加倍",
        "blackjack_cannot_double_after_hit": "已要牌，不能再加倍",
        "blackjack_surrender_disabled": "投降当前未开放",
        "blackjack_cannot_surrender_after_hit": "已要牌，不能再投降",
        "blackjack_cannot_surrender_after_double": "已加倍，不能再投降",
        "blackjack_hand_not_found": "手牌不存在",
        "blackjack_user_stats_not_found": "用户积分信息不存在",
        "blackjack_insufficient_credits": "积分不足",
        "blackjack_insufficient_credits_to_double": "积分不足，无法加倍",
        "blackjack_deal_too_frequent": "操作过于频繁，请稍后再试",
        "blackjack_rule_violation": "牌靴异常，请联系管理员",
    }
    if code == "blackjack_invalid_bet":
        options = payload.get("bet_options", [])
        detail = f"注额不合法，可选档位为 {'、'.join(str(x) for x in options)}"
    elif code == "blackjack_insufficient_credits_for_entry":
        detail = f"积分不足，参与需至少 {payload.get('required', '')} 积分"
    elif code == "blackjack_tournament_not_found":
        detail = str(payload.get("legacy_message", error.message))
    else:
        detail = details.get(code, payload.get("detail", error.message))
    status_code = 404 if code == "blackjack_hand_not_found" else error.status_code
    raise HTTPException(status_code=status_code, detail=detail)


def _raise_for_value_error(e: ValueError) -> None:
    """Translate only legacy untyped errors; new domain errors use stable codes."""
    if isinstance(e, BlackjackError):
        _raise_typed_error(e)
    if isinstance(e, BlackjackRuleError):
        raise HTTPException(status_code=500, detail="牌靴异常，请联系管理员")
    raise HTTPException(status_code=400, detail=str(e))


def _build_action_response(
    result: dict, tg_id: int, message: str
) -> BlackjackActionResponse:
    """由 DB 层返回值构造动作响应。"""
    decision = result.get("decision")
    return BlackjackActionResponse(
        success=True,
        message=message,
        hand=BlackjackHandResponse.from_hand(result["hand"]),
        settled=bool(result.get("settled")),
        current_credits=float(blackjack_service.get_current_credits(int(tg_id))),
        decision=BlackjackDecisionFeedback(**decision) if decision else None,
        jackpot_balance=blackjack_service.get_blackjack_jackpot(),
        relief_credits=float(result.get("relief_credits") or 0),
        freespin_grants=[
            BlackjackFreespinGrant(**g) for g in (result.get("freespins") or [])
        ],
    )


@router.post("/deal", response_model=BlackjackActionResponse)
@require_telegram_auth
async def deal(
    request: Request,
    data: BlackjackDealRequest,
    background_tasks: BackgroundTasks,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """发牌"""
    try:
        result = blackjack_service.create_blackjack_hand(
            tg_id=int(current_user.id), bet_credits=int(data.bet_credits)
        )
        hand = result["hand"]

        # 未结算的手牌需要超时兜底；天胡直接结算的手牌不需要。
        # 时限取手牌上的快照，与结算口径一致，避免与配置的后续改动脱节。
        if not result.get("settled"):
            _schedule_blackjack_timeout(
                hand_id=int(hand["id"]),
                timeout_minutes=int(hand["hand_timeout_minutes"]),
            )

        if result.get("settled"):
            background_tasks.add_task(
                check_and_award_game_king_badge,
                user_id=int(current_user.id),
            )

        return _build_action_response(result, int(current_user.id), "发牌成功")
    except ValueError as e:
        _raise_for_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"21 点发牌失败: {e}")
        raise HTTPException(status_code=500, detail="发牌失败")


@router.post("/{hand_id}/hit", response_model=BlackjackActionResponse)
@require_telegram_auth
async def hit(
    request: Request,
    hand_id: int,
    background_tasks: BackgroundTasks,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """要牌"""
    try:
        result = blackjack_service.blackjack_hit(
            tg_id=int(current_user.id), hand_id=int(hand_id)
        )
        if result.get("settled"):
            background_tasks.add_task(
                check_and_award_game_king_badge,
                user_id=int(current_user.id),
            )
        return _build_action_response(result, int(current_user.id), "要牌成功")
    except ValueError as e:
        _raise_for_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"21 点要牌失败: {e}")
        raise HTTPException(status_code=500, detail="要牌失败")


@router.post("/{hand_id}/stand", response_model=BlackjackActionResponse)
@require_telegram_auth
async def stand(
    request: Request,
    hand_id: int,
    background_tasks: BackgroundTasks,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """停牌"""
    try:
        result = blackjack_service.blackjack_stand(
            tg_id=int(current_user.id), hand_id=int(hand_id)
        )
        background_tasks.add_task(
            check_and_award_game_king_badge,
            user_id=int(current_user.id),
        )
        return _build_action_response(result, int(current_user.id), "停牌成功")
    except ValueError as e:
        _raise_for_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"21 点停牌失败: {e}")
        raise HTTPException(status_code=500, detail="停牌失败")


@router.post("/{hand_id}/double", response_model=BlackjackActionResponse)
@require_telegram_auth
async def double(
    request: Request,
    hand_id: int,
    background_tasks: BackgroundTasks,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """加倍：追加一份基础注额，只发一张牌并自动停牌"""
    try:
        result = blackjack_service.blackjack_double(
            tg_id=int(current_user.id), hand_id=int(hand_id)
        )
        background_tasks.add_task(
            check_and_award_game_king_badge,
            user_id=int(current_user.id),
        )
        return _build_action_response(result, int(current_user.id), "加倍成功")
    except ValueError as e:
        _raise_for_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"21 点加倍失败: {e}")
        raise HTTPException(status_code=500, detail="加倍失败")


@router.post("/{hand_id}/surrender", response_model=BlackjackActionResponse)
@require_telegram_auth
async def surrender(
    request: Request,
    hand_id: int,
    background_tasks: BackgroundTasks,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """投降：返还一半基础注额，手牌立即结算，不经庄家回合"""
    try:
        result = blackjack_service.blackjack_surrender(
            tg_id=int(current_user.id), hand_id=int(hand_id)
        )
        background_tasks.add_task(
            check_and_award_game_king_badge,
            user_id=int(current_user.id),
        )
        return _build_action_response(result, int(current_user.id), "已投降")
    except ValueError as e:
        _raise_for_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"21 点投降失败: {e}")
        raise HTTPException(status_code=500, detail="投降失败")


@router.get("/current", response_model=BlackjackCurrentHandResponse)
@require_telegram_auth
async def get_current_hand(
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """取当前进行中的**现金局**手牌，供恢复牌桌用。没有则 hand 为 null。

    赛内手牌不在此返回：它与现金局共用「至多一手」不变量，故 `get_current_blackjack_hand`
    可能返回一手赛内牌，但现金局牌桌对它无能为力（所有动作端点都拒赛内手牌）。
    把它滤掉，现金局界面正常展示下注区，赛内牌桌自会经锦标赛入口恢复。
    """
    try:
        hand = blackjack_service.get_current_blackjack_hand(tg_id=int(current_user.id))
        if hand and hand.get("tournament_id") is not None:
            hand = None
        return BlackjackCurrentHandResponse(
            hand=BlackjackHandResponse.from_hand(hand) if hand else None,
            current_credits=float(
                blackjack_service.get_current_credits(int(current_user.id))
            ),
            jackpot_balance=blackjack_service.get_blackjack_jackpot(),
            free_hands_remaining=blackjack_service.get_blackjack_free_hands_remaining(
                int(current_user.id)
            ),
        )
    except Exception as e:
        logger.error(f"获取当前 21 点手牌失败: {e}")
        raise HTTPException(status_code=500, detail="获取当前手牌失败")


@router.get("/user-stats", response_model=BlackjackUserStatsResponse)
@require_telegram_auth
async def get_user_stats(
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """用户的 21 点个人统计"""
    try:
        stats = blackjack_service.get_user_blackjack_stats(tg_id=int(current_user.id))
        return BlackjackUserStatsResponse(**stats)
    except Exception as e:
        logger.error(f"获取 21 点个人统计失败: {e}")
        raise HTTPException(status_code=500, detail="获取统计失败")


@router.get("/config", response_model=BlackjackPublicConfigResponse)
@require_telegram_auth
async def get_public_config(
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """对用户公开的参数，供牌桌与规则说明渲染。

    前端不得硬编码赔率、注额、门槛、抽水比率，一律取自本接口。
    """
    try:
        config = blackjack_service.get_blackjack_config_dict()
        return BlackjackPublicConfigResponse(
            enabled=bool(config.get("enabled", False)),
            bet_options=[int(b) for b in config.get("bet_options") or []],
            min_credits=int(config.get("min_credits", 30)),
            blackjack_payout=float(config.get("blackjack_payout", 1.5)),
            rake_percent_on_profit=round(
                float(config.get("rake_bp_on_profit", 300)) / 100.0, 2
            ),
            dealer_hits_soft_17=bool(config.get("dealer_hits_soft_17", False)),
            surrender_enabled=bool(config.get("surrender_enabled", True)),
            hand_timeout_minutes=int(config.get("hand_timeout_minutes", 15)),
            free_hands_per_day=int(config.get("free_hands_per_day", 1)),
            jackpot_enabled=bool(config.get("jackpot_enabled", True)),
            jackpot_balance=blackjack_service.get_blackjack_jackpot(),
            jackpot_suited_bj_pct=float(config.get("jackpot_suited_bj_pct", 10)),
            relief_enabled=bool(config.get("relief_enabled", True)),
            relief_threshold=int(config.get("relief_threshold", 8)),
            relief_multiplier=float(config.get("relief_multiplier", 1.0)),
            cashback_enabled=bool(config.get("cashback_enabled", True)),
            cashback_rate=float(config.get("cashback_rate", 0.15)),
            freespins_enabled=bool(config.get("freespins_enabled", True)),
            freespins_hand_threshold=int(config.get("freespins_hand_threshold", 20)),
            freespins_weekly_cap=int(config.get("freespins_weekly_cap", 5)),
            freespins_expiry_days=int(config.get("freespins_expiry_days", 7)),
        )
    except Exception as e:
        logger.error(f"获取 21 点配置失败: {e}")
        raise HTTPException(status_code=500, detail="获取配置失败")


@router.get("/admin/config", response_model=BlackjackAdminConfig)
@require_telegram_auth
async def get_admin_config(
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """管理员读取完整配置"""
    check_admin_permission(current_user)
    try:
        config = blackjack_service.get_blackjack_config_dict()
        return BlackjackAdminConfig(**config)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 21 点管理配置失败: {e}")
        raise HTTPException(status_code=500, detail="获取配置失败")


@router.put("/config", response_model=BlackjackAdminConfig)
@require_telegram_auth
async def update_config(
    request: Request,
    data: BlackjackConfigUpdateRequest,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """管理员更新配置（含停用开关）。

    配置变更不影响进行中或已结算的手牌——每手牌按其发牌时快照的参数结算。
    """
    check_admin_permission(current_user)
    try:
        if int(data.rake_burn_bp) + int(data.rake_jackpot_bp) != int(
            data.rake_bp_on_profit
        ):
            raise HTTPException(
                status_code=400,
                detail="抽水拆分之和必须等于抽水总比率",
            )
        if not data.bet_options or any(int(b) <= 0 for b in data.bet_options):
            raise HTTPException(status_code=400, detail="注额档位必须为正整数")

        config = data.model_dump()
        config["bet_options"] = sorted({int(b) for b in data.bet_options})

        if not blackjack_service.set_blackjack_config(
            "config", json.dumps(config, ensure_ascii=False)
        ):
            raise HTTPException(status_code=500, detail="保存配置失败")

        return BlackjackAdminConfig(**blackjack_service.get_blackjack_config_dict())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新 21 点配置失败: {e}")
        raise HTTPException(status_code=500, detail="更新配置失败")


@router.post("/admin/jackpot/seed", response_model=dict)
@require_telegram_auth
async def seed_jackpot(
    request: Request,
    data: BlackjackJackpotSeedRequest,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """管理员向幸运奖池注入种子余额。

    奖池平时只由抽水供养，本接口是**唯一会增发积分**的路径，故仅限管理员显式
    调用。用途是上线冷启动时让奖池有个初值，否则前期余额几乎为零、毫无观感。
    """
    check_admin_permission(current_user)
    try:
        balance = blackjack_service.seed_blackjack_jackpot(float(data.amount))
        return {
            "success": True,
            "message": f"已注入 {data.amount} 积分",
            "jackpot_balance": balance,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail="注入金额必须为正数") from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"注入 21 点奖池种子失败: {e}")
        raise HTTPException(status_code=500, detail="注入奖池失败")


@router.get("/admin/stats", response_model=BlackjackAdminStatsResponse)
@require_telegram_auth
async def get_admin_stats(
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """21 点的运营聚合统计，供管理页卡片展示。仅管理员可读。

    与 `/user-stats` 不同，这里是全站口径，含押注量、抽水与积分净流向，属运营
    内部数据，故与 `/admin/config` 一样要过管理员校验。
    """
    check_admin_permission(current_user)
    try:
        return BlackjackAdminStatsResponse(
            **blackjack_service.get_blackjack_admin_stats()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 21 点运营统计失败: {e}")
        raise HTTPException(status_code=500, detail="获取统计失败")
