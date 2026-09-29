"""21 点锦标赛路由

只做参数校验、权限、异常翻译与赛事推进的任务编排；业务逻辑与事务在 `blackjack_service.py` 的
`*_tournament*` 方法里，规则判定复用 `blackjack_engine.py`。

赛内手牌的响应一律经 `BlackjackHandResponse.from_hand()` 构造——与现金局共用同一道
信息隐藏闸门（庄家暗牌裁剪、种子与游标排除），不在本模块另写一份。

**赛事推进用每分钟一次的 tick 任务，不用 per-赛事的持久化 date 任务**（design 决策
8）：那套机制的代价是 `misfire_grace_time=None` 的陷阱外加一个重启恢复函数。手牌
超时值得付这个代价（15 分钟时限要求及时性），而赛事是跨天事件，一分钟的推进延迟
无人可感，周期 tick 天然免疫任务丢失与重启，**不需要恢复函数**。

**五处通知的去重一律靠状态的 CAS**，不另设机制：抢到状态流转的一方负责发通知，
抢不到的一方什么都不做。开赛、赛果、取消三处各有多条触发路径（最后一次报名 /
tick 任务 / 任务重试），靠「记得只发一次」是不可能正确的。这与奖池播报的游标轮询
是有意不同的选择——奖池派彩散落六条结算路径、无法收敛成单点，而赛事状态流转天然
就是单点。
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.core.log import uvicorn_logger as logger
from app.domains.blackjack import service as blackjack_service
from app.domains.blackjack.config import (
    TOURNAMENT_CANCELLED,
    TOURNAMENT_REGISTERING,
    TOURNAMENT_RUNNING,
    TOURNAMENT_SETTLED,
)
from app.domains.blackjack.exceptions import BlackjackError
from app.domains.blackjack.rules import BlackjackRuleError
from app.domains.blackjack.schemas import (
    BlackjackHandResponse,
    TournamentActionResponse,
    TournamentCurrentHandResponse,
    TournamentDealRequest,
    TournamentEntryResponse,
    TournamentListResponse,
    TournamentRegisterResponse,
    TournamentResponse,
    TournamentStandingRow,
    TournamentStandingsResponse,
    TournamentWalletResponse,
)
from app.integrations.telegram.profiles import get_user_names_from_tg_ids
from app.transport.http.auth import get_telegram_user, require_telegram_auth
from app.transport.http.schemas import TelegramUser

router = APIRouter(prefix="/blackjack/tournament", tags=["21点锦标赛"])

# 单轮 tick 处理的赛事条数上限。达到上限会**记 error 而非静默截断**——列表按 id
# 倒序取，被截掉的恰好是最老的赛事，它们会永远开不了赛、结不了算。
_TICK_LIST_LIMIT = 100


# ============================================================
# 通知
# ============================================================


from app.domains.blackjack.jobs.tournament import (
    _schedule_tournament_hand_timeout,
)
from app.domains.blackjack.notifications.tournament import (
    notify_tournament_started,
)


def _raise_typed_error(error: BlackjackError) -> None:
    payload = error.payload
    code = error.code
    details = {
        "blackjack_disabled": "21 点活动当前未开放",
        "blackjack_tournament_not_found": "赛事不存在",
        "blackjack_tournament_entry_not_found": "你未报名该赛事",
        "blackjack_already_registered": "你已报名该赛事",
        "blackjack_tournament_full": "报名人数已满",
        "blackjack_registration_closed": "报名已截止",
        "blackjack_tournament_not_open_for_registration": "该赛事当前不接受报名",
        "blackjack_tournament_already_started": "赛事已开赛，无法修改或取消",
        "blackjack_tournament_not_running": "赛事尚未开赛或已结束",
        "blackjack_tournament_finished": "赛事已结束",
        "blackjack_all_hands_played": "你已打满全部手数",
        "blackjack_eliminated": "你的筹码已不足最小注，已被淘汰",
        "blackjack_insufficient_chips": "筹码不足",
        "blackjack_insufficient_chips_to_double": "筹码不足，无法加倍",
        "blackjack_insufficient_credits": "积分不足",
        "blackjack_hand_in_progress": "你还有一手牌未结束，请先完成",
        "blackjack_hand_in_progress_in_cash_game": "你还有一手现金局的牌未结束，请先去 21 点打完",
        "blackjack_hand_in_progress_in_tournament": "你在另一场锦标赛中还有一手牌未结束，请先打完",
        "blackjack_hand_already_finished": "该手牌已结束",
        "blackjack_not_player_turn": "当前不是你的回合",
        "blackjack_already_doubled": "本手牌已加倍，不能重复加倍",
        "blackjack_cannot_double_after_hit": "已要牌，不能再加倍",
        "blackjack_surrender_disabled": "本赛事未开放投降",
        "blackjack_cannot_surrender_now": "当前不可投降",
        "blackjack_hand_not_found": "手牌不存在",
        "blackjack_user_stats_not_found": "用户积分信息不存在",
        "blackjack_deal_too_frequent": "操作过于频繁，请稍后再试",
    }
    if code == "blackjack_insufficient_credits_for_entry":
        detail = (
            f"争霸赛余额与积分合计不足，报名需 {payload.get('required', '')} 积分"
            "（报名时优先扣争霸赛余额）"
        )
    elif code == "blackjack_bet_must_be_a_multiple_of":
        detail = f"注额须为 {payload.get('bet_step', '')} 的整数倍"
    elif code == "blackjack_bet_out_of_range":
        detail = f"注额须在 {payload.get('bet_range', '')} 筹码之间"
    elif code == "blackjack_play_window_must_be_at_least":
        detail = f"赛程过短：报名截止到完赛截止之间至少需要 {payload.get('minutes', '')} 分钟"
    elif code == "blackjack_tournament_title_required":
        detail = "赛事名称不能为空"
    elif code == "blackjack_register_deadline_must_be_in_the_future":
        detail = "报名截止时点须晚于当前时间"
    elif code == "blackjack_seeded_prize_credits_must_not_decrease":
        detail = "已有人报名，奖池补贴只能增加、不能减少"
    elif code == "blackjack_cannot_change_after_entrants_joined":
        detail = "已有人报名，报名费与赛制参数不可再改；如需变更请先取消赛事再重建"
    else:
        detail = details.get(code, payload.get("detail", error.message))
    status_code = 404 if code == "blackjack_tournament_not_found" else error.status_code
    raise HTTPException(status_code=status_code, detail=detail)


def _raise_for_value_error(e: ValueError) -> None:
    """Translate only legacy untyped errors; new domain errors use stable codes."""
    if isinstance(e, BlackjackError):
        _raise_typed_error(e)
    if isinstance(e, BlackjackRuleError):
        raise HTTPException(status_code=500, detail="牌靴异常，请联系管理员")
    raise HTTPException(status_code=400, detail=str(e))


def _hands_remaining(tournament: dict, entry: dict) -> int:
    return max(0, int(tournament["total_hands"]) - int(entry["hands_played"]))


def _action_response(result: dict, message: str) -> TournamentActionResponse:
    """由 DB 层返回值构造赛内动作响应。

    筹码、进度与总手数**全部来自 `result`**，不再为算「剩余手数」而多查一次赛事：
    那次查询走的是吞异常返回 `None` 的读方法，一个瞬时的 DB 错误就会让一次已经
    落库并按筹码赔付完毕的结算变成 500，而客户端从响应里什么也拿不到。

    缺字段时一律传 `None` 而非 0——见 `TournamentActionResponse` 的说明。
    """
    played = result.get("hands_played")
    total = result.get("total_hands")
    remaining = (
        max(0, int(total) - int(played))
        if played is not None and total is not None
        else None
    )
    return TournamentActionResponse(
        success=True,
        message=message,
        hand=BlackjackHandResponse.from_hand(result["hand"]),
        settled=bool(result.get("settled")),
        chips=result.get("chips"),
        hands_played=played,
        hands_remaining=remaining,
        entry_status=result.get("entry_status"),
    )


@router.get("", response_model=TournamentListResponse)
@require_telegram_auth
async def list_tournaments(
    request: Request,
    include_finished: bool = False,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """赛事大厅：报名中与进行中的赛事，附带当前用户的报名状态。

    `include_finished` 时连已结算与已取消一并列出。管理面板需要它——赛事一结算就
    从列表里消失的话，`/admin/{id}/consistency` 恰好在唯一需要它的时候（已经派过
    奖了）变得无从触达。
    """
    statuses = (
        (
            TOURNAMENT_REGISTERING,
            TOURNAMENT_RUNNING,
            TOURNAMENT_SETTLED,
            TOURNAMENT_CANCELLED,
        )
        if include_finished
        else None
    )
    tournaments = blackjack_service.list_blackjack_tournaments(
        tg_id=current_user.id,
        statuses=statuses,
        limit=40 if include_finished else 20,
    )
    return TournamentListResponse(
        success=True,
        tournaments=[TournamentResponse.from_tournament(t) for t in tournaments],
    )


# 注意注册顺序：/wallet 这类字面量单段路由必须排在 /{tournament_id} 之前——
# FastAPI 按注册顺序匹配，否则 GET /wallet 会撞上 int 路径参数、把
# "wallet" 当赛事 ID 解析而返回 422
@router.get("/wallet", response_model=TournamentWalletResponse)
@require_telegram_auth
async def get_wallet(
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """争霸赛余额：21 点周损失返还的发放去向，仅可支付报名费。"""
    return TournamentWalletResponse(
        tournament_wallet_credits=float(
            blackjack_service.get_blackjack_tournament_wallet(current_user.id) or 0
        )
    )


@router.get("/{tournament_id}", response_model=TournamentResponse)
@require_telegram_auth
async def get_tournament(
    request: Request,
    tournament_id: int,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """赛事详情。"""
    t = blackjack_service.get_blackjack_tournament(
        int(tournament_id), tg_id=current_user.id
    )
    if not t:
        raise HTTPException(status_code=404, detail="赛事不存在")
    return TournamentResponse.from_tournament(t)


@router.get("/{tournament_id}/standings", response_model=TournamentStandingsResponse)
@require_telegram_auth
async def get_standings(
    request: Request,
    tournament_id: int,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """全场排名。进行中给临时位次，已结算给最终名次。"""
    t = blackjack_service.get_blackjack_tournament(int(tournament_id))
    if not t:
        raise HTTPException(status_code=404, detail="赛事不存在")
    rows = blackjack_service.get_blackjack_tournament_standings(int(tournament_id))
    # 一次性取全部显示名：逐行调 get_user_name_from_tg_id 会把整个用户缓存
    # pickle 反序列化 N 遍，而本端点在每手牌结算后都会被调用一次
    names = get_user_names_from_tg_ids([r["tg_id"] for r in rows])
    standings = []
    for row in rows:
        standings.append(
            TournamentStandingRow(
                **TournamentEntryResponse.from_entry(row).model_dump(),
                display_name=names.get(int(row["tg_id"]), str(row["tg_id"])),
                provisional_rank=row.get("provisional_rank"),
            )
        )
    return TournamentStandingsResponse(
        success=True,
        tournament_id=int(tournament_id),
        status=int(t["status"]),
        standings=standings,
    )


@router.post("/{tournament_id}/register", response_model=TournamentRegisterResponse)
@require_telegram_auth
async def register(
    request: Request,
    tournament_id: int,
    background_tasks: BackgroundTasks,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """报名。满员时本次报名会触发开赛，开赛通知走后台任务。"""
    try:
        result = blackjack_service.register_blackjack_tournament(
            current_user.id, int(tournament_id)
        )
    except ValueError as e:
        _raise_for_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"锦标赛报名失败 (tg_id={current_user.id}): {e}")
        raise HTTPException(status_code=500, detail="报名失败，请稍后再试")

    # 开赛通知放后台：它可能要发 20 条私聊，同步发会让这位报名者的请求卡住数秒。
    # 进程挂掉会丢通知——可接受，与奖池播报同一口径（业务结果早已落库）
    if result.get("started"):
        background_tasks.add_task(
            notify_tournament_started,
            result["tournament"],
            result["notify_entrants"],
        )

    return TournamentRegisterResponse(
        success=True,
        message="报名成功",
        tournament=TournamentResponse.from_tournament(result["tournament"]),
        entry=TournamentEntryResponse.from_entry(result["entry"]),
        started=bool(result.get("started")),
        # 报名事务内返回的余额，避免二次读库（读取失败静默归零的隐患）
        current_credits=float(result.get("current_credits") or 0),
        tournament_wallet_credits=float(result.get("tournament_wallet_credits") or 0),
    )


@router.get("/{tournament_id}/current", response_model=TournamentCurrentHandResponse)
@require_telegram_auth
async def get_current(
    request: Request,
    tournament_id: int,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """赛内当前手牌与筹码状态，供恢复牌桌用。"""
    t = blackjack_service.get_blackjack_tournament(
        int(tournament_id), tg_id=current_user.id
    )
    if not t:
        raise HTTPException(status_code=404, detail="赛事不存在")
    entry = t.get("my_entry")
    if not entry:
        raise HTTPException(status_code=400, detail="你未报名该赛事")

    # 先清掉该用户已超时的手牌，避免返回一手早该结算的牌
    blackjack_service.sweep_timed_out_blackjack_hands(tg_id=current_user.id)
    entry = blackjack_service.get_user_blackjack_tournament_entry(
        current_user.id, int(tournament_id)
    )

    hand = blackjack_service.get_current_blackjack_hand(current_user.id)
    # 只认属于本赛事的手牌：用户可能正持有一手现金局的牌（「至多一手」跨两侧共用），
    # 那手牌不该出现在赛内牌桌上
    if hand and hand.get("tournament_id") != int(tournament_id):
        hand = None

    return TournamentCurrentHandResponse(
        success=True,
        tournament=TournamentResponse.from_tournament(t),
        entry=TournamentEntryResponse.from_entry(entry),
        hand=BlackjackHandResponse.from_hand(hand) if hand else None,
        hands_remaining=_hands_remaining(t, entry),
    )


@router.post("/{tournament_id}/deal", response_model=TournamentActionResponse)
@require_telegram_auth
async def deal(
    request: Request,
    tournament_id: int,
    data: TournamentDealRequest,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """赛内发牌。"""
    try:
        result = blackjack_service.create_blackjack_tournament_hand(
            current_user.id, int(tournament_id), int(data.bet_chips)
        )
    except ValueError as e:
        _raise_for_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"赛内发牌失败 (tg_id={current_user.id}): {e}")
        raise HTTPException(status_code=500, detail="发牌失败，请稍后再试")

    _schedule_tournament_hand_timeout(result)
    return _action_response(result, "发牌成功")


def _run_hand_action(action, tg_id: int, hand_id: int, message: str):
    """执行一个赛内动作并构造响应。

    五个动作端点的错误边界收在这里。**兜底的 `except Exception` 不能省**：并发
    重复报名撞唯一约束、瞬时 DB 错误这类非 ValueError 会一路冒到 FastAPI 变成
    无消息的 500，而现金局那侧每个端点都有这层兜底。
    """
    try:
        result = action(int(tg_id), int(hand_id))
    except ValueError as e:
        _raise_for_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"赛内动作失败 (tg_id={tg_id}, hand={hand_id}): {e}")
        raise HTTPException(status_code=500, detail="操作失败，请稍后再试")
    return _action_response(result, message)


@router.post(
    "/{tournament_id}/hand/{hand_id}/hit", response_model=TournamentActionResponse
)
@require_telegram_auth
async def hit(
    request: Request,
    tournament_id: int,
    hand_id: int,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """赛内要牌。"""
    return _run_hand_action(
        blackjack_service.blackjack_tournament_hit,
        current_user.id,
        hand_id,
        "要牌成功",
    )


@router.post(
    "/{tournament_id}/hand/{hand_id}/stand", response_model=TournamentActionResponse
)
@require_telegram_auth
async def stand(
    request: Request,
    tournament_id: int,
    hand_id: int,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """赛内停牌。"""
    return _run_hand_action(
        blackjack_service.blackjack_tournament_stand,
        current_user.id,
        hand_id,
        "停牌成功",
    )


@router.post(
    "/{tournament_id}/hand/{hand_id}/double", response_model=TournamentActionResponse
)
@require_telegram_auth
async def double(
    request: Request,
    tournament_id: int,
    hand_id: int,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """赛内加倍。"""
    return _run_hand_action(
        blackjack_service.blackjack_tournament_double,
        current_user.id,
        hand_id,
        "加倍成功",
    )


@router.post(
    "/{tournament_id}/hand/{hand_id}/surrender",
    response_model=TournamentActionResponse,
)
@require_telegram_auth
async def surrender(
    request: Request,
    tournament_id: int,
    hand_id: int,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """赛内投降。"""
    return _run_hand_action(
        blackjack_service.blackjack_tournament_surrender,
        current_user.id,
        hand_id,
        "已投降",
    )
