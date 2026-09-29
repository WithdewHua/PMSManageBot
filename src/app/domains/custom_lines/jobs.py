"""
自定义线路管理模块
"""

from datetime import UTC, datetime

from sqlalchemy import and_, select

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.custom_lines.models import CustomLine
from app.domains.custom_lines.repository import (
    _get_expired_lines,
    _get_expiring_soon_lines,
)
from app.domains.custom_lines.service import (
    _process_expired_lines,
    _send_expiring_soon_notifications,
)
from app.domains.lines.service import unbind_specified_line_for_all_users
from app.integrations.telegram.messaging import send_message_by_url


async def check_expired_custom_lines():
    """
    检查即将过期和已过期的自定义线路

    功能：
    1. 检查即将在1天内过期的线路，发送提醒通知
    2. 处理已过期的线路：
       - 更新状态为 expired
       - 解绑所有使用该线路的用户
       - 发送过期通知给线路所有者
    """

    try:
        logger.info("开始检查即将过期和已过期的自定义线路")

        with get_session() as session:
            current_time = int(datetime.now(tz=UTC).timestamp())
            # 1天后的时间戳（用于提前提醒）
            one_day_later = current_time + (24 * 60 * 60)

            # 1. 查询即将在1天内过期的线路（还未过期，但快到期了）
            expiring_soon_lines = await _get_expiring_soon_lines(
                session, current_time, one_day_later
            )

            # 发送即将过期的提醒通知（函数内部会过滤已通知的线路，并更新 expiry_notified_at）
            if expiring_soon_lines:
                await _send_expiring_soon_notifications(
                    expiring_soon_lines, current_time
                )

            # 2. 查询已经过期的线路
            expired_lines = await _get_expired_lines(session, current_time)

            if not expired_lines:
                logger.info("没有需要下线的过期自定义线路")
            else:
                # 批量更新过期线路状态并解绑用户
                await _process_expired_lines(
                    session,
                    expired_lines,
                    current_time,
                    unbind_specified_line_for_all_users,
                )

                session.commit()
                logger.info(f"已将 {len(expired_lines)} 条过期自定义线路标记为已过期")

    except Exception as e:
        logger.error(f"检查过期自定义线路失败: {e}", exc_info=True)


from app.domains.custom_lines.service import _is_line_valid
from app.domains.traffic.repository import _get_line_monthly_traffic


