import datetime

from app.core import events
from app.core.config import settings
from app.core.log import logger, uvicorn_logger
from app.domains.badges import service as badges_service
from app.domains.blackjack import events as blackjack_events
from app.domains.blackjack import repository as blackjack_repository
from app.domains.blackjack.config import (
    TOURNAMENT_REGISTERING,
    TOURNAMENT_RUNNING,
)
from app.domains.blackjack.notifications.tournament import (
    _broadcast_group,
    _format_cancelled,
    _format_created,
    _format_reminder,
    _format_result_dm,
    _format_result_group,
    _send_many,
    notify_tournament_started,
)
from app.domains.blackjack.repository import analytics as blackjack_analytics
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.luckywheel import service as luckywheel_service
from app.domains.luckywheel.types import FreeSpinProgress


async def award_blackjack_champion_badge(tg_id: int) -> dict | None:
    """给锦标赛冠军授予/续期「21 点冠军」勋章。

    照 `game_king` 的形状：勋章不存在时**自动创建**，故本变更不需要预置数据或
    数据迁移。`credits_cost=0` 且 `is_enabled=0` —— 仅由系统授予，不可用积分兑换。

    与 `game_king` 的关键区别是**再次夺冠要续期而非跳过**：`game_king` 是一次性
    成就，而冠军是可以反复拿的，若沿用「有则跳过」，连庄的人第二次夺冠什么都得
    不到。续期语义见 `badges_service.award_or_renew_badge`。

    加成 5% 每日观看积分、30 天有效期，上限由配置的 `tournament_badge_cap_days`
    给出。**这是一条增发路径**（约 0.4 积分/天/人），量级相对大转盘的回收可忽略，
    但仍在此显式记账。

    Returns: 授予结果 dict，失败返回 None。
    """
    from app.domains.blackjack.config import (
        CHAMPION_BADGE_BONUS,
        CHAMPION_BADGE_TYPE,
        CHAMPION_BADGE_VALID_DAYS,
    )

    try:
        badge_info = badges_service.get_badge_by_type(CHAMPION_BADGE_TYPE)
        if not badge_info:
            logger.info(f"勋章 '{CHAMPION_BADGE_TYPE}' 不存在，正在创建...")
            badge_info = badges_service.create_badge(
                badge_type=CHAMPION_BADGE_TYPE,
                name="21 点冠军勋章",
                description=(
                    "此勋章授予 21 点锦标赛的冠军："
                    f"持有永久，每日观看积分 +{int(CHAMPION_BADGE_BONUS * 100)}%，"
                    f"加成有效期 {CHAMPION_BADGE_VALID_DAYS} 天，再次夺冠可续期"
                ),
                icon_url="/badges/blackjack_champion.svg",
                credits_cost=0,
                bonus_percentage=CHAMPION_BADGE_BONUS,
                valid_days=CHAMPION_BADGE_VALID_DAYS,
                is_enabled=0,  # 禁用兑换，仅由系统授予
            )
            if not badge_info:
                logger.error("创建 21 点冠军勋章失败")
                return None

        config = blackjack_repository.get_blackjack_config_dict()
        cap_days = int(config.get("tournament_badge_cap_days", 90))
        valid_days = int(badge_info.get("valid_days", CHAMPION_BADGE_VALID_DAYS))

        result = badges_service.award_or_renew_badge(
            tg_id=int(tg_id),
            badge_id=int(badge_info["id"]),
            valid_days=valid_days,
            cap_days=cap_days,
        )
        if result.get("awarded"):
            logger.info(f"已向用户 {tg_id} 授予 21 点冠军勋章")
        elif result.get("renewed"):
            logger.info(
                f"用户 {tg_id} 的 21 点冠军勋章加成已续期至 {result['expires_at']}"
            )
        return result
    except Exception as e:
        logger.error(f"授予 21 点冠军勋章失败 (tg_id={tg_id}): {e}")
        return None


def get_blackjack_config_dict() -> dict:
    return blackjack_repository.get_blackjack_config_dict()


