from datetime import datetime, timedelta

from sqlalchemy import and_, select

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.custom_lines.models import CustomLine
from app.domains.donation import service as donation_service
from app.integrations.telegram.messaging import send_message_by_url


async def _send_expiring_soon_notifications(lines: list[CustomLine], current_time: int):
    """发送即将过期的提醒通知"""
    logger.info(f"找到 {len(lines)} 条即将过期的自定义线路")

    for line in lines:
        # 若已在本次过期窗口（最近24小时）内发送过提醒，则跳过，避免重复打扰
        if (
            line.expiry_notified_at is not None
            and line.expiry_notified_at >= line.expires_at - 24 * 60 * 60
        ):
            logger.info(f"线路 {line.domain} 已在本次过期窗口内发送过提醒，跳过")
            continue

        try:
            # 计算剩余时间（小时）
            remaining_hours = round((line.expires_at - current_time) / 3600, 1)
            expire_time_str = datetime.fromtimestamp(
                line.expires_at, tz=settings.TZ
            ).strftime("%Y-%m-%d %H:%M:%S")

            message = (
                f"⏰ 自定义线路即将过期提醒\n\n"
                f"域名：{line.domain}\n"
                f"网络情况：{line.network_info}\n"
                f"过期时间：{expire_time_str}\n"
                f"剩余时间：约 {remaining_hours} 小时\n\n"
                f"⚠️ 过期后线路将自动下线并解绑所有用户\n"
                f"请及时在个人中心续期以继续使用"
            )

            await send_message_by_url(
                chat_id=line.tg_id, text=message, disable_notification=False
            )

            # 记录本次通知时间
            line.expiry_notified_at = current_time

            logger.info(
                f"已发送即将过期提醒给用户 {line.tg_id}，线路域名：{line.domain}，剩余 {remaining_hours} 小时"
            )
        except Exception as e:
            logger.error(
                f"发送即将过期提醒失败 (用户 {line.tg_id}，线路 {line.domain}): {e}"
            )


async def _process_expired_lines(
    session, lines: list[CustomLine], current_time: int, unbind_func
):
    """处理已过期的线路"""
    for line in lines:
        # 将状态改为 expired
        line.status = "expired"
        line.updated_at = current_time

        # 解绑所有使用该线路的用户
        try:
            success, unbind_count = await unbind_func(line.domain, reason="已过期")
            if success and unbind_count > 0:
                logger.info(
                    f"自定义线路 {line.domain} 过期，已解绑 {unbind_count} 个用户"
                )
        except Exception as e:
            logger.error(f"解绑过期线路 {line.domain} 用户时失败: {e}")

        # 禁用所有使用该线路的调度规则并通知用户
        try:
            from app.domains.lines.service import disable_line_schedules_and_notify

            await disable_line_schedules_and_notify(line.domain, "用户分享线路已过期")
        except Exception as e:
            logger.error(f"禁用过期线路 {line.domain} 的调度规则失败: {e}")

        # 发送通知给提交用户
        try:
            message = (
                f"📢 自定义线路过期通知\n\n"
                f"您提交的自定义线路已过期：\n"
                f"域名：{line.domain}\n"
                f"网络情况：{line.network_info}\n\n"
                f"线路已自动下线并解绑所有用户\n"
                f"您可以在个人中心续期或删除该线路"
            )

            await send_message_by_url(
                chat_id=line.tg_id, text=message, disable_notification=False
            )

            logger.info(f"已发送过期通知给用户 {line.tg_id}，线路域名：{line.domain}")
        except Exception as e:
            logger.error(
                f"发送过期通知失败 (用户 {line.tg_id}，线路 {line.domain}): {e}"
            )


from app.domains.custom_lines.notifications import _send_admin_settlement_summary
from app.domains.traffic.repository import _get_line_monthly_traffic


