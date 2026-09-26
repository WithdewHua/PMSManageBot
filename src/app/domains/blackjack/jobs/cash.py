"""21 点活动路由

只做参数校验、权限、异常翻译与超时任务编排；业务逻辑与事务在 `db.py` 的
`blackjack_*` 方法里，规则判定在 `blackjack_engine.py`。

响应一律经 `BlackjackHandResponse.from_hand()` 构造，庄家暗牌与随机种子的过滤
落在该构造入口，不在本模块逐处 if 判断（设计决策 10）。
"""

from datetime import datetime

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.databases import db
from app.domains.blackjack.notifications.cash import (
    _fmt_credits,
    _format_jackpot_win,
    _get_group_chat_id,
)
from app.utils.utils import send_message_by_url

# router declaration belongs to the HTTP assembly(prefix="/blackjack", tags=["21点"])


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

        from app.core.scheduler import Scheduler

        run_date = datetime.now(settings.TZ) + timedelta(
            seconds=float(timeout_minutes) * 60.0
        )
        Scheduler().add_async_job(
            # Keep the persisted B1 callable path until B3 migrates jobstore rows.
            func="app.webapp.routers.activities.blackjack:_settle_blackjack_hand_on_timeout",
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


async def notify_blackjack_freespin_grants_job() -> None:
    """把新发放的免费大转盘机会逐用户私信。

    走游标轮询而非在结算路径挂钩子：发放散落在全部结算路径上（含超时
    清理等不经路由的路径），只有轮询能全覆盖。认领即视为已通知，发送
    失败只记日志、不重发。发送量有界：每周每人至多周上限（5）条。
    """
    try:
        grants = db.claim_unnotified_blackjack_freespins()
        if not grants:
            return
        for grant in grants:
            expires_dt = datetime.fromtimestamp(
                grant["expires_at_ms"] / 1000, tz=settings.TZ
            )
            try:
                await send_message_by_url(
                    chat_id=int(grant["tg_id"]),
                    text=(
                        "🎁 打满手数奖励到账！\n"
                        "你获得了 <b>1 次免费大转盘机会</b>（免除参与费，"
                        "奖池与普通转盘完全一致）\n"
                        f"有效期至 {expires_dt:%m-%d %H:%M}（{settings.TZ}），过期作废\n"
                        "入口：WebApp 活动页 → 幸运大转盘"
                    ),
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"免费机会获得通知发送失败 (tg_id={grant['tg_id']}): {e}")
        logger.info(f"已发送 {len(grants)} 条免费机会获得通知")
    except Exception as e:
        logger.error(f"免费机会获得通知任务失败: {e}")


async def remind_blackjack_freespin_expiry_job() -> None:
    """每日提醒：24 小时内将到期的未用免费机会，同用户合并为一条。

    过期未用的机会是留存价值最高的损失——用户已付出手数，却因不知道
    而错过。提醒让「打满手数」的奖励完整闭环。发送量有界：每日至多
    一条/人。
    """
    try:
        expiring = db.list_expiring_blackjack_freespins()
        if not expiring:
            return
        for item in expiring:
            tg_id = int(item["tg_id"])
            expiries = item["expires_at_ms_list"]
            times = "、".join(
                datetime.fromtimestamp(ms / 1000, tz=settings.TZ).strftime(
                    "%m-%d %H:%M"
                )
                for ms in expiries
            )
            try:
                await send_message_by_url(
                    chat_id=tg_id,
                    text=(
                        "⏳ 你的免费大转盘机会即将过期\n"
                        f"共 {len(expiries)} 张未使用，将于 {times}（{settings.TZ}）作废\n"
                        "入口：WebApp 活动页 → 幸运大转盘"
                    ),
                )
            except Exception as e:
                logger.error(f"免费机会到期提醒发送失败 (tg_id={tg_id}): {e}")
        logger.info(f"已发送 {len(expiring)} 条免费机会到期提醒")
    except Exception as e:
        logger.error(f"免费机会到期提醒任务失败: {e}")


async def blackjack_weekly_cashback_job() -> None:
    """每周一结算上周 21 点损失返还，存入争霸赛余额并逐用户私信。

    结算幂等（撞 UNIQUE 跳过）、停机跨周可补漏（游标逐周推进）。
    业务结果先落库，通知失败只记日志——与锦标赛通知同一口径。
    """
    try:
        result = db.settle_blackjack_weekly_cashback()
        if not result.get("enabled"):
            return
        if result.get("anchored"):
            logger.info("21 点周返还首次运行：已锚定未结算周期，下周开始结算")
            return
        notified = 0
        for week in result.get("settled_weeks", []):
            for user in week.get("users", []):
                try:
                    await send_message_by_url(
                        chat_id=int(user["tg_id"]),
                        text=(
                            "💰 21 点周返还到账\n"
                            f"上周净亏损 <b>{_fmt_credits(abs(user['net_change']))}</b> 积分，"
                            f"按比例返还 <b>{_fmt_credits(user['cashback'])}</b> 积分\n"
                            f"已存入你的争霸赛余额（当前 {_fmt_credits(user['wallet_balance'])}），"
                            "仅可用于锦标赛报名费\n"
                            "入口：WebApp 活动页 → 21 点锦标赛"
                        ),
                        parse_mode="HTML",
                    )
                    notified += 1
                except Exception as e:
                    logger.error(f"周返还通知发送失败 (tg_id={user['tg_id']}): {e}")
        if notified:
            logger.info(f"21 点周返还已结算并通知 {notified} 位用户")
    except Exception as e:
        logger.error(f"21 点周返还任务失败: {e}")
