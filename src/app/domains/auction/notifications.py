from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.databases import db
from app.utils.utils import get_user_name_from_tg_id, send_message_by_url


async def send_channel_auction_notification(text: str):
    """
    后台任务：发送竞拍频道通知
    """
    if not settings.TG_CHANNEL_ID:
        return
    try:
        await send_message_by_url(
            chat_id=settings.TG_CHANNEL_ID,
            text=text,
            disable_notification=False,
        )
        logger.info("竞拍频道通知发送成功")
    except Exception as e:
        logger.error(f"发送竞拍频道通知失败: {e}")


async def send_bid_notifications(
    auction_id: int,
    bidder_id: int,
    bid_amount: float,
    auction_title: str,
    bid_count: int,
):
    """
    后台任务：发送出价通知给其他参与者和管理员
    """
    try:
        # 获取该拍卖的其他参与者
        other_participants = db.get_auction_participants(
            auction_id, exclude_user_id=bidder_id
        )

        # 准备通知消息
        bidder_name = get_user_name_from_tg_id(bidder_id)

        # 通知其他参与者
        participant_message = (
            f"🔔 竞拍更新通知\n\n"
            f"📝 竞拍: {auction_title}\n"
            f"👤 最新出价 {bid_amount} 积分\n\n"
            f"快来查看详情并参与竞拍吧！"
        )

        for participant_id in other_participants:
            try:
                await send_message_by_url(
                    chat_id=participant_id, text=participant_message
                )
            except Exception as e:
                logger.warning(f"发送通知给参与者 {participant_id} 失败: {e}")

        # 通知管理员
        admin_message = (
            f"🎯 拍卖新出价通知\n\n"
            f"📝 竞拍: {auction_title}\n"
            f"👤 出价者: {bidder_name} (ID: {bidder_id})\n"
            f"💰 出价金额: {bid_amount} 积分\n"
            f"📊 总出价次数: {bid_count}"
        )

        for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
            try:
                await send_message_by_url(chat_id=admin_chat_id, text=admin_message)
            except Exception as e:
                logger.warning(f"发送通知给管理员 {admin_chat_id} 失败: {e}")

        logger.info(f"成功发送出价通知，竞拍ID: {auction_id}, 出价者: {bidder_id}")

    except Exception as e:
        logger.error(f"发送出价通知失败: {e}")
