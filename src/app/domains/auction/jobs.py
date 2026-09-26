from datetime import datetime

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.core.scheduler import Scheduler
from app.core.telegram import get_user_name_from_tg_id, send_message_by_url
from app.databases import db
from app.domains.auction.notifications import send_channel_auction_notification


async def finish_single_auction_job(auction_id: int):
    """
    单个竞拍结束任务
    """
    try:
        # 检查竞拍是否存在且处于活跃状态
        auction_data = db.get_auction_by_id(auction_id)
        if not auction_data or not auction_data["is_active"]:
            logger.info(f"竞拍 {auction_id} 不存在或已结束，跳过自动结束任务")
            return

        # 结束竞拍
        success, winner = db.finish_auction_by_id(auction_id)

        if success and winner:
            # 通知用户
            await send_message_by_url(
                winner.get("winner_id"),
                f"恭喜你，竞拍 {auction_data['title']} 获胜！最终出价为 {winner.get('final_price')} 积分",
            )
            if not winner.get("credits_reduced", False):
                # 如果未扣除积分，通知管理员
                for chat_id in settings.TG_ADMIN_CHAT_ID:
                    await send_message_by_url(
                        chat_id=chat_id,
                        text=f"用户 {winner.get('winner_id')} 在竞拍 {auction_data['title']} 中获胜，但未扣除积分。",
                    )

            # 发送频道通知：竞拍结束
            winner_name = get_user_name_from_tg_id(winner.get("winner_id"))
            channel_text = (
                f"🏁 竞拍结束通知\n\n"
                f"📝 竞拍: {auction_data['title']}\n"
                f"🏆 最终得主: {winner_name}\n"
                f"💰 成交价格: {winner.get('final_price')} 积分\n\n"
                f"感谢所有参与者！"
            )
            await send_channel_auction_notification(channel_text)

            logger.info(f"竞拍 {auction_id} 自动结束成功")
        elif success and not winner:
            # 无人出价，流拍
            channel_text = (
                f"🏁 竞拍结束通知\n\n"
                f"📝 竞拍: {auction_data['title']}\n"
                f"😔 本次竞拍无人出价，已流拍。"
            )
            await send_channel_auction_notification(channel_text)
            logger.info(f"竞拍 {auction_id} 自动结束，无人出价（流拍）")
        else:
            logger.warning(f"竞拍 {auction_id} 自动结束失败")

    except Exception as e:
        logger.error(f"自动结束竞拍 {auction_id} 失败: {e}")


def restore_auction_schedules():
    """
    启动时恢复现有活跃竞拍的定时任务
    """
    try:
        scheduler = Scheduler()

        # 获取所有活跃的竞拍
        active_auctions = db.get_active_auctions()

        import time

        current_time = int(time.time())

        for auction_data in active_auctions:
            auction_id = auction_data["id"]
            end_time = auction_data["end_time"]

            # 跳过已过期的竞拍（这些会被兜底任务处理）
            if end_time <= current_time:
                logger.warning(f"竞拍 {auction_id} 已过期，将由兜底任务处理")
                continue

            # 为未过期的竞拍创建定时任务
            job_id = f"finish_auction_{auction_id}"
            end_datetime = datetime.fromtimestamp(end_time, tz=settings.TZ)

            scheduler.add_async_job(
                func=finish_single_auction_job,
                args=[auction_id],
                trigger="date",
                run_date=end_datetime,
                id=job_id,
                replace_existing=True,
                max_instances=1,
            )

            logger.info(f"恢复竞拍 {auction_id} 的定时任务，结束时间: {end_datetime}")

        logger.info(
            f"已恢复 {len([a for a in active_auctions if a['end_time'] > current_time])} 个竞拍的定时任务"
        )

    except Exception as e:
        logger.error(f"恢复竞拍定时任务失败: {e}")


async def finish_expired_auctions_job():
    """定时任务：结束过期的竞拍活动"""
    try:
        finished_auctions = db.finish_expired_auctions()
        # 通知用户
        for autction in finished_auctions:
            await send_message_by_url(
                autction.get("winner_id"),
                f"恭喜你，竞拍 {autction['title']} 获胜！最终出价为 {autction['final_price']} 积分",
            )
            if not autction.get("credits_reduced", False):
                # 如果未扣除积分，通知管理员
                for chat_id in settings.TG_ADMIN_CHAT_ID:
                    await send_message_by_url(
                        chat_id=chat_id,
                        text=f"用户 {autction.get('winner_id')} 在竞拍 {autction['title']} 中获胜，但未扣除积分。",
                    )
        return finished_auctions
    except Exception as e:
        logger.error(f"自动结束过期竞拍失败: {e}")
