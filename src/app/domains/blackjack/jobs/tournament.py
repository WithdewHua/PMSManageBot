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

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.databases import db
from app.databases.db_func import award_blackjack_champion_badge
from app.domains.blackjack.notifications.tournament import (
    _broadcast_group,
    _format_cancelled,
    _format_created,
    _format_reminder,
    _format_result_dm,
    _format_result_group,
    _notify_enabled,
    _send_many,
    notify_tournament_started,
)

# router declaration belongs to the HTTP assembly(prefix="/blackjack/tournament", tags=["21点锦标赛"])

# 单轮 tick 处理的赛事条数上限。达到上限会**记 error 而非静默截断**——列表按 id
# 倒序取，被截掉的恰好是最老的赛事，它们会永远开不了赛、结不了算。
_TICK_LIST_LIMIT = 100


# ============================================================
# 通知
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
    """阶段三：完赛截止或全员终态 → 先清场，再排名派奖。

    闸门是「截止已到 **或** 已无进行中报名」。只要还有人处于 `ENTRY_PLAYING`
    且截止未到，本场保持进行中。资格门仍只在结算里生效，不在这里提前筛人。

    两阶段的顺序不可颠倒：排名要读终局筹码，而一手在局的牌意味着押注已从 chips
    扣除、赔付尚未计入，其持有者的筹码被低估。全员终态时清场几乎总是空转
    （报名终态写在手牌结算之后），但仍必须先跑——带着未终结手牌排名是
    不可恢复的。不清干净不派奖，下一分钟重试。
    """
    if not tournaments:
        return

    still_playing = db.list_blackjack_tournaments_with_playing_entries(
        [int(t["id"]) for t in tournaments]
    )
    # 查询失败按「本轮每场都仍有进行中报名」处理：提前完赛关掉，
    # 截止已到的赛事仍走清场 → 派奖。不得把失败当成空集。
    if still_playing is None:
        still_playing = {int(t["id"]) for t in tournaments}

    for t in tournaments:
        tid = int(t["id"])
        if now_ms < int(t["play_deadline_ms"]) and tid in still_playing:
            continue
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


async def auto_create_blackjack_tournament_job() -> None:
    """每周一 09:00 自动创建周赛（cron 注册在 main.py）。

    两个截止时点在函数内按「本周的星期几」对齐计算而非取相对偏移：任务若因
    重启补跑或手动触发而晚于整点，截止仍应对齐周三 18:00 / 周日 23:59，
    而不是随实际触发时刻漂移。

    赛制参数取全局配置的 `tournament_defaults`（与管理员表单预填同源）；
    名称留空走自动命名；`seeded_prize_credits` 刻意剔除——奖池补贴按约定
    必须是管理员的显式操作，不能经定时任务增发。

    去重闸门见 `count_registering_blackjack_tournaments`：已有报名未截止的
    赛事（上一轮自动建的，或管理员手动建的）就跳过，防止重复开赛。任务体
    吞掉异常——调度任务失败不应影响其他任务（项目约定）。
    """
    import datetime as _datetime

    try:
        config = db.get_blackjack_config_dict()
        if not config.get("tournament_auto_create_enabled", False):
            logger.info("锦标赛自动开赛未开启，跳过本周自动创建")
            return
        if not config.get("enabled", False):
            logger.info("21 点活动当前未开放，跳过本周锦标赛自动创建")
            return

        now = _datetime.datetime.now(settings.TZ)
        monday = (now - _datetime.timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        register_deadline = monday + _datetime.timedelta(days=2, hours=18)  # 周三 18:00
        play_deadline = monday + _datetime.timedelta(
            days=6, hours=23, minutes=59
        )  # 周日 23:59

        now_ms = int(now.timestamp() * 1000)
        open_count = db.count_registering_blackjack_tournaments(now_ms)
        if open_count is None:
            logger.error("无法确认本周是否已有报名中的锦标赛，跳过自动创建")
            return
        if open_count > 0:
            logger.info(f"已有 {open_count} 场报名中的锦标赛，跳过本周自动创建")
            return

        params = {
            **(config.get("tournament_defaults") or {}),
            "register_deadline_ms": int(register_deadline.timestamp() * 1000),
            "play_deadline_ms": int(play_deadline.timestamp() * 1000),
        }
        params.pop("title", None)
        params.pop("seeded_prize_credits", None)

        t = db.create_blackjack_tournament(params)
        logger.info(f"已自动创建本周锦标赛：{t['title']} (id={t['id']})")

        if _notify_enabled():
            await _broadcast_group(_format_created(t), "赛事创建")
    except ValueError as e:
        # 参数被拒：如 tournament_defaults 被改非法，或创建瞬间活动被关闭
        logger.error(f"自动创建锦标赛失败（参数校验未过）: {e}")
    except Exception as e:
        logger.error(f"自动创建锦标赛失败: {e}")


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
        from app.domains.blackjack.jobs.cash import (
            _schedule_blackjack_timeout,
        )

        _schedule_blackjack_timeout(
            hand_id=int(result["hand"]["id"]),
            timeout_minutes=float(result["hand"]["hand_timeout_minutes"]),
        )
    except Exception as e:
        logger.error(f"安排赛内手牌超时任务失败: {e}")
