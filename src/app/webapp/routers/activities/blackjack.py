"""21 点活动路由

只做参数校验、权限、异常翻译与超时任务编排；业务逻辑与事务在 `db.py` 的
`blackjack_*` 方法里，规则判定在 `blackjack_engine.py`。

响应一律经 `BlackjackHandResponse.from_hand()` 构造，庄家暗牌与随机种子的过滤
落在该构造入口，不在本模块逐处 if 判断（设计决策 10）。
"""

import json

from app.config import settings
from app.databases import db
from app.databases.db_func import check_and_award_game_king_badge
from app.log import uvicorn_logger as logger
from app.utils.utils import get_user_name_from_tg_id
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.routers.admin import check_admin_permission
from app.webapp.schemas import TelegramUser
from app.webapp.schemas.blackjack import (
    BlackjackActionResponse,
    BlackjackAdminConfig,
    BlackjackAdminStatsResponse,
    BlackjackConfigUpdateRequest,
    BlackjackCurrentHandResponse,
    BlackjackDealRequest,
    BlackjackDecisionFeedback,
    BlackjackHandResponse,
    BlackjackJackpotSeedRequest,
    BlackjackPublicConfigResponse,
    BlackjackUserStatsResponse,
)
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

router = APIRouter(prefix="/blackjack", tags=["21点"])


async def _settle_blackjack_hand_on_timeout(*, hand_id: int) -> None:
    """超时兜底任务体：把手牌按停牌口径结算。

    异常只记日志、不抛出——调度任务失败不应影响其他任务，且惰性清理会在用户
    下次发牌时兜住漏掉的手牌（设计决策 7）。
    """
    try:
        result = db.settle_blackjack_hand_by_timeout(int(hand_id))
        if result.get("already_settled"):
            logger.info(f"Blackjack timeout: hand {hand_id} already settled; skip")
        else:
            logger.info(
                f"Blackjack timeout settled: hand={hand_id} "
                f"outcome={result.get('outcome')} payout={result.get('payout_credits')}"
            )
    except Exception as e:
        logger.error(f"Blackjack timeout settle failed (hand={hand_id}): {e}")


def _schedule_blackjack_timeout(*, hand_id: int, timeout_minutes: float) -> None:
    """安排手牌的超时结算任务。

    用持久化 jobstore，服务重启不丢（spec：超时任务 SHALL 持久化）。

    时限按**秒**换算而非 `int(分钟)`：重启后重建任务时传入的是剩余时间（小数
    分钟），取整会把 14.9 分钟压成 14 分钟，任务提前 54 秒触发，玩家还在思考
    时手牌就被按停牌结算，下一次要牌只会得到「该手牌已结束」。

    `misfire_grace_time=None` 表示不设错过窗口：调度器全局默认只有 60 秒，
    一次超过一分钟的重启就会让 APScheduler 判定任务错过而**永久丢弃**它，
    手牌将带着已扣的押注长期悬挂。配合 `restore_blackjack_timeouts()`（启动时
    重建任务）与 `sweep_expired_blackjack_hands_job()`（定时全量兜底），三者
    共同满足 spec 的「服务重启 SHALL NOT 导致待处置的手牌被遗漏」。
    """
    try:
        from datetime import datetime, timedelta

        from app.scheduler import Scheduler

        run_date = datetime.now(settings.TZ) + timedelta(
            seconds=float(timeout_minutes) * 60.0
        )
        Scheduler().add_async_job(
            func=_settle_blackjack_hand_on_timeout,
            trigger="date",
            id=f"blackjack_timeout_{int(hand_id)}",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=None,
            run_date=run_date,
            kwargs={"hand_id": int(hand_id)},
            jobstore="sqlalchemy",
        )
        logger.info(
            f"Blackjack timeout scheduled: hand={hand_id}, minutes={timeout_minutes}"
        )
    except Exception as e:
        logger.error(f"Blackjack timeout schedule failed (hand={hand_id}): {e}")


def restore_blackjack_timeouts() -> None:
    """启动时为仍在进行中的手牌重建超时任务。

    照 `auction.restore_auction_schedules()` 的做法。已过期的手牌不在此处理，
    交由定时兜底任务立即清掉，避免启动阶段做重活。
    """
    try:
        import time as _time

        restored = 0
        expired = 0
        now_ms = int(_time.time() * 1000)

        for hand in db.list_active_blackjack_hands():
            deadline_ms = (
                int(hand["created_at_ms"])
                + int(hand["hand_timeout_minutes"]) * 60 * 1000
            )
            if deadline_ms <= now_ms:
                expired += 1
                continue
            remaining_minutes = max(0.0, (deadline_ms - now_ms) / 60000.0)
            _schedule_blackjack_timeout(
                hand_id=int(hand["id"]), timeout_minutes=remaining_minutes
            )
            restored += 1

        logger.info(
            f"已恢复 {restored} 手 21 点手牌的超时任务，另有 {expired} 手已过期待兜底清理"
        )
    except Exception as e:
        logger.error(f"恢复 21 点超时任务失败: {e}")