def free_spin_progress(tg_id: int) -> FreeSpinProgress:
    return blackjack_repository.free_spin_progress(tg_id)


def get_current_credits(tg_id: int) -> float:
    return float(credits_service.read_optional(CreditAccount.tg(int(tg_id))) or 0)


def get_blackjack_skill_ranks(min_hands: int | None = None) -> dict:
    return blackjack_analytics.get_blackjack_skill_ranks(min_hands)


def get_blackjack_max_win_rank() -> list:
    return blackjack_analytics.get_blackjack_max_win_rank()


def get_user_blackjack_stats(tg_id: int) -> dict:
    return blackjack_repository.get_user_blackjack_stats(tg_id)


def cash_hand_metrics_tx(
    session,
    tg_id: int,
    since: int,
    until: int,
    *,
    min_bet: float | None = None,
    min_accuracy: float | None = None,
) -> int | tuple[int, float]:
    return blackjack_analytics.cash_hand_metrics_tx(
        session,
        tg_id,
        since,
        until,
        min_bet=min_bet,
        min_accuracy=min_accuracy,
    )


def count_tournament_entries_tx(session, tg_id: int, since: int, until: int) -> int:
    return blackjack_analytics.count_tournament_entries_tx(session, tg_id, since, until)


def get_game_king_eligible_tg_ids_tx(
    session, min_hands: int, min_accuracy: float
) -> list[int]:
    return blackjack_analytics.get_game_king_eligible_tg_ids_tx(
        session, min_hands, min_accuracy
    )


def get_blackjack_jackpot() -> float:
    return blackjack_repository.get_blackjack_jackpot()


def seed_blackjack_jackpot(amount: float) -> float:
    return blackjack_repository.seed_blackjack_jackpot(amount)


def get_blackjack_free_hands_remaining(tg_id: int) -> int:
    return blackjack_repository.get_blackjack_free_hands_remaining(tg_id)


def get_current_blackjack_hand(tg_id: int) -> dict | None:
    return blackjack_repository.get_current_blackjack_hand(tg_id)


def list_active_blackjack_hands() -> list[dict]:
    return blackjack_repository.list_active_blackjack_hands()


def get_blackjack_admin_stats() -> dict:
    return blackjack_repository.get_blackjack_admin_stats()


def set_blackjack_config(config_key: str, config_json: str) -> bool:
    return blackjack_repository.set_blackjack_config(config_key, config_json)


def create_blackjack_hand(tg_id: int, bet_credits: int) -> dict:
    result = blackjack_repository.create_blackjack_hand(tg_id, bet_credits)
    if result.get("settled"):
        events.emit(blackjack_events.CashHandPlayed(int(tg_id)))
    return result


def blackjack_hit(tg_id: int, hand_id: int) -> dict:
    result = blackjack_repository.blackjack_hit(tg_id, hand_id)
    if result.get("settled"):
        events.emit(blackjack_events.CashHandPlayed(int(tg_id)))
    return result


def blackjack_stand(tg_id: int, hand_id: int) -> dict:
    result = blackjack_repository.blackjack_stand(tg_id, hand_id)
    events.emit(blackjack_events.CashHandPlayed(int(tg_id)))
    return result


def blackjack_double(tg_id: int, hand_id: int) -> dict:
    result = blackjack_repository.blackjack_double(tg_id, hand_id)
    events.emit(blackjack_events.CashHandPlayed(int(tg_id)))
    return result


def blackjack_surrender(tg_id: int, hand_id: int) -> dict:
    result = blackjack_repository.blackjack_surrender(tg_id, hand_id)
    events.emit(blackjack_events.CashHandPlayed(int(tg_id)))
    return result


def settle_blackjack_hand_by_timeout(hand_id: int) -> dict:
    return blackjack_repository.settle_blackjack_hand_by_timeout(hand_id)


def sweep_timed_out_blackjack_hands(tg_id: int | None = None) -> int:
    return blackjack_repository.sweep_timed_out_blackjack_hands(tg_id)


def settle_blackjack_weekly_cashback() -> dict:
    return blackjack_repository.settle_blackjack_weekly_cashback()


