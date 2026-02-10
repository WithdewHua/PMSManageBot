"""
自定义线路管理模块
"""

from datetime import datetime, timedelta
from typing import List, Optional

from app.config import settings
from app.databases import db
from app.databases.session import get_session
from app.log import logger
from app.models.models import CustomLine, LineTrafficMonthlyStats
from app.utils.utils import send_message_by_url
from app.webapp.routers.admin import unbind_specified_line_for_all_users
from sqlalchemy import and_, func, select


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
            current_time = int(datetime.now().timestamp())
            # 1天后的时间戳（用于提前提醒）
            one_day_later = current_time + (24 * 60 * 60)

            # 1. 查询即将在1天内过期的线路（还未过期，但快到期了）
            expiring_soon_lines = await _get_expiring_soon_lines(
                session, current_time, one_day_later
            )

            # 发送即将过期的提醒通知
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


async def _get_expiring_soon_lines(
    session, current_time: int, one_day_later: int
) -> List[CustomLine]:
    """获取即将在1天内过期的线路"""
    stmt_expiring_soon = select(CustomLine).where(
        and_(
            CustomLine.status == "approved",
            CustomLine.is_permanent == 0,
            CustomLine.expires_at.isnot(None),
            CustomLine.expires_at > current_time,  # 还没过期
            CustomLine.expires_at <= one_day_later,  # 但1天内会过期
        )
    )

    result = session.execute(stmt_expiring_soon)
    return result.scalars().all()


async def _get_expired_lines(session, current_time: int) -> List[CustomLine]:
    """获取已经过期的线路"""
    stmt_expired = select(CustomLine).where(
        and_(
            CustomLine.status == "approved",
            CustomLine.is_permanent == 0,
            CustomLine.expires_at.isnot(None),
            CustomLine.expires_at <= current_time,
        )
    )

    result = session.execute(stmt_expired)
    return result.scalars().all()


async def _send_expiring_soon_notifications(lines: List[CustomLine], current_time: int):
    """发送即将过期的提醒通知"""
    logger.info(f"找到 {len(lines)} 条即将过期的自定义线路")

    for line in lines:
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

            logger.info(
                f"已发送即将过期提醒给用户 {line.tg_id}，线路域名：{line.domain}，剩余 {remaining_hours} 小时"
            )
        except Exception as e:
            logger.error(
                f"发送即将过期提醒失败 (用户 {line.tg_id}，线路 {line.domain}): {e}"
            )


