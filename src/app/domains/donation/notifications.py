"""Donation domain notifications."""

from __future__ import annotations

from typing import Any

from app.core.log import logger
from app.integrations.telegram.messaging import send_message, send_message_by_url
from app.transport.telegram.admin import notify_admins_by_url


async def notify_admins_of_registration(
    user_id: int,
    user_name: str,
    payment_method: str,
    amount: float,
    is_donation_registration: bool,
) -> None:
    """Send admin notification when a user registers a donation."""
    registration_type = "捐赠开号" if is_donation_registration else "普通捐赠"
    text = (
        f"用户 {user_name} 提交了{registration_type}登记: {payment_method} {amount}元"
    )
    try:
        await notify_admins_by_url(text)
        logger.info(
            f"用户 {user_name} 提交了{registration_type}登记: "
            f"{payment_method} {amount}元"
        )
    except Exception as e:
        logger.warning(f"发送管理员捐赠登记通知失败: {e}")


async def send_confirmation_notifications(
    *,
    registration_id: int,
    user_id: int,
    user_name: str,
    admin_id: int,
    admin_name: str,
    approved: bool,
    amount: float,
    payment_method: str,
    is_donation_registration: bool,
    processed_at: str | None,
    admin_note: str | None = None,
) -> None:
    """Send confirmation notifications to the donor user and the processing admin."""
    action = "批准" if approved else "拒绝"
    reg_type_name = "捐赠开号" if is_donation_registration else "普通捐赠"

    if approved:
        notification_text = (
            f"✅ 您的{reg_type_name}登记已批准\n\n"
            f"📝 登记编号: #{registration_id}\n"
            f"💰 捐赠金额: {amount}元\n"
            f"💳 支付方式: {payment_method}\n"
            f"📋 登记类型: {reg_type_name}\n"
            f"👨‍💼 处理管理员: {admin_name}\n"
            f"⏰ 处理时间: {processed_at}"
        )
        if admin_note:
            notification_text += f"\n📋 管理员备注: {admin_note}"

        if is_donation_registration:
            notification_text += (
                "\n\n🎫 已为您生成邀请码，可在个人中心查看。\n"
                "📝 捐赠开号只记录捐赠金额，不增加积分。"
            )
        else:
            notification_text += "\n\n💎 您的捐赠金额和积分已更新。"

        notification_text += "\n\n感谢您的支持！"
    else:
        notification_text = (
            f"❌ 您的{reg_type_name}登记被拒绝\n\n"
            f"📝 登记编号: #{registration_id}\n"
            f"💰 捐赠金额: {amount}元\n"
            f"💳 支付方式: {payment_method}\n"
            f"📋 登记类型: {reg_type_name}\n"
            f"👨‍💼 处理管理员: {admin_name}\n"
            f"⏰ 处理时间: {processed_at}"
        )
        if admin_note:
            notification_text += f"\n📋 拒绝原因: {admin_note}"
        else:
            notification_text += "\n📋 拒绝原因: 未提供具体原因"

        notification_text += "\n\n如有疑问，请联系管理员。"

    user_notified = True
    try:
        await send_message_by_url(
            chat_id=user_id,
            text=notification_text,
            parse_mode="HTML",
        )
        logger.info(f"已向用户 {user_name}({user_id}) 发送捐赠登记{action}通知")
    except Exception as e:
        user_notified = False
        logger.warning(f"发送用户捐赠登记{action}通知失败: {e}")

    # Notify admin
    try:
        if user_notified:
            admin_text = (
                f"管理员 {admin_name}，已成功{action}捐赠登记 {registration_id}，"
                f"用户 {user_name}({user_id}) 已收到通知。"
            )
        else:
            admin_text = (
                f"管理员 {admin_name}，处理的捐赠登记 {registration_id} "
                f"的通知发送失败，请检查日志。"
            )
        await send_message_by_url(
            chat_id=admin_id,
            text=admin_text,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"发送管理员确认反馈通知失败: {e}")


async def send_donation_received_notification(
    *,
    tg_id: int,
    amount: float,
    cumulative_donation: float,
    note: str | None = None,
) -> None:
    """Send notification to user when admin records a donation."""
    text = (
        f"\n感谢您的捐赠！\n\n"
        f"💰 本次捐赠: {amount}元\n"
        f"💳 累计捐赠: {cumulative_donation}元\n"
    )
    if note:
        text += f"📝 备注: {note}"

    try:
        await send_message_by_url(
            chat_id=tg_id,
            text=text,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"发送捐赠通知失败: {e!s}")


async def send_bot_donation_credit_notification(
    *,
    tg_id: int,
    delta: float,
    context: Any,
) -> None:
    """Send notification to user when bot sets donation with credits."""
    await send_message(
        chat_id=tg_id,
        text=f"通知：感谢您的捐赠，已为您增加积分 {delta}",
        context=context,
    )


__all__ = [
    "notify_admins_of_registration",
    "send_bot_donation_credit_notification",
    "send_confirmation_notifications",
    "send_donation_received_notification",
]