async def sweep_expired_blackjack_hands_job() -> None:
    """定时兜底：全量结算已超时的手牌。

    覆盖调度任务因任何原因丢失的情形——按用户的惰性清理只在该用户自己再次操作
    时触发，若用户再也不回来，手牌会永久悬挂、押注不退。
    """
    try:
        swept = db.sweep_timed_out_blackjack_hands()
        if swept:
            logger.info(f"21 点兜底清理：结算了 {swept} 手超时手牌")
    except Exception as e:
        logger.error(f"21 点兜底清理失败: {e}")


def _get_group_chat_id() -> str | None:
    """群组播报的 chat_id；未配置 TG_GROUP_ID 则跳过播报。

    与夺宝奇兵、大预言家取同一个配置项，行为保持一致。
    """
    if getattr(settings, "TG_GROUP_ID", None):
        return str(settings.TG_GROUP_ID)
    return None


def _format_jackpot_win(win: dict, jackpot_balance: float) -> str:
    """把一条中奖记录渲染成群播报文案。

    刻意带上牌面：只报金额的话，奖池空虚期会出现「赢得 0.4 积分」这种毫无
    说服力的播报；牌面本身（同花天胡、三张 7）才是真正稀有的部分。稀有度不
    另注明触发频率——那是给管理员判断播报频次用的（见管理面板），播到群里
    只会让报喜的消息读着像说明书。

    余额由调用方查好传入——本函数会被逐条调用，在此处查库等于每条消息各开
    一次会话去读同一个值。
    """
    name = get_user_name_from_tg_id(win["tg_id"])
    cards = " ".join(win.get("player_cards") or [])
    amount = float(win.get("jackpot_won") or 0)

    if win.get("triple_seven"):
        headline = "🎰 <b>三张 7！幸运奖池被通吃</b>"
    else:
        headline = "🃏 <b>同花天胡！命中幸运奖池</b>"

    return (
        f"{headline}\n"
        f"玩家：<code>{name}</code>\n"
        f"牌面：{cards}\n"
        f"奖池派彩：<b>{amount:.2f}</b> 积分\n"
        f"当前奖池：{jackpot_balance:.2f} 积分\n"
        f"入口：WebApp 活动页 → 21 点"
    )


async def notify_blackjack_jackpot_wins_job() -> None:
    """把新产生的奖池中奖播报到群里。

    走游标轮询而非在各结算路径挂钩子——理由见 `db.JACKPOT_NOTIFY_CURSOR_KEY`
    的注释。认领即视为已播报，故发送失败只记日志、不重播，避免刷屏。
    """
    try:
        config = db.get_blackjack_config_dict()
        chat_id = _get_group_chat_id()

        # 关闭播报与未配置群组是同一件事：都**照常认领并推进游标**，只是不发送。
        # 若关闭时直接 return，游标会冻结，积压的中奖会在管理员重新打开的那一分钟
        # 一次性倾泻到群里——关掉播报两周再打开就是几十条连发。
        if not config.get("jackpot_notify_enabled", True) or not chat_id:
            claimed = db.claim_unannounced_jackpot_wins()
            if claimed:
                reason = (
                    "播报已关闭"
                    if not config.get("jackpot_notify_enabled", True)
                    else "TG_GROUP_ID 未配置"
                )
                logger.info(
                    f"{reason}，跳过 {len(claimed)} 条 21 点奖池中奖播报（游标已推进）"
                )
            return

        wins = db.claim_unannounced_jackpot_wins()
        if not wins:
            return

        from app.utils.utils import send_message_by_url

        # 余额对本批所有消息都一样，查一次即可，不要每条消息各开一次会话
        jackpot_balance = db.get_blackjack_jackpot()

        for win in wins:
            try:
                await send_message_by_url(
                    chat_id=chat_id,
                    text=_format_jackpot_win(win, jackpot_balance),
                    parse_mode="HTML",
                )
                logger.info(
                    f"已播报 21 点奖池中奖：hand={win['hand_id']} "
                    f"tg_id={win['tg_id']} amount={win['jackpot_won']}"
                )
            except Exception as e:
                logger.error(f"播报 21 点奖池中奖失败 (hand={win['hand_id']}): {e}")
    except Exception as e:
        logger.error(f"21 点奖池中奖播报任务失败: {e}")