async def settle_custom_line_traffic(
    line_domain: str | None = None, force_current_month: bool = False
):
    """
    结算自定义线路流量积分

    Args:
        line_domain: 指定线路域名，None 表示结算所有线路
        force_current_month: 是否强制结算当月（删除线路时使用）

    功能：
    1. 每月1号凌晨2:00自动结算上个月的流量，按照流量单价赠送积分（在流量聚合任务1:00之后执行）
    2. 删除线路时立即结算当月流量
    """

    try:
        logger.info(
            f"开始结算自定义线路流量积分 (线路: {line_domain or '全部'}, 强制当月: {force_current_month})"
        )

        with get_session() as session:
            now = datetime.now(tz=settings.TZ)

            # 确定要结算的月份
            if force_current_month:
                # 删除线路时，结算当月
                settle_month = now.strftime("%Y-%m")
            else:
                # 每月1号结算上个月（在凌晨1:00流量聚合完成后）
                last_month = datetime(
                    now.year, now.month, 1, tzinfo=settings.TZ
                ) - timedelta(days=1)
                settle_month = last_month.strftime("%Y-%m")

            logger.info(f"结算月份: {settle_month}")

            # 构建查询条件
            conditions = []
            conditions.append(CustomLine.total_traffic.isnot(None))
            conditions.append(CustomLine.total_traffic > 0)
            # 至少有一个价格字段
            conditions.append(
                (CustomLine.price_monthly.isnot(None))
                | (CustomLine.price_yearly.isnot(None))
            )

            if line_domain:
                conditions.append(CustomLine.domain == line_domain)

            stmt = select(CustomLine).where(and_(*conditions))
            result = session.execute(stmt)
            lines = result.scalars().all()

            if not lines:
                logger.info("没有需要结算的自定义线路")
                return

            settled_count = 0
            total_credits = 0
            # 用于管理员汇总通知的结算详情列表
            settlement_details = []

            for line in lines:
                # 获取该月流量（排除线路所有者）
                # 如果是强制当月结算（删除线路），从原始流量表实时聚合
                # 否则从月度聚合表查询
                monthly_traffic_gb = await _get_line_monthly_traffic(
                    session,
                    line.domain,
                    settle_month,
                    line.tg_id,
                    from_raw_table=force_current_month,
                )

                if monthly_traffic_gb <= 0:
                    logger.info(
                        f"线路 {line.domain} 在 {settle_month} 无流量，跳过结算"
                    )
                    continue

                # 计算月付价格：优先使用 price_monthly，否则用 price_yearly / 12
                if line.price_monthly is not None:
                    monthly_price = line.price_monthly
                elif line.price_yearly is not None:
                    monthly_price = line.price_yearly / 12
                else:
                    logger.warning(f"线路 {line.domain} 没有配置价格，跳过结算")
                    continue

                # 计算流量单价（考虑流量类型）
                # total_traffic 是总流量包，需要根据流量类型折算
                if line.traffic_type == "two_way":
                    # 双向流量：总流量包需要除以2折算为单向
                    effective_traffic = line.total_traffic / 2
                else:
                    # 单向流量：直接使用
                    effective_traffic = line.total_traffic

                price_per_gb = float(monthly_price) / float(effective_traffic)

                # 计算应赠送的积分（使用单向流量，计算对应的价格，通过人民币和积分的倍率计算积分），按照 8 折奖励
                credits_to_reward = (
                    float(monthly_traffic_gb)
                    * price_per_gb
                    * donation_service.get_donation_multiplier()
                    * 0.8
                )

                # 赠送积分给线路所有者
                try:
                    credits_service.add(
                        CreditAccount.tg(int(line.tg_id)), credits_to_reward
                    )
                    settled_count += 1
                    total_credits += credits_to_reward

                    # 记录结算详情用于管理员汇总
                    settlement_details.append(
                        {
                            "domain": line.domain,
                            "tg_id": line.tg_id,
                            "traffic_gb": monthly_traffic_gb,
                            "price_per_gb": price_per_gb,
                            "credits": credits_to_reward,
                        }
                    )

                    logger.info(
                        f"线路 {line.domain} 结算完成: "
                        f"月份={settle_month}, "
                        f"流量={monthly_traffic_gb:.2f}GB, "
                        f"单价={price_per_gb:.4f}元/GB, "
                        f"赠送积分={credits_to_reward:.2f}"
                    )

                    # 发送结算通知
                    try:
                        message = (
                            f"💰 自定义线路流量结算通知\n\n"
                            f"线路域名：{line.domain}\n"
                            f"结算月份：{settle_month}\n"
                            f"消耗流量：{monthly_traffic_gb:.2f}GB (单向)\n"
                            f"获得积分：{credits_to_reward:.2f}\n\n"
                            f"感谢您的分享，积分已自动发放到您的账户 🎉"
                        )

                        await send_message_by_url(
                            chat_id=line.tg_id, text=message, disable_notification=False
                        )
                    except Exception as e:
                        logger.error(
                            f"发送结算通知失败 (用户 {line.tg_id}，线路 {line.domain}): {e}"
                        )

                except Exception as e:
                    logger.error(f"为线路 {line.domain} 赠送积分失败: {e}")

            logger.info(
                f"流量结算完成: 结算 {settled_count} 条线路, 总计赠送 {total_credits:.2f} 积分"
            )

            # 发送管理员汇总通知（仅在有成功结算且非单条线路结算时发送）
            if settlement_details and not line_domain and settings.TG_ADMIN_CHAT_ID:
                await _send_admin_settlement_summary(
                    settle_month, settlement_details, settled_count, total_credits
                )

    except Exception as e:
        logger.error(f"结算自定义线路流量失败: {e}", exc_info=True)


def _is_line_valid(line: CustomLine, current_time: int) -> bool:
    """
    检查线路是否在有效期内

    Args:
        line: 自定义线路对象
        current_time: 当前时间戳

    Returns:
        是否有效
    """
    # 长期可用的线路
    if line.is_permanent == 1:
        return True

    # 有期限的线路
    return bool(line.expires_at and line.expires_at > current_time)
