"""Auction notifications; message construction is kept out of routers and jobs."""

from app.core.config import settings
from app.core.log import logger
from app.core.telegram import get_user_name_from_tg_id, send_message_by_url


async def send_channel_auction_notification(text: str) -> None:
    """Send a prepared auction announcement to the configured channel."""
    if not settings.TG_CHANNEL_ID:
        return
    try:
        await send_message_by_url(
            chat_id=settings.TG_CHANNEL_ID,
            text=text,
            disable_notification=False,
        )
        logger.info("竞拍频道通知发送成功")
    except Exception as error:
        logger.error(f"发送竞拍频道通知失败: {error}")


async def send_auction_created_notification(
    *, title: str, description: str, starting_price: float, end_time_text: str
) -> None:
    await send_channel_auction_notification(
        "🎉 新竞拍活动开始啦！\n\n"
        f"📝 竞拍: {title}\n"
        f"📖 描述: {description or '暂无描述'}\n"
        f"💰 起拍价: {starting_price} 积分\n"
        f"⏰ 结束时间: {end_time_text}\n\n"
        "欢迎感兴趣的朋友参与！"
    )


async def send_bid_notifications(
    auction_id: int,
    bidder_id: int,
    bid_amount: float,
    auction_title: str,
    bid_count: int,
    participant_ids: list[int] | None = None,
) -> None:
    """Notify other bidders and administrators using service-provided IDs."""
    try:
        bidder_name = get_user_name_from_tg_id(bidder_id)
        participant_message = (
            "🔔 竞拍更新通知\n\n"
            f"📝 竞拍: {auction_title}\n"
            f"👤 最新出价 {bid_amount} 积分\n\n"
            "快来查看详情并参与竞拍吧！"
        )
        for participant_id in participant_ids or []:
            try:
                await send_message_by_url(
                    chat_id=participant_id, text=participant_message
                )
            except Exception as error:
                logger.warning(f"发送通知给参与者 {participant_id} 失败: {error}")

        admin_message = (
            "🎯 拍卖新出价通知\n\n"
            f"📝 竞拍: {auction_title}\n"
            f"👤 出价者: {bidder_name} (ID: {bidder_id})\n"
            f"💰 出价金额: {bid_amount} 积分\n"
            f"📊 总出价次数: {bid_count}"
        )
        for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
            try:
                await send_message_by_url(chat_id=admin_chat_id, text=admin_message)
            except Exception as error:
                logger.warning(f"发送通知给管理员 {admin_chat_id} 失败: {error}")
        logger.info(f"成功发送出价通知，竞拍ID: {auction_id}, 出价者: {bidder_id}")
    except Exception as error:
        logger.error(f"发送出价通知失败: {error}")


async def send_auction_finished_notifications(
    *,
    title: str,
    winner_id: int | None,
    final_price: float | None,
    credits_reduced: bool = True,
    notify_winner: bool = True,
    notify_channel: bool = True,
) -> None:
    """Send winner/admin/channel messages after an auction has settled."""
    if notify_winner:
        try:
            await send_message_by_url(
                winner_id,
                f"恭喜你，竞拍 {title} 获胜！最终出价为 {final_price} 积分",
            )
        except Exception as error:
            logger.warning(f"发送竞拍中奖通知失败: {error}")

        if not credits_reduced:
            for chat_id in settings.TG_ADMIN_CHAT_ID:
                try:
                    await send_message_by_url(
                        chat_id=chat_id,
                        text=f"用户 {winner_id} 在竞拍 {title} 中获胜，但未扣除积分。",
                    )
                except Exception as error:
                    logger.warning(f"发送竞拍积分扣除告警失败: {error}")

    if not notify_channel:
        return
    if winner_id is not None:
        winner_name = get_user_name_from_tg_id(winner_id)
        channel_text = (
            "🏁 竞拍结束通知\n\n"
            f"📝 竞拍: {title}\n"
            f"🏆 最终得主: {winner_name}\n"
            f"💰 成交价格: {final_price} 积分\n\n"
            "感谢所有参与者！"
        )
    else:
        channel_text = (
            f"🏁 竞拍结束通知\n\n📝 竞拍: {title}\n😔 本次竞拍无人出价，已流拍。"
        )
    await send_channel_auction_notification(channel_text)


__all__ = [
    "send_auction_created_notification",
    "send_auction_finished_notifications",
    "send_bid_notifications",
    "send_channel_auction_notification",
]
