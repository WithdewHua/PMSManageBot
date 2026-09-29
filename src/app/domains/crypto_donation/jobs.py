import asyncio

from app.core.config import settings
from app.core.log import logger
from app.databases.db import db
from app.integrations.telegram.messaging import send_message_by_url
from app.integrations.telegram.profiles import get_user_name_from_tg_id


async def check_expired_crypto_donation_orders():
    """定时任务：检查并更新过期的 crypto 捐赠订单状态"""
    try:
        logger.info("开始检查过期的 crypto 捐赠订单")

        # 获取过期的订单（用于通知）
        expired_orders = db.get_expired_crypto_donation_orders()

        if not expired_orders:
            logger.info("没有找到过期的 crypto 捐赠订单")
            return

        # 更新过期订单状态
        updated_count = db.update_expired_crypto_donation_orders()

        if updated_count > 0:
            logger.info(f"成功更新 {updated_count} 个过期的 crypto 捐赠订单状态")

            # 准备通知消息
            notification_messages = []

            # 通知用户订单已过期
            for order in expired_orders:
                user_id = order["user_id"]
                order_id = order["order_id"]
                amount = order["amount"]
                crypto_type = order["crypto_type"]

                user_message = f"""
💰 Crypto 捐赠订单过期通知

订单号：{order_id}
金额：{amount:.2f} CNY
加密货币类型：{crypto_type}
状态：已过期

很抱歉，您的 Crypto 捐赠订单已超过有效期。如需继续捐赠，请重新创建订单。

感谢您对项目的支持！
"""

                notification_messages.append((user_id, user_message))

            # 通知管理员
            admin_message = f"""
📊 Crypto 捐赠订单过期统计

共处理过期订单：{updated_count} 个

详情：
"""
            for order in expired_orders:
                user_name = get_user_name_from_tg_id(order["user_id"])
                admin_message += f"• 用户：{user_name} ({order['user_id']}) - {order['amount']:.2f} CNY ({order['crypto_type']})\n"

            # 发送用户通知
            for user_id, message in notification_messages:
                try:
                    await send_message_by_url(
                        chat_id=user_id, text=message, disable_notification=False
                    )
                    await asyncio.sleep(0.5)  # 避免发送过于频繁
                except Exception as e:
                    logger.warning(f"向用户 {user_id} 发送过期订单通知失败: {e}")

            # 发送管理员通知
            for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
                try:
                    await send_message_by_url(
                        chat_id=admin_chat_id,
                        text=admin_message,
                        disable_notification=True,
                    )
                except Exception as e:
                    logger.warning(
                        f"向管理员 {admin_chat_id} 发送过期订单统计失败: {e}"
                    )

    except Exception as e:
        logger.error(f"检查过期 crypto 捐赠订单失败: {e}")
