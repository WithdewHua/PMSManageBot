"""Post-commit crypto donation notifications; templates frozen from 761b0a5."""

import asyncio

from app.core.config import settings
from app.core.log import logger
from app.domains.crypto_donation.types import NewOrder, UPayCallbackData
from app.integrations.telegram import messaging, profiles


async def notify_admins(message: str) -> None:
    for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
        try:
            await messaging.send_message_by_url(
                chat_id=admin_chat_id, text=message, parse_mode="HTML"
            )
        except Exception as error:
            logger.warning("发送 UPay 管理员通知失败 %s: %s", admin_chat_id, error)


async def notify_created(
    user_id: int,
    order_id: str,
    order_data: NewOrder,
    upay_result: dict,
    updated_order: dict,
) -> None:
    try:
        user_name = profiles.get_user_name_from_tg_id(user_id)
        admin_message = f"""
💰 <b>新的 Crypto 捐赠订单</b>

👤 用户: {user_name} ({user_id})
🆔 订单号: {order_id}
💳 加密货币: {order_data.crypto_type}
💵 金额: {order_data.amount:.2f} CNY
📝 备注: {order_data.note or "无"}

💰 支付地址: <code>{upay_result.get("token", "未获取")}</code>
🔗 支付链接: {upay_result.get("payment_url", "未获取")}
⏰ 创建时间: {updated_order.get("created_at", "未知")}
"""
        await notify_admins(admin_message)
    except Exception as error:
        logger.warning("发送 Crypto 捐赠订单创建通知失败: %s", error)


async def notify_payment(callback: UPayCallbackData, result: dict) -> None:
    order = result["order"]
    user_id = int(order["user_id"])
    donation_amount_cny = float(order["amount"])
    credits_reward = result["credits_reward"]
    new_donation = result["new_donation"]
    new_credits = result["new_credits"]
    try:
        user_message = f"""
🎉 <b>Crypto 捐赠支付成功</b>

感谢您的捐赠！

🆔 订单号: {callback.order_id}
💳 加密货币: {order["crypto_type"]}
💵 支付金额: {donation_amount_cny:.2f} CNY
🏆 获得积分: {credits_reward}
💰 累计捐赠: {new_donation:.2f} CNY
⭐ 当前积分: {new_credits:.2f}

您的支持是我们前进的动力！
"""
        await messaging.send_message_by_url(
            chat_id=user_id, text=user_message, parse_mode="HTML"
        )
    except Exception as error:
        logger.warning("发送用户 Crypto 捐赠支付成功通知失败: %s", error)
    try:
        user_name = profiles.get_user_name_from_tg_id(user_id)
        admin_message = f"""
✅ <b>Crypto 捐赠订单支付完成</b>

👤 用户: {user_name} ({user_id})
🆔 订单号: {callback.order_id}
💳 加密货币: {order["crypto_type"]}
💵 支付金额: {donation_amount_cny:.2f} CNY
🏆 积分奖励: {credits_reward}
💰 用户累计捐赠: {new_donation:.2f} CNY
⭐ 用户当前积分: {new_credits:.2f}

🔗 区块链交易: <code>{callback.block_transaction_id or "未提供"}</code>
⏰ 完成时间: {callback.time or "未知"}
"""
        await notify_admins(admin_message)
    except Exception as error:
        logger.warning("发送 Crypto 捐赠订单完成通知失败: %s", error)


async def notify_expired(expired_orders: list[dict]) -> None:
    updated_count = len(expired_orders)
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
        user_name = profiles.get_user_name_from_tg_id(order["user_id"])
        admin_message += f"• 用户：{user_name} ({order['user_id']}) - {order['amount']:.2f} CNY ({order['crypto_type']})\n"

    # 发送用户通知
    for user_id, message in notification_messages:
        try:
            await messaging.send_message_by_url(
                chat_id=user_id, text=message, disable_notification=False
            )
            await asyncio.sleep(0.5)  # 避免发送过于频繁
        except Exception as e:
            logger.warning(f"向用户 {user_id} 发送过期订单通知失败: {e}")

    # 发送管理员通知
    for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
        try:
            await messaging.send_message_by_url(
                chat_id=admin_chat_id,
                text=admin_message,
                disable_notification=True,
            )
        except Exception as e:
            logger.warning(f"向管理员 {admin_chat_id} 发送过期订单统计失败: {e}")