def claim_unannounced_jackpot_wins() -> list[dict]:
    return blackjack_repository.claim_unannounced_jackpot_wins()


def claim_unnotified_blackjack_freespins() -> list:
    return luckywheel_service.claim_unnotified_blackjack_freespins()


def list_expiring_blackjack_freespins(*, within_ms: int = 86400 * 1000) -> list[dict]:
    return luckywheel_service.list_expiring_blackjack_freespins(within_ms=within_ms)


def get_blackjack_freespin_summary(tg_id: int) -> dict:
    return luckywheel_service.free_spin_summary(tg_id)


def consume_blackjack_freespin(tg_id: int) -> dict | None:
    return luckywheel_service.consume_free_spin(tg_id)


def release_blackjack_freespin(spin_id: int, *, claimed_at_ms: int) -> bool:
    return luckywheel_service.release_free_spin(spin_id, claimed_at_ms=claimed_at_ms)


def get_blackjack_tournament_wallet(tg_id: int) -> float:
    return blackjack_repository.get_blackjack_tournament_wallet(tg_id)


def get_blackjack_tournament(
    tournament_id: int, tg_id: int | None = None
) -> dict | None:
    return blackjack_repository.get_blackjack_tournament(tournament_id, tg_id)


def list_blackjack_tournaments(
    tg_id: int | None = None,
    statuses: tuple | None = None,
    limit: int = 20,
) -> list[dict]:
    return blackjack_repository.list_blackjack_tournaments(tg_id, statuses, limit)


def list_blackjack_tournaments_with_playing_entries(
    tournament_ids: list[int],
) -> list[dict] | set[int] | None:
    return blackjack_repository.list_blackjack_tournaments_with_playing_entries(
        tournament_ids
    )


def count_registering_blackjack_tournaments(now_ms: int) -> int | None:
    return blackjack_repository.count_registering_blackjack_tournaments(now_ms)


def get_blackjack_tournament_standings(tournament_id: int) -> list[dict]:
    return blackjack_repository.get_blackjack_tournament_standings(tournament_id)


def get_user_blackjack_tournament_entry(tg_id: int, tournament_id: int) -> dict | None:
    return blackjack_repository.get_user_blackjack_tournament_entry(
        tg_id, tournament_id
    )


def create_blackjack_tournament(params: dict, created_by: int | None = None) -> dict:
    return blackjack_repository.create_blackjack_tournament(params, created_by)


def update_blackjack_tournament(tournament_id: int, params: dict) -> dict:
    return blackjack_repository.update_blackjack_tournament(tournament_id, params)


def register_blackjack_tournament(tg_id: int, tournament_id: int) -> dict:
    return blackjack_repository.register_blackjack_tournament(tg_id, tournament_id)


def start_blackjack_tournament(tournament_id: int) -> dict:
    return blackjack_repository.start_blackjack_tournament(tournament_id)


def cancel_blackjack_tournament(
    tournament_id: int, reason: str = "insufficient_entrants"
) -> dict:
    return blackjack_repository.cancel_blackjack_tournament(tournament_id, reason)


def claim_tournament_reminder(tournament_id: int) -> dict:
    return blackjack_repository.claim_tournament_reminder(tournament_id)


def create_blackjack_tournament_hand(
    tg_id: int, tournament_id: int, bet_chips: int
) -> dict:
    return blackjack_repository.create_blackjack_tournament_hand(
        tg_id, tournament_id, bet_chips
    )


def blackjack_tournament_hit(tg_id: int, hand_id: int) -> dict:
    return blackjack_repository.blackjack_tournament_hit(tg_id, hand_id)


def blackjack_tournament_stand(tg_id: int, hand_id: int) -> dict:
    return blackjack_repository.blackjack_tournament_stand(tg_id, hand_id)


def blackjack_tournament_double(tg_id: int, hand_id: int) -> dict:
    return blackjack_repository.blackjack_tournament_double(tg_id, hand_id)


def blackjack_tournament_surrender(tg_id: int, hand_id: int) -> dict:
    return blackjack_repository.blackjack_tournament_surrender(tg_id, hand_id)