def _raise_for_value_error(e: ValueError) -> None:
    """把 DB 层的 ValueError 翻译为面向用户的中文提示。"""
    msg = str(e)
    msg_l = msg.lower()

    if "blackjack disabled" in msg_l:
        raise HTTPException(status_code=400, detail="21 点活动当前未开放")
    if "invalid bet" in msg_l:
        options = db.get_blackjack_config_dict().get("bet_options") or []
        raise HTTPException(
            status_code=400,
            detail=f"注额不合法，可选档位为 {'、'.join(str(b) for b in options)}",
        )
    if "insufficient credits to double" in msg_l:
        raise HTTPException(status_code=400, detail="积分不足，无法加倍")
    if "insufficient credits: need" in msg_l:
        need = msg_l.split("need")[-1].strip()
        raise HTTPException(status_code=400, detail=f"积分不足，参与需至少 {need} 积分")
    if "insufficient credits" in msg_l:
        raise HTTPException(status_code=400, detail="积分不足")
    if "hand in progress in tournament" in msg_l:
        # 必须比下一条更早匹配：现金局的 /current 看不到赛内手牌，只说「你还有
        # 一手牌未结束」等于让用户在现金局界面里找一张永远找不到的牌
        raise HTTPException(
            status_code=400,
            detail="你在锦标赛中还有一手牌未结束，请先到锦标赛里打完",
        )
    if "hand in progress" in msg_l:
        raise HTTPException(status_code=400, detail="你还有一手牌未结束，请先完成")
    if "hand already finished" in msg_l:
        raise HTTPException(status_code=400, detail="该手牌已结束")
    if "not player turn" in msg_l:
        raise HTTPException(status_code=400, detail="当前不是你的回合")
    if "already doubled" in msg_l:
        raise HTTPException(status_code=400, detail="本手牌已加倍，不能重复加倍")
    if "cannot double after hit" in msg_l:
        raise HTTPException(status_code=400, detail="已要牌，不能再加倍")
    if "surrender disabled" in msg_l:
        raise HTTPException(status_code=400, detail="投降当前未开放")
    if "cannot surrender after hit" in msg_l:
        raise HTTPException(status_code=400, detail="已要牌，不能再投降")
    if "cannot surrender after double" in msg_l:
        raise HTTPException(status_code=400, detail="已加倍，不能再投降")
    if "deal too frequent" in msg_l:
        raise HTTPException(status_code=429, detail="操作过于频繁，请稍后再试")
    if "hand not found" in msg_l:
        raise HTTPException(status_code=404, detail="手牌不存在")
    if "user stats not found" in msg_l:
        raise HTTPException(status_code=400, detail="用户积分信息不存在")
    if "deck exhausted" in msg_l or "牌靴已耗尽" in msg:
        raise HTTPException(status_code=500, detail="牌靴异常，请联系管理员")

    raise HTTPException(status_code=400, detail=msg)


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
        current_credits=float(db.get_user_credits(tg_id) or 0),
        decision=BlackjackDecisionFeedback(**decision) if decision else None,
        jackpot_balance=db.get_blackjack_jackpot(),
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
        result = db.create_blackjack_hand(
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
        result = db.blackjack_hit(tg_id=int(current_user.id), hand_id=int(hand_id))
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
        result = db.blackjack_stand(tg_id=int(current_user.id), hand_id=int(hand_id))
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
        result = db.blackjack_double(tg_id=int(current_user.id), hand_id=int(hand_id))
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
        result = db.blackjack_surrender(
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
        hand = db.get_current_blackjack_hand(tg_id=int(current_user.id))
        if hand and hand.get("tournament_id") is not None:
            hand = None
        return BlackjackCurrentHandResponse(
            hand=BlackjackHandResponse.from_hand(hand) if hand else None,
            current_credits=float(db.get_user_credits(int(current_user.id)) or 0),
            jackpot_balance=db.get_blackjack_jackpot(),
            free_hands_remaining=db.get_blackjack_free_hands_remaining(
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
        stats = db.get_user_blackjack_stats(tg_id=int(current_user.id))
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
        config = db.get_blackjack_config_dict()
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
            jackpot_balance=db.get_blackjack_jackpot(),
            jackpot_suited_bj_pct=float(config.get("jackpot_suited_bj_pct", 10)),
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
        config = db.get_blackjack_config_dict()
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

        if not db.set_blackjack_config(
            "config", json.dumps(config, ensure_ascii=False)
        ):
            raise HTTPException(status_code=500, detail="保存配置失败")

        return BlackjackAdminConfig(**db.get_blackjack_config_dict())
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
        balance = db.seed_blackjack_jackpot(float(data.amount))
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
        return BlackjackAdminStatsResponse(**db.get_blackjack_admin_stats())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 21 点运营统计失败: {e}")
        raise HTTPException(status_code=500, detail="获取统计失败")