async def check_custom_line_traffic():
    """
    检查自定义线路的月流量使用情况

    功能：
    1. 检查当月流量是否超过限制，超过则自动下线
    2. 检查新月开始时，符合条件的线路自动上线
    """

    try:
        logger.info("开始检查自定义线路流量使用情况")

        with get_session() as session:
            current_time = int(datetime.now(tz=UTC).timestamp())
            current_month = datetime.now(tz=UTC).astimezone().strftime("%Y-%m")

            # 获取所有已批准的自定义线路
            stmt = select(CustomLine).where(
                and_(
                    CustomLine.status.in_(["approved", "offline"]),
                    CustomLine.traffic_limit.isnot(None),
                    CustomLine.traffic_limit > 0,
                )
            )
            result = session.execute(stmt)
            lines = result.scalars().all()

            if not lines:
                logger.info("没有需要检查流量的自定义线路")
                return

            offline_count = 0
            online_count = 0

            for line in lines:
                # 获取当月流量使用情况（包含所有用户，不排除线路所有者）
                # 从原始流量表实时读取当月流量
                monthly_traffic_gb = await _get_line_monthly_traffic(
                    session,
                    line.domain,
                    current_month,
                    owner_tg_id=None,
                    from_raw_table=True,
                )

                # 计算实际流量（根据流量类型）
                actual_traffic = monthly_traffic_gb
                if line.traffic_type == "two_way":
                    actual_traffic = monthly_traffic_gb * 2

                logger.info(
                    f"线路 {line.domain} 当月流量: {monthly_traffic_gb:.2f}GB (单向), "
                    f"实际计费: {actual_traffic:.2f}GB ({line.traffic_type}), "
                    f"限制: {line.traffic_limit}GB"
                )

                # 检查是否超过流量限制
                if actual_traffic >= line.traffic_limit:
                    if line.status == "approved":
                        # 超过流量限制，自动下线
                        line.status = "offline"
                        line.auto_offline_reason = (
                            "traffic_exceeded"  # 标记为流量超限自动下线
                        )
                        line.updated_at = current_time
                        offline_count += 1

                        # 解绑所有使用该线路的用户
                        try:
                            (
                                success,
                                unbind_count,
                            ) = await unbind_specified_line_for_all_users(
                                line.domain, reason="流量已用尽"
                            )
                            if success and unbind_count > 0:
                                logger.info(
                                    f"自定义线路 {line.domain} 流量超限，已解绑 {unbind_count} 个用户"
                                )
                        except Exception as e:
                            logger.error(
                                f"解绑超流量线路 {line.domain} 用户时失败: {e}"
                            )

                        # 禁用所有使用该线路的调度规则并通知用户
                        try:
                            from app.domains.lines.service import (
                                disable_line_schedules_and_notify,
                            )

                            await disable_line_schedules_and_notify(
                                line.domain, "用户分享线路月流量已用尽"
                            )
                        except Exception as e:
                            logger.error(
                                f"禁用流量超限线路 {line.domain} 的调度规则失败: {e}"
                            )

                        # 发送通知给线路所有者
                        try:
                            message = (
                                f"⚠️ 自定义线路流量超限通知\n\n"
                                f"域名：{line.domain}\n"
                                f"当月流量：{actual_traffic:.2f}GB\n"
                                f"流量限制：{line.traffic_limit}GB\n\n"
                                f"线路已自动下线并解绑所有用户\n"
                                f"下月 1 号将自动恢复使用"
                            )

                            await send_message_by_url(
                                chat_id=line.tg_id,
                                text=message,
                                disable_notification=False,
                            )
                        except Exception as e:
                            logger.error(
                                f"发送流量超限通知失败 (用户 {line.tg_id}，线路 {line.domain}): {e}"
                            )

                else:
                    # 流量未超限，检查是否需要上线
                    # 仅恢复因流量超限自动下线的线路，不恢复用户主动下线的线路
                    if (
                        line.status == "offline"
                        and line.auto_offline_reason == "traffic_exceeded"
                    ):
                        # 检查线路是否还在有效期内
                        is_valid = _is_line_valid(line, current_time)
                        if is_valid:
                            line.status = "approved"
                            line.auto_offline_reason = None  # 清除自动下线标记
                            line.updated_at = current_time
                            online_count += 1

                            # 发送恢复通知给线路所有者
                            try:
                                message = (
                                    f"✅ 自定义线路已恢复上线\n\n"
                                    f"域名: {line.domain}\n"
                                    f"当月流量: {actual_traffic:.2f}GB\n"
                                    f"流量限制: {line.traffic_limit}GB\n\n"
                                    f"用户现在可以重新绑定此线路"
                                )

                                await send_message_by_url(
                                    chat_id=line.tg_id,
                                    text=message,
                                    disable_notification=False,
                                )
                            except Exception as e:
                                logger.error(
                                    f"发送线路恢复通知失败 (用户 {line.tg_id}，线路 {line.domain}): {e}"
                                )

                            # 发送频道通知
                            if settings.TG_CHANNEL_ID:
                                try:
                                    traffic_info = (
                                        f"{line.traffic_limit} GB"
                                        if line.traffic_limit
                                        else "无限制"
                                    )

                                    # 判断有效期信息
                                    if line.is_permanent:
                                        expire_info = "长期可用"
                                    elif line.expires_at:
                                        expire_info = datetime.fromtimestamp(
                                            line.expires_at, tz=settings.TZ
                                        ).strftime("%Y-%m-%d %H:%M:%S")
                                    else:
                                        expire_info = "未设置"

                                    channel_notification = f"""🎉 线路恢复上线通知

🌐 线路: {line.domain}
🌍 网络信息: {line.network_info or "未提供"}
📊 流量限制: {traffic_info}
⏰ 有效期: {expire_info}

线路流量已重置，现已恢复上线！"""

                                    await send_message_by_url(
                                        chat_id=settings.TG_CHANNEL_ID,
                                        text=channel_notification,
                                        disable_notification=False,
                                    )
                                except Exception as e:
                                    logger.error(
                                        f"发送频道恢复通知失败 (线路 {line.domain}): {e}"
                                    )

            if offline_count > 0 or online_count > 0:
                session.commit()
                logger.info(
                    f"流量检查完成: {offline_count} 条线路下线, {online_count} 条线路上线"
                )
            else:
                logger.info("流量检查完成: 无需更新线路状态")

    except Exception as e:
        logger.error(f"检查自定义线路流量失败: {e}", exc_info=True)
