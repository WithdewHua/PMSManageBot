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

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.integrations.telegram.messaging import send_message_by_url
from app.integrations.telegram.profiles import get_user_names_from_tg_ids

# router declaration belongs to the HTTP assembly(prefix="/blackjack/tournament", tags=["21点锦标赛"])

# 单轮 tick 处理的赛事条数上限。达到上限会**记 error 而非静默截断**——列表按 id
# 倒序取，被截掉的恰好是最老的赛事，它们会永远开不了赛、结不了算。
_TICK_LIST_LIMIT = 100


# ============================================================
# 通知
# ============================================================


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


async def notify_tournament_started(
    tournament: dict, entrants: list, *, notify_enabled: bool = True
) -> None:
    """开赛通知。通知开关由上层 service/job 调用方解析后传入。"""
    if not notify_enabled or not entrants:
        return
    text = _format_started(tournament)
    sent = await _send_many(entrants, lambda _t: text, "开赛")
    logger.info(f"锦标赛 {tournament['id']} 开赛通知：{sent}/{len(entrants)} 人送达")
