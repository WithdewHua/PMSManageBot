import time

from app.core.log import uvicorn_logger as logger


def _get_group_chat_id() -> str | None:
    """获取用于群组通知的 chat_id；未配置则跳过通知。"""
    from app.core.config import settings

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

    from app.core.config import settings
    from app.integrations.telegram.messaging import send_message_by_url

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

    from app.core.config import settings
    from app.integrations.telegram.messaging import send_message_by_url

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
    from app.integrations.telegram.messaging import send_message_by_url

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
    from app.integrations.telegram.messaging import send_message_by_url

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
    from app.integrations.telegram.messaging import send_message_by_url
    from app.integrations.telegram.profiles import get_user_name_from_tg_id

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

    from app.core.config import settings
    from app.integrations.telegram.messaging import send_message_by_url
    from app.integrations.telegram.profiles import get_user_name_from_tg_id

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
    from app.integrations.telegram.messaging import send_message_by_url

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
