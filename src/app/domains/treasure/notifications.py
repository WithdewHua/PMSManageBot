"""Treasure group and winner notifications."""

from app.core.log import uvicorn_logger as logger
from app.utils.utils import get_user_name_from_tg_id


def _get_group_chat_id() -> str | None:
    """获取用于群组通知的 chat_id。

    群组通知明确使用 TG_GROUP（可以是数字 ID 或 @username）。
    未配置则跳过群组通知。
    """
    from app.core.config import settings

    if getattr(settings, "TG_GROUP_ID", None):
        return str(settings.TG_GROUP_ID)
    return None


async def notify_treasure_issue_created(
    *,
    issue_id: int,
    title: str,
    total_shares: int,
    credits_per_share: int,
    prize_credits: int,
) -> None:
    """新期数创建后群组通知（若 TG_GROUP 未配置则跳过）。"""

    from app.utils.utils import send_message_by_url

    chat_id = _get_group_chat_id()
    if not chat_id:
        logger.info("TG_GROUP not configured; skip treasure created notification")
        return

    text = (
        f"🎁 <b>夺宝奇兵</b> 新期数已开启\n"
        f"期数ID：{issue_id}\n"
        f"标题：{title}\n"
        f"每份：{credits_per_share} 积分\n"
        f"总份数：{total_shares}\n"
        f"奖池：{prize_credits} 积分\n"
        f"入口：WebApp 活动页 → 夺宝奇兵"
    )
    await send_message_by_url(chat_id=chat_id, text=text, parse_mode="HTML")


async def notify_treasure_settled(
    *,
    issue_id: int,
    title: str,
    winner_tg_id: int,
    winner_number: int,
    prize_credits: int,
) -> None:
    """开奖结算后的通知：中奖者私聊 + 群组公告（若 TG_GROUP 未配置则跳过）。"""

    from app.utils.utils import send_message_by_url

    # 1) 通知中奖者（私聊）
    try:
        text_user = (
            f"🎉 恭喜你中奖！\n"
            f"期数ID：{issue_id}\n"
            f"标题：{title}\n"
            f"中奖号码：{winner_number}\n"
            f"已发放奖池：{prize_credits} 积分"
        )
        await send_message_by_url(chat_id=winner_tg_id, text=text_user)
    except Exception as e:
        logger.warning(f"Notify winner failed: {e}")

    # 2) 群组公告
    chat_id = _get_group_chat_id()
    if not chat_id:
        return
    text_group = (
        f"🏁 <b>夺宝奇兵</b> 已开奖\n"
        f"期数ID：{issue_id}\n"
        f"标题：{title}\n"
        f"中奖号码：{winner_number}\n"
        f"中奖用户：<code>{get_user_name_from_tg_id(winner_tg_id)}</code>\n"
        f"奖池：{prize_credits} 积分"
    )
    await send_message_by_url(chat_id=chat_id, text=text_group, parse_mode="HTML")


async def notify_treasure_not_full_after_join(
    *,
    issue_id: int,
    title: str | None,
    joiner_tg_id: int,
    bought_shares: int,
    shares_sold: int,
    total_shares: int,
    prize_credits: int,
) -> None:
    """用户参与后，若未满员则群组通知当前进度与距离开奖剩余人数/份数。"""

    from app.utils.utils import send_message_by_url

    chat_id = _get_group_chat_id()
    if not chat_id:
        return

    try:
        remaining = max(0, int(total_shares) - int(shares_sold))
    except Exception:
        remaining = 0

    # 仅在未满员时通知（remaining==0 的情况由开奖公告覆盖）
    if remaining <= 0:
        return

    text = (
        f"🧩 <b>夺宝奇兵 #{int(issue_id)}</b> 有新参与\n"
        f"标题：{title or 'N/A'}\n"
        f"奖池：{prize_credits} 积分\n"
        f"参与用户：<code>{get_user_name_from_tg_id(joiner_tg_id) or joiner_tg_id}</code>\n"
        f"已购买份数：{bought_shares}\n"
        f"距离开奖还差：{int(remaining)} 份"
    )
    await send_message_by_url(chat_id=chat_id, text=text, parse_mode="HTML")
