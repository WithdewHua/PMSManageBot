from datetime import datetime

from app.core.config import settings
from app.core.log import logger
from app.core.telegram import send_message_by_url


async def _send_admin_settlement_summary(
    settle_month: str,
    settlement_details: list[dict],
    settled_count: int,
    total_credits: float,
):
    """
    发送管理员结算汇总通知

    Args:
        settle_month: 结算月份
        settlement_details: 结算详情列表
        settled_count: 结算线路数量
        total_credits: 总赠送积分
    """
    try:
        # 计算汇总数据
        total_traffic = sum(d["traffic_gb"] for d in settlement_details)

        # 构建汇总消息
        message_lines = [
            "📊 自定义线路流量结算汇总报告",
            "",
            f"📅 结算月份：{settle_month}",
            f"📈 结算线路数：{settled_count} 条",
            f"💾 总消耗流量：{total_traffic:.2f} GB",
            f"💰 总赠送积分：{total_credits:.2f}",
            "",
            "━━━━━━━ 明细列表 ━━━━━━━",
        ]

        # 添加每条线路的结算详情
        for idx, detail in enumerate(settlement_details, 1):
            message_lines.append(
                f"{idx}. {detail['domain']}\n"
                f"   用户ID: {detail['tg_id']}\n"
                f"   流量: {detail['traffic_gb']:.2f}GB | 积分: {detail['credits']:.2f}"
            )

        message_lines.append("")
        message_lines.append(
            f"✅ 结算完成时间：{datetime.now(settings.TZ).strftime('%Y-%m-%d %H:%M:%S')}"
        )

        message = "\n".join(message_lines)

        # 发送给所有管理员
        for admin_id in settings.TG_ADMIN_CHAT_ID:
            try:
                await send_message_by_url(
                    chat_id=admin_id, text=message, disable_notification=False
                )
                logger.info(f"已发送结算汇总通知给管理员 {admin_id}")
            except Exception as e:
                logger.error(f"发送结算汇总通知给管理员 {admin_id} 失败: {e}")

    except Exception as e:
        logger.error(f"发送管理员结算汇总通知失败: {e}", exc_info=True)