def force_settle_tournament_hands(tournament_id: int) -> dict:
    return blackjack_repository.force_settle_tournament_hands(tournament_id)


def settle_blackjack_tournament(tournament_id: int) -> dict:
    return blackjack_repository.settle_blackjack_tournament(tournament_id)


def check_blackjack_tournament_consistency(tournament_id: int) -> dict | None:
    return blackjack_repository.check_blackjack_tournament_consistency(tournament_id)


# ============================================================
# 锦标赛推进工作流（tick / 每周自动开赛）
#
# 这两个工作流原先在 `jobs/tournament.py` 里，现按 design 的层序搬到 service：
# jobs 只做「解析任务参数 → 调 service」的适配。通知一律发生在 repository
# 事务提交之后，工作流内部按阶段吞异常，单个赛事失败不影响其余赛事。
# ============================================================

# 单轮 tick 处理的赛事条数上限。达到上限会**记 error 而非静默截断**——列表按 id
# 倒序取，被截掉的恰好是最老的赛事，它们会永远开不了赛、结不了算。
_TICK_LIST_LIMIT = 100


def _notify_enabled() -> bool:
    return bool(get_blackjack_config_dict().get("tournament_notify_enabled", True))


async def _tick_registration_deadlines(now_ms: int, tournaments: list) -> None:
    """阶段一：报名截止 → 人数达标则开赛，否则取消退款。"""
    for t in tournaments:
        if now_ms < int(t["register_deadline_ms"]):
            continue
        try:
            if int(t["entrant_count"]) >= int(t["min_entrants"]):
                result = start_blackjack_tournament(int(t["id"]))
                if result.get("started"):
                    await notify_tournament_started(
                        result["tournament"],
                        result["notify_entrants"],
                        notify_enabled=_notify_enabled(),
                    )
            else:
                result = cancel_blackjack_tournament(int(t["id"]))
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
                    uvicorn_logger.info(
                        f"锦标赛 {t['id']} 取消退款通知：{sent}/{len(refunds)} 人送达"
                    )
        except Exception as e:
            uvicorn_logger.error(f"处理锦标赛报名截止失败 (id={t['id']}): {e}")