async def _process_expired_lines(
    session, lines: List[CustomLine], current_time: int, unbind_func
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
            current_time = int(datetime.now().timestamp())
            current_month = datetime.now().strftime("%Y-%m")

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
                # 获取当月流量使用情况（排除线路所有者）
                # 从原始流量表实时读取当月流量
                monthly_traffic_gb = await _get_line_monthly_traffic(
                    session, line.domain, current_month, line.tg_id, from_raw_table=True
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

                            # 发送恢复通知
                            try:
                                message = (
                                    f"✅ 自定义线路已恢复上线\n\n"
                                    f"域名：{line.domain}\n"
                                    f"当月流量：{actual_traffic:.2f}GB\n"
                                    f"流量限制：{line.traffic_limit}GB\n\n"
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

            if offline_count > 0 or online_count > 0:
                session.commit()
                logger.info(
                    f"流量检查完成: {offline_count} 条线路下线, {online_count} 条线路上线"
                )
            else:
                logger.info("流量检查完成: 无需更新线路状态")

    except Exception as e:
        logger.error(f"检查自定义线路流量失败: {e}", exc_info=True)


async def settle_custom_line_traffic(
    line_domain: Optional[str] = None, force_current_month: bool = False
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
            now = datetime.now()

            # 确定要结算的月份
            if force_current_month:
                # 删除线路时，结算当月
                settle_month = now.strftime("%Y-%m")
            else:
                # 每月1号结算上个月（在凌晨1:00流量聚合完成后）
                last_month = datetime(now.year, now.month, 1) - timedelta(days=1)
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

                price_per_gb = monthly_price / effective_traffic

                # 计算应赠送的积分（使用单向流量），按照 7 折奖励
                credits_to_reward = monthly_traffic_gb * price_per_gb * 0.7

                # 赠送积分给线路所有者
                try:
                    db.add_credits(line.tg_id, credits_to_reward)
                    settled_count += 1
                    total_credits += credits_to_reward

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

    except Exception as e:
        logger.error(f"结算自定义线路流量失败: {e}", exc_info=True)


async def _get_line_monthly_traffic(
    session,
    line_domain: str,
    year_month: str,
    owner_tg_id: int,
    from_raw_table: bool = False,
) -> float:
    """
    获取指定线路在指定月份的总流量（GB）
    排除线路所有者自己产生的流量

    Args:
        session: 数据库会话
        line_domain: 线路域名
        year_month: 年月，格式：YYYY-MM
        owner_tg_id: 线路所有者的 tg_id
        from_raw_table: 是否从原始流量表(line_traffic_stats)实时聚合，用于删除线路时获取当月未聚合的流量

    Returns:
        总流量（GB）
    """
    try:
        # 获取线路所有者的用户名（Plex 和 Emby）
        owner_usernames = set()

        # 查询 Plex 用户名
        plex_user = db.get_plex_info_by_tg_id(owner_tg_id)
        if plex_user and plex_user[4]:  # plex_username (索引4)
            owner_usernames.add(plex_user[4].lower())

        # 查询 Emby 用户名
        emby_user = db.get_emby_info_by_tg_id(owner_tg_id)
        if emby_user and emby_user[0]:  # emby_username
            owner_usernames.add(emby_user[0].lower())

        if from_raw_table:
            # 从原始流量表实时聚合（用于删除线路时获取当月流量）
            from app.models.models import LineTrafficStats

            # 计算目标月份的开始和结束时间
            month_start = datetime.strptime(f"{year_month}-01", "%Y-%m-%d").replace(
                tzinfo=settings.TZ
            )
            if month_start.month == 12:
                next_month_start = month_start.replace(
                    year=month_start.year + 1, month=1
                )
            else:
                next_month_start = month_start.replace(month=month_start.month + 1)

            month_start_str = month_start.isoformat()
            next_month_start_str = next_month_start.isoformat()

            # 从原始流量表实时聚合
            stmt = select(func.sum(LineTrafficStats.send_bytes)).where(
                and_(
                    LineTrafficStats.line == line_domain,
                    LineTrafficStats.timestamp >= month_start_str,
                    LineTrafficStats.timestamp < next_month_start_str,
                    ~LineTrafficStats.username.in_([u.lower() for u in owner_usernames])
                    if owner_usernames
                    else True,
                )
            )

            result = session.execute(stmt)
            total_bytes = result.scalar() or 0

            logger.info(
                f"从原始流量表聚合线路 {line_domain} {year_month} 流量: {total_bytes} bytes"
            )
        else:
            # 从月度流量统计表查询（用于正常月初结算）
            stmt = select(func.sum(LineTrafficMonthlyStats.total_bytes)).where(
                and_(
                    LineTrafficMonthlyStats.line == line_domain,
                    LineTrafficMonthlyStats.year_month == year_month,
                    ~LineTrafficMonthlyStats.username.in_(
                        [u.lower() for u in owner_usernames]
                    )
                    if owner_usernames
                    else True,
                )
            )

            result = session.execute(stmt)
            total_bytes = result.scalar() or 0

        # 转换为 GB
        total_gb = total_bytes / (1024**3)

        return total_gb

    except Exception as e:
        logger.error(
            f"获取线路 {line_domain} 月流量失败 (月份: {year_month}, 原始表: {from_raw_table}): {e}",
            exc_info=True,
        )
        return 0.0


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
    if line.expires_at and line.expires_at > current_time:
        return True

    return False
