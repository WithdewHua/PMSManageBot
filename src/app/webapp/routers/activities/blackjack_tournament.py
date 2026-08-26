"""21 点锦标赛路由

只做参数校验、权限、异常翻译与赛事推进的任务编排；业务逻辑与事务在 `db.py` 的
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

from app.config import settings
from app.databases import db
from app.databases.db_func import award_blackjack_champion_badge
from app.log import uvicorn_logger as logger
from app.utils.utils import get_user_names_from_tg_ids, send_message_by_url
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.routers.admin import check_admin_permission
from app.webapp.schemas import TelegramUser
from app.webapp.schemas.blackjack import BlackjackHandResponse
from app.webapp.schemas.blackjack_tournament import (
    TournamentActionResponse,
    TournamentAdminResponse,
    TournamentConsistencyResponse,
    TournamentCreateRequest,
    TournamentCurrentHandResponse,
    TournamentDealRequest,
    TournamentEntryResponse,
    TournamentListResponse,
    TournamentRegisterResponse,
    TournamentResponse,
    TournamentStandingRow,
    TournamentStandingsResponse,
    TournamentUpdateRequest,
)
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

router = APIRouter(prefix="/blackjack/tournament", tags=["21点锦标赛"])

# 单轮 tick 处理的赛事条数上限。达到上限会**记 error 而非静默截断**——列表按 id
# 倒序取，被截掉的恰好是最老的赛事，它们会永远开不了赛、结不了算。
_TICK_LIST_LIMIT = 100


# ============================================================
# 通知
# ============================================================


def _notify_enabled() -> bool:
    """赛事通知是否开启。"""
    return bool(db.get_blackjack_config_dict().get("tournament_notify_enabled", True))


def _group_chat_id() -> str | None:
    """群播报的 chat_id；未配置 TG_GROUP_ID 则跳过播报。

    与夺宝奇兵、大预言家、21 点现金局取同一个配置项，行为保持一致。
    """
    if getattr(settings, "TG_GROUP_ID", None):
        return str(settings.TG_GROUP_ID)
    return None


def _fmt_ts(ms: int) -> str:
    """毫秒时间戳渲染为本地时间字符串。"""
    import datetime

    return datetime.datetime.fromtimestamp(int(ms) / 1000, settings.TZ).strftime(
        "%m-%d %H:%M"
    )


async def _send_many(recipients: list, text_of, label: str) -> int:
    """逐个私聊发送，返回成功数。

    **单个收件人失败不中断同批其余**：从未与机器人建立私聊、或将其拉黑的用户会
    发送失败，不能因一人失败让其余人收不到。失败只记日志、不重试——业务结果早已
    落库，通知只是事后公示（与奖池播报同一口径）。
    """
    sent = 0
    for tg_id in recipients:
        try:
            await send_message_by_url(
                chat_id=int(tg_id), text=text_of(tg_id), parse_mode="HTML"
            )
            sent += 1
        except Exception as e:
            logger.warning(f"{label} 通知发送失败 (tg_id={tg_id}): {e}")
    return sent


def _format_created(t: dict) -> str:
    """① 赛事创建 → 群播报。带上参与入口与报名截止，让人知道怎么进、什么时候截止。"""
    return (
        f"🏆 <b>21 点锦标赛开放报名</b>\n"
        f"赛事：<b>{t['title']}</b>\n"
        f"报名费：{t['buy_in_credits']} 积分\n"
        f"起始筹码：{t['starting_chips']} · 共 {t['total_hands']} 手\n"
        f"注额区间：{t['min_bet_chips']} ~ {t['max_bet_chips']} 筹码\n"
        f"人数：{t['min_entrants']} ~ {t['max_entrants']} 人（满员即开）\n"
        f"报名截止：{_fmt_ts(t['register_deadline_ms'])}\n"
        f"完赛截止：{_fmt_ts(t['play_deadline_ms'])}\n"
        f"入口：WebApp 活动页 → 21 点锦标赛"
    )


def _format_started(t: dict) -> str:
    """② 开赛 → 私聊全部报名者。

    内容以「需完成多少手、截止到什么时候」为主——这条通知的目的就是让人及时安排
    完赛，只说「开赛了」等于没说。
    """
    return (
        f"🎬 <b>锦标赛已开赛</b>\n"
        f"赛事：<b>{t['title']}</b>\n"
        f"你的起始筹码：{t['starting_chips']}\n"
        f"需完成：<b>{t['total_hands']} 手</b>\n"
        f"完赛截止：<b>{_fmt_ts(t['play_deadline_ms'])}</b>\n"
        f"⚠️ 未打满全部手数且未被淘汰将<b>失去派奖资格</b>，请及时完赛。\n"
        f"入口：WebApp 活动页 → 21 点锦标赛"
    )


def _format_reminder(t: dict, remaining: int) -> str:
    """③ 完赛提醒 → 私聊未打满者。

    这是**公平性保障而非便利**：未打满即失去派奖资格是一条硬规则，缺少提醒会使其
    等同于静默没收报名费。故必须说清剩余手数与后果。
    """
    return (
        f"⏰ <b>锦标赛完赛提醒</b>\n"
        f"赛事：<b>{t['title']}</b>\n"
        f"你还有 <b>{remaining} 手</b>未完成\n"
        f"完赛截止：<b>{_fmt_ts(t['play_deadline_ms'])}</b>\n"
        f"⚠️ 到点仍未打满且未被淘汰的话，将失去派奖资格、报名费不退。\n"
        f"入口：WebApp 活动页 → 21 点锦标赛"
    )


def _format_result_dm(t: dict, row: dict) -> str:
    """④ 赛果 → 私聊前三名。"""
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(int(row["final_rank"] or 0), "🏅")
    prize = float(row.get("prize_credits") or 0)
    extra = (
        "\n🎖 已获得「21 点冠军勋章」（每日观看积分加成，再次夺冠可续期）"
        if int(row["final_rank"] or 0) == 1
        else ""
    )
    return (
        f"{medal} <b>锦标赛赛果</b>\n"
        f"赛事：<b>{t['title']}</b>\n"
        f"名次：<b>第 {row['final_rank']} 名</b>（{len_or_dash(t)}）\n"
        f"最终筹码：{row['chips']}\n"
        f"派奖：<b>{prize:.2f}</b> 积分{extra}"
    )


def len_or_dash(t: dict) -> str:
    """展示「N 人参赛」。单独成函数只为让上面的 f-string 不至于难读。"""
    return f"共 {t['entrant_count']} 人参赛"


def _format_result_group(t: dict, standings: list, prize_total: float) -> str:
    """④ 赛果 → 群播报。"""
    lines = [
        "🏆 <b>21 点锦标赛赛果</b>",
        f"赛事：<b>{t['title']}</b>",
        f"参赛：{t['entrant_count']} 人 · 奖池 {t['prize_pool_net']:.2f} 积分",
        "",
    ]
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    top3 = [
        row
        for row in standings
        if int(row.get("final_rank") or 0) and int(row["final_rank"]) <= 3
    ]
    names = get_user_names_from_tg_ids([row["tg_id"] for row in top3])
    for row in top3:
        rank = int(row["final_rank"])
        name = names.get(int(row["tg_id"]), str(row["tg_id"]))
        prize = float(row.get("prize_credits") or 0)
        lines.append(
            f"{medals.get(rank, '🏅')} <code>{name}</code> — "
            f"{row['chips']} 筹码 · +{prize:.2f} 积分"
        )
    lines.append("")
    lines.append(f"派奖合计 {prize_total:.2f} 积分")
    lines.append("入口：WebApp 活动页 → 21 点锦标赛")
    return "\n".join(lines)


def _format_cancelled(t: dict, refund: float) -> str:
    """⑤ 取消退款 → 私聊全部报名者。

    用户是**付过钱**的，退款必须告知，否则他只会看到「我报名的赛事消失了」。
    """
    return (
        f"↩️ <b>锦标赛已取消</b>\n"
        f"赛事：<b>{t['title']}</b>\n"
        f"原因：报名人数未达最低开赛人数（{t['min_entrants']} 人）\n"
        f"你的报名费 <b>{refund:.2f}</b> 积分已<b>全额退还</b>。"
    )


async def _broadcast_group(text: str, label: str) -> None:
    """群播报。未配置群组或通知已关闭时静默跳过。"""
    chat_id = _group_chat_id()
    if not chat_id:
        logger.info(f"TG_GROUP_ID 未配置，跳过{label}群播报")
        return
    try:
        await send_message_by_url(chat_id=chat_id, text=text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"{label}群播报失败: {e}")


async def notify_tournament_started(tournament: dict, entrants: list) -> None:
    """开赛通知。由报名请求（`BackgroundTasks`）与 tick 任务共用。"""
    if not _notify_enabled() or not entrants:
        return
    text = _format_started(tournament)
    sent = await _send_many(entrants, lambda _t: text, "开赛")
    logger.info(f"锦标赛 {tournament['id']} 开赛通知：{sent}/{len(entrants)} 人送达")


# ============================================================
# 赛事推进的 tick 任务
# ============================================================


async def _tick_registration_deadlines(now_ms: int, tournaments: list) -> None:
    """阶段一：报名截止 → 人数达标则开赛，否则取消退款。"""
    for t in tournaments:
        if now_ms < int(t["register_deadline_ms"]):
            continue
        try:
            if int(t["entrant_count"]) >= int(t["min_entrants"]):
                result = db.start_blackjack_tournament(int(t["id"]))
                if result.get("started"):
                    await notify_tournament_started(
                        result["tournament"], result["notify_entrants"]
                    )
            else:
                result = db.cancel_blackjack_tournament(int(t["id"]))
                if result.get("cancelled") and _notify_enabled():
                    tt = result["tournament"]
                    refunds = result["refunds"]
                    # 文案在循环内先渲染成字符串，**不把 lambda 留到循环外求值**：
                    # 闭包捕获的是变量而非当时的值，一旦这个 lambda 被推迟执行
                    # （比如改走 BackgroundTasks，register 端点已有先例），它会
                    # 读到下一场赛事的数据，把 A 赛事的退款通知发成 B 赛事的
                    text = _format_cancelled(tt, float(tt["buy_in_credits"]))
                    sent = await _send_many(
                        [r["tg_id"] for r in refunds],
                        lambda _tg, _text=text: _text,
                        "取消退款",
                    )
                    logger.info(
                        f"锦标赛 {t['id']} 取消退款通知：{sent}/{len(refunds)} 人送达"
                    )
        except Exception as e:
            logger.error(f"处理锦标赛报名截止失败 (id={t['id']}): {e}")


async def _tick_completion_reminders(now_ms: int, tournaments: list) -> None:
    """阶段二：完赛截止前提醒未打满者。

    去重标记是 `reminder_sent_at`，**由 DB 层在同一事务内 CAS 写入**——通知关闭时
    也照常推进它，只是不发送。若关闭时直接跳过，标记会冻结，重新打开的那一分钟会
    把积压的提醒一次性倾泻出去。
    """
    config = db.get_blackjack_config_dict()
    configured_lead_ms = int(
        float(config.get("tournament_remind_lead_hours", 6)) * 3600 * 1000
    )

    for t in tournaments:
        deadline = int(t["play_deadline_ms"])

        # 提前量要**按赛事自己的时长收敛**，不能直接用配置值：赛程比提前量还短时
        # （如 2 小时的赛事配 6 小时提前量），提醒窗口在开赛的那一刻就已成立，
        # 用户会在同一分钟收到「已开赛」和「你还有 N 手未完成」两条——后者此时
        # 毫无信息量，只是噪音，还会稀释真正临近截止时的紧迫感。
        #
        # 用 register_deadline 而非实际开赛时点作为窗口起点：赛事没有 started_at
        # 列，而 register_deadline 是**最晚**的开赛时点，故 (play - register) 是
        # 赛程的下界。满员提前开赛的话玩家只会得到更充裕的时间，提醒仍落在后半程。
        window_ms = max(0, deadline - int(t["register_deadline_ms"]))
        lead_ms = min(configured_lead_ms, window_ms // 2)

        if not (deadline - lead_ms <= now_ms < deadline):
            continue
        try:
            claimed = db.claim_tournament_reminder(int(t["id"]))
            if not claimed.get("claimed"):
                continue
            pending = claimed.get("pending") or []
            if not pending or not _notify_enabled():
                if pending:
                    logger.info(
                        f"赛事通知已关闭，跳过锦标赛 {t['id']} 的 "
                        f"{len(pending)} 条完赛提醒（去重标记已推进）"
                    )
                continue
            # 每人的剩余手数不同，故按收件人预渲染成 {tg_id: 文案}，
            # 再用默认参数把它绑进闭包——不让 lambda 捕获循环变量（见上方说明）
            texts = {
                int(p["tg_id"]): _format_reminder(t, int(p["hands_remaining"]))
                for p in pending
            }
            sent = await _send_many(
                list(texts.keys()),
                lambda tg, _texts=texts: _texts[int(tg)],
                "完赛提醒",
            )
            logger.info(f"锦标赛 {t['id']} 完赛提醒：{sent}/{len(pending)} 人送达")
        except Exception as e:
            logger.error(f"处理锦标赛完赛提醒失败 (id={t['id']}): {e}")


async def _tick_play_deadlines(now_ms: int, tournaments: list) -> None:
    """阶段三：完赛截止 → 先清场，再排名派奖。

    两阶段的顺序不可颠倒：排名要读终局筹码，而一手在局的牌意味着押注已从 chips
    扣除、赔付尚未计入，其持有者的筹码被低估。新手牌无法在两阶段之间冒出来——
    发牌端点以 `now < play_deadline_ms` 为闸门，那是个与赛事状态无关的固定时间戳。
    """
    for t in tournaments:
        if now_ms < int(t["play_deadline_ms"]):
            continue
        tid = int(t["id"])
        try:
            # 阶段一：清场。**没清干净就不能派奖**——排名会读到被低估的筹码，
            # 而派奖的 CAS 一旦触发，这一场就再也没有第二次机会了。跳过本轮，
            # 赛事仍是「进行中」，下一分钟的 tick 会重新走完整个流程
            cleared = db.force_settle_tournament_hands(tid)
            if not cleared.get("cleared"):
                continue

            # 阶段二：排名派奖。CAS 保证不会半途派奖
            result = db.settle_blackjack_tournament(tid)
            if not result.get("settled"):
                continue

            tt = result["tournament"]
            standings = result["standings"]

            # 冠军勋章。授勋失败不影响派奖——积分早已入账
            champion = result.get("champion_tg_id")
            if champion:
                try:
                    await award_blackjack_champion_badge(int(champion))
                except Exception as e:
                    logger.error(f"授予锦标赛冠军勋章失败 (tg_id={champion}): {e}")

            if not _notify_enabled():
                logger.info(f"赛事通知已关闭，跳过锦标赛 {tid} 的赛果通知")
                continue

            top3 = [
                r
                for r in standings
                if r.get("final_rank") and int(r["final_rank"]) <= 3
            ]
            # 同样按收件人预渲染并用默认参数绑定，不捕获循环变量
            texts = {int(r["tg_id"]): _format_result_dm(tt, r) for r in top3}
            await _send_many(
                list(texts.keys()),
                lambda tg, _texts=texts: _texts[int(tg)],
                "赛果",
            )
            await _broadcast_group(
                _format_result_group(tt, standings, result["prize_total"]), "赛果"
            )
        except Exception as e:
            logger.error(f"处理锦标赛完赛结算失败 (id={tid}): {e}")


async def blackjack_tournament_tick_job() -> None:
    """赛事推进：每分钟依次处理报名截止、完赛提醒、完赛结算。

    两份列表**在此一次查出**再传给各阶段：完赛提醒与完赛结算取的是同一个「进行中」
    集合，各查一次等于每分钟白跑一遍查询加一轮 ORM 水合与 JSON 解析。

    一次查出还顺带消除了「同一 tick 内开赛又结算」这条路径：阶段一新开的赛事不在
    本轮的「进行中」列表里，最早也要等下一分钟才被提醒或结算。赛程窗口有 30 分钟
    的下限（`TOURNAMENT_MIN_PLAY_WINDOW_MS`），这一分钟的延迟不改变任何结果。

    三个阶段各自 CAS 门控，单个赛事失败只记日志、不影响其余。整个任务体也吞掉
    异常——调度任务失败不应影响其他任务（项目约定）。
    """
    import time as _time

    now_ms = int(_time.time() * 1000)

    def _fetch(status: int, label: str) -> list:
        rows = db.list_blackjack_tournaments(statuses=(status,), limit=_TICK_LIST_LIMIT)
        # 截断必须出声：按 id 倒序取前 N 条，最老的赛事会永远推进不了
        if len(rows) >= _TICK_LIST_LIMIT:
            logger.error(
                f"锦标赛 tick 的「{label}」列表达到 {_TICK_LIST_LIMIT} 条上限，"
                f"更早的赛事本轮未被处理"
            )
        return rows

    try:
        registering = _fetch(db.TOURNAMENT_REGISTERING, "报名中")
        running = _fetch(db.TOURNAMENT_RUNNING, "进行中")
    except Exception as e:
        logger.error(f"锦标赛 tick 任务拉取赛事列表失败: {e}")
        return

    for phase, fn, rows in (
        ("报名截止", _tick_registration_deadlines, registering),
        ("完赛提醒", _tick_completion_reminders, running),
        ("完赛结算", _tick_play_deadlines, running),
    ):
        try:
            await fn(now_ms, rows)
        except Exception as e:
            logger.error(f"锦标赛 tick 任务的「{phase}」阶段失败: {e}")


# ============================================================
# 异常翻译
# ============================================================


def _raise_for_value_error(e: ValueError) -> None:
    """把 DB 层的 ValueError 翻译为面向用户的中文提示。"""
    msg = str(e)
    msg_l = msg.lower()

    if "blackjack disabled" in msg_l:
        raise HTTPException(status_code=400, detail="21 点活动当前未开放")
    if "tournament not found" in msg_l:
        raise HTTPException(status_code=404, detail="赛事不存在")
    if "tournament entry not found" in msg_l:
        raise HTTPException(status_code=400, detail="你未报名该赛事")
    if "already registered" in msg_l:
        raise HTTPException(status_code=400, detail="你已报名该赛事")
    if "tournament full" in msg_l:
        raise HTTPException(status_code=400, detail="报名人数已满")
    if "registration closed" in msg_l:
        raise HTTPException(status_code=400, detail="报名已截止")
    if "not open for registration" in msg_l:
        raise HTTPException(status_code=400, detail="该赛事当前不接受报名")
    if "tournament already started" in msg_l:
        raise HTTPException(status_code=400, detail="赛事已开赛，无法修改或取消")
    if "tournament not running" in msg_l:
        raise HTTPException(status_code=400, detail="赛事尚未开赛或已结束")
    if "tournament finished" in msg_l:
        raise HTTPException(status_code=400, detail="赛事已结束")
    if "all hands played" in msg_l:
        raise HTTPException(status_code=400, detail="你已打满全部手数")
    if "eliminated" in msg_l:
        raise HTTPException(status_code=400, detail="你的筹码已不足最小注，已被淘汰")
    if "insufficient chips to double" in msg_l:
        raise HTTPException(status_code=400, detail="筹码不足，无法加倍")
    if "insufficient chips" in msg_l:
        raise HTTPException(status_code=400, detail="筹码不足")
    if "insufficient credits: need" in msg_l:
        need = msg_l.split("need")[-1].strip()
        raise HTTPException(status_code=400, detail=f"积分不足，报名需 {need} 积分")
    if "insufficient credits" in msg_l:
        raise HTTPException(status_code=400, detail="积分不足")
    if "bet must be a multiple of" in msg_l:
        step = msg_l.split("of")[-1].strip()
        raise HTTPException(status_code=400, detail=f"注额须为 {step} 的整数倍")
    if "bet out of range" in msg_l:
        rng = msg.split(":")[-1].strip()
        raise HTTPException(status_code=400, detail=f"注额须在 {rng} 筹码之间")
    if "hand in progress in cash game" in msg_l:
        raise HTTPException(
            status_code=400, detail="你还有一手现金局的牌未结束，请先去 21 点打完"
        )
    if "hand in progress in tournament" in msg_l:
        raise HTTPException(
            status_code=400, detail="你在另一场锦标赛中还有一手牌未结束，请先打完"
        )
    if "hand in progress" in msg_l:
        raise HTTPException(status_code=400, detail="你还有一手牌未结束，请先完成")
    if "cannot change" in msg_l and "after entrants joined" in msg_l:
        raise HTTPException(
            status_code=400,
            detail="已有人报名，报名费与赛制参数不可再改；如需变更请先取消赛事再重建",
        )
    if "seeded_prize_credits must not decrease" in msg_l:
        raise HTTPException(
            status_code=400, detail="已有人报名，奖池补贴只能增加、不能减少"
        )
    if "play window must be at least" in msg_l:
        minutes = msg_l.split("least")[-1].split("minutes")[0].strip()
        raise HTTPException(
            status_code=400,
            detail=f"赛程过短：报名截止到完赛截止之间至少需要 {minutes} 分钟",
        )
    if "hand already finished" in msg_l:
        raise HTTPException(status_code=400, detail="该手牌已结束")
    if "not player turn" in msg_l:
        raise HTTPException(status_code=400, detail="当前不是你的回合")
    if "already doubled" in msg_l:
        raise HTTPException(status_code=400, detail="本手牌已加倍，不能重复加倍")
    if "cannot double after hit" in msg_l:
        raise HTTPException(status_code=400, detail="已要牌，不能再加倍")
    if "surrender disabled" in msg_l:
        raise HTTPException(status_code=400, detail="本赛事未开放投降")
    if "cannot surrender now" in msg_l:
        raise HTTPException(status_code=400, detail="当前不可投降")
    if "deal too frequent" in msg_l:
        raise HTTPException(status_code=429, detail="操作过于频繁，请稍后再试")
    if "hand not found" in msg_l:
        raise HTTPException(status_code=404, detail="手牌不存在")
    if "user stats not found" in msg_l:
        raise HTTPException(status_code=400, detail="用户积分信息不存在")
    if "tournament title required" in msg_l:
        # 只有修改路径会走到这里：创建时留空会被自动命名兜住
        raise HTTPException(status_code=400, detail="赛事名称不能为空")
    if "register deadline must be in the future" in msg_l:
        raise HTTPException(status_code=400, detail="报名截止时点须晚于当前时间")
    if "must not exceed" in msg_l or "must be" in msg_l or "invalid" in msg_l:
        raise HTTPException(status_code=400, detail=f"参数不合法：{msg}")

    raise HTTPException(status_code=400, detail=msg)


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


# ============================================================
# 玩家端点
# ============================================================


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
            db.TOURNAMENT_REGISTERING,
            db.TOURNAMENT_RUNNING,
            db.TOURNAMENT_SETTLED,
            db.TOURNAMENT_CANCELLED,
        )
        if include_finished
        else None
    )
    tournaments = db.list_blackjack_tournaments(
        tg_id=current_user.id,
        statuses=statuses,
        limit=40 if include_finished else 20,
    )
    return TournamentListResponse(
        success=True,
        tournaments=[TournamentResponse.from_tournament(t) for t in tournaments],
    )


@router.get("/{tournament_id}", response_model=TournamentResponse)
@require_telegram_auth
async def get_tournament(
    request: Request,
    tournament_id: int,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """赛事详情。"""
    t = db.get_blackjack_tournament(int(tournament_id), tg_id=current_user.id)
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
    t = db.get_blackjack_tournament(int(tournament_id))
    if not t:
        raise HTTPException(status_code=404, detail="赛事不存在")
    rows = db.get_blackjack_tournament_standings(int(tournament_id))
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
        result = db.register_blackjack_tournament(current_user.id, int(tournament_id))
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
        current_credits=float(db.get_user_credits(current_user.id) or 0),
    )


@router.get("/{tournament_id}/current", response_model=TournamentCurrentHandResponse)
@require_telegram_auth
async def get_current(
    request: Request,
    tournament_id: int,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """赛内当前手牌与筹码状态，供恢复牌桌用。"""
    t = db.get_blackjack_tournament(int(tournament_id), tg_id=current_user.id)
    if not t:
        raise HTTPException(status_code=404, detail="赛事不存在")
    entry = t.get("my_entry")
    if not entry:
        raise HTTPException(status_code=400, detail="你未报名该赛事")

    # 先清掉该用户已超时的手牌，避免返回一手早该结算的牌
    db.sweep_timed_out_blackjack_hands(tg_id=current_user.id)
    entry = db.get_user_blackjack_tournament_entry(current_user.id, int(tournament_id))

    hand = db.get_current_blackjack_hand(current_user.id)
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
        result = db.create_blackjack_tournament_hand(
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


def _schedule_tournament_hand_timeout(result: dict) -> None:
    """为新发出的赛内手牌安排超时任务。

    复用现金局那套持久化 date 任务（三层保障：date 任务 / 重启恢复 / 定时全量
    兜底），结算时走哪个适配层由 `_settle_blackjack_hand_dispatch` 按
    `tournament_id` 分派，故此处无需区分。

    时限从手牌自己的快照读（发牌时已从赛事固化到手牌行上），不回查赛事。
    """
    if result.get("settled"):
        return
    try:
        from app.webapp.routers.activities.blackjack import (
            _schedule_blackjack_timeout,
        )

        _schedule_blackjack_timeout(
            hand_id=int(result["hand"]["id"]),
            timeout_minutes=float(result["hand"]["hand_timeout_minutes"]),
        )
    except Exception as e:
        logger.error(f"安排赛内手牌超时任务失败: {e}")


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
        db.blackjack_tournament_hit, current_user.id, hand_id, "要牌成功"
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
        db.blackjack_tournament_stand, current_user.id, hand_id, "停牌成功"
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
        db.blackjack_tournament_double, current_user.id, hand_id, "加倍成功"
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
        db.blackjack_tournament_surrender, current_user.id, hand_id, "已投降"
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
        t = db.create_blackjack_tournament(
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
        t = db.update_blackjack_tournament(
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
        result = db.cancel_blackjack_tournament(
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
    result = db.check_blackjack_tournament_consistency(int(tournament_id))
    if not result:
        raise HTTPException(status_code=404, detail="赛事不存在")
    return TournamentConsistencyResponse(success=True, **result)