async def _tick_completion_reminders(now_ms: int, tournaments: list) -> None:
    """阶段二：完赛截止前提醒未打满者。

    去重标记是 `reminder_sent_at`，**由 DB 层在同一事务内 CAS 写入**——通知关闭时
    也照常推进它，只是不发送。若关闭时直接跳过，标记会冻结，重新打开的那一分钟会
    把积压的提醒一次性倾泻出去。
    """
    config = get_blackjack_config_dict()
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
            claimed = claim_tournament_reminder(int(t["id"]))
            if not claimed.get("claimed"):
                continue
            pending = claimed.get("pending") or []
            if not pending or not _notify_enabled():
                if pending:
                    uvicorn_logger.info(
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
            uvicorn_logger.info(
                f"锦标赛 {t['id']} 完赛提醒：{sent}/{len(pending)} 人送达"
            )
        except Exception as e:
            uvicorn_logger.error(f"处理锦标赛完赛提醒失败 (id={t['id']}): {e}")


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

    still_playing = list_blackjack_tournaments_with_playing_entries(
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
            cleared = force_settle_tournament_hands(tid)
            if not cleared.get("cleared"):
                continue

            # 阶段二：排名派奖。CAS 保证不会半途派奖
            result = settle_blackjack_tournament(tid)
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
                    uvicorn_logger.error(
                        f"授予锦标赛冠军勋章失败 (tg_id={champion}): {e}"
                    )

            if not _notify_enabled():
                uvicorn_logger.info(f"赛事通知已关闭，跳过锦标赛 {tid} 的赛果通知")
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
            uvicorn_logger.error(f"处理锦标赛完赛结算失败 (id={tid}): {e}")


async def tick_tournaments() -> None:
    """赛事推进：每分钟依次处理报名截止、完赛提醒、完赛结算。

    两份列表**在此一次查出**再传给各阶段：完赛提醒与完赛结算取的是同一个「进行中」
    集合，各查一次等于每分钟白跑一遍查询加一轮 ORM 水合与 JSON 解析。

    一次查出还顺带消除了「同一 tick 内开赛又结算」这条路径：阶段一新开的赛事不在
    本轮提前查出的 `running` 列表里，故不会在同一分钟被阶段三结算。

    三个阶段各自 CAS 门控，单个赛事失败只记日志、不影响其余。整个任务体也吞掉
    异常——调度任务失败不应影响其他任务（项目约定）。
    """
    import time as _time

    now_ms = int(_time.time() * 1000)

    def _fetch(status: int, label: str) -> list:
        rows = list_blackjack_tournaments(statuses=(status,), limit=_TICK_LIST_LIMIT)
        # 截断必须出声：按 id 倒序取前 N 条，最老的赛事会永远推进不了
        if len(rows) >= _TICK_LIST_LIMIT:
            uvicorn_logger.error(
                f"锦标赛 tick 的「{label}」列表达到 {_TICK_LIST_LIMIT} 条上限，"
                f"更早的赛事本轮未被处理"
            )
        return rows

    try:
        registering = _fetch(TOURNAMENT_REGISTERING, "报名中")
        running = _fetch(TOURNAMENT_RUNNING, "进行中")
    except Exception as e:
        uvicorn_logger.error(f"锦标赛 tick 任务拉取赛事列表失败: {e}")
        return

    for phase, fn, rows in (
        ("报名截止", _tick_registration_deadlines, registering),
        ("完赛提醒", _tick_completion_reminders, running),
        ("完赛结算", _tick_play_deadlines, running),
    ):
        try:
            await fn(now_ms, rows)
        except Exception as e:
            uvicorn_logger.error(f"锦标赛 tick 任务的「{phase}」阶段失败: {e}")


async def create_weekly_tournament() -> dict | None:
    """每周一 09:00 自动创建周赛（cron 注册在 schedule.py）。

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
    try:
        config = get_blackjack_config_dict()
        if not config.get("tournament_auto_create_enabled", False):
            uvicorn_logger.info("锦标赛自动开赛未开启，跳过本周自动创建")
            return None
        if not config.get("enabled", False):
            uvicorn_logger.info("21 点活动当前未开放，跳过本周锦标赛自动创建")
            return None

        now = datetime.datetime.now(settings.TZ)
        monday = (now - datetime.timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        register_deadline = monday + datetime.timedelta(days=2, hours=18)  # 周三 18:00
        play_deadline = monday + datetime.timedelta(
            days=6, hours=23, minutes=59
        )  # 周日 23:59

        now_ms = int(now.timestamp() * 1000)
        open_count = count_registering_blackjack_tournaments(now_ms)
        if open_count is None:
            uvicorn_logger.error("无法确认本周是否已有报名中的锦标赛，跳过自动创建")
            return None
        if open_count > 0:
            uvicorn_logger.info(f"已有 {open_count} 场报名中的锦标赛，跳过本周自动创建")
            return None

        params = {
            **(config.get("tournament_defaults") or {}),
            "register_deadline_ms": int(register_deadline.timestamp() * 1000),
            "play_deadline_ms": int(play_deadline.timestamp() * 1000),
        }
        params.pop("title", None)
        params.pop("seeded_prize_credits", None)

        t = create_blackjack_tournament(params)
        uvicorn_logger.info(f"已自动创建本周锦标赛：{t['title']} (id={t['id']})")

        if _notify_enabled():
            await _broadcast_group(_format_created(t), "赛事创建")
        return t
    except ValueError as e:
        # 参数被拒：如 tournament_defaults 被改非法，或创建瞬间活动被关闭
        uvicorn_logger.error(f"自动创建锦标赛失败（参数校验未过）: {e}")
        return None
    except Exception as e:
        uvicorn_logger.error(f"自动创建锦标赛失败: {e}")
        return None


def get_game_king_eligible_tg_ids(min_hands: int, min_accuracy: float) -> list[int]:
    return blackjack_analytics.get_game_king_eligible_tg_ids(min_hands, min_accuracy)
