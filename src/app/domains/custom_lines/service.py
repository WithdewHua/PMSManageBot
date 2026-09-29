from datetime import datetime, timedelta

from sqlalchemy import and_, func, select

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.custom_lines import rules as custom_line_rules
from app.domains.custom_lines.models import CustomLine, CustomLineSettlement
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
    """Settle custom-line traffic once per line and calendar month."""
    logger.info(
        "开始结算自定义线路流量积分 (线路: %s, 强制当月: %s)",
        line_domain or "全部",
        force_current_month,
    )
    now = datetime.now(tz=settings.TZ)
    current_month = custom_line_rules.month_key(now, settings.TZ)
    if force_current_month:
        previous_month = custom_line_rules.month_key(
            datetime(now.year, now.month, 1, tzinfo=settings.TZ) - timedelta(days=1),
            settings.TZ,
        )
        month_sources = [(current_month, True), (previous_month, False)]
    else:
        previous_month = custom_line_rules.month_key(
            datetime(now.year, now.month, 1, tzinfo=settings.TZ) - timedelta(days=1),
            settings.TZ,
        )
        month_sources = [(previous_month, False)]

    settlement_details: list[dict] = []
    failures: list[str] = []
    for settle_month, from_raw_table in month_sources:
        with get_session() as session:
            conditions = [
                CustomLine.total_traffic.isnot(None),
                CustomLine.total_traffic > 0,
                (
                    CustomLine.price_monthly.isnot(None)
                    | CustomLine.price_yearly.isnot(None)
                ),
            ]
            if line_domain:
                conditions.append(CustomLine.domain == line_domain)
            lines = (
                session.execute(select(CustomLine).where(and_(*conditions)))
                .scalars()
                .all()
            )
            for line in lines:
                try:
                    with session.begin_nested():
                        monthly_traffic_gb = await _get_line_monthly_traffic(
                            session,
                            line.domain,
                            settle_month,
                            line.tg_id,
                            from_raw_table=from_raw_table,
                        )
                        settled_bytes = int(
                            session.execute(
                                select(
                                    func.coalesce(
                                        func.sum(CustomLineSettlement.traffic_bytes), 0
                                    )
                                ).where(
                                    CustomLineSettlement.domain == line.domain,
                                    CustomLineSettlement.year_month == settle_month,
                                )
                            ).scalar_one()
                            or 0
                        )
                        traffic_bytes = max(
                            0, int(float(monthly_traffic_gb) * 1024**3) - settled_bytes
                        )
                        if traffic_bytes <= 0:
                            continue
                        monthly_price = (
                            line.price_monthly
                            if line.price_monthly is not None
                            else float(line.price_yearly) / 12
                        )
                        effective_traffic = (
                            float(line.total_traffic) / 2
                            if line.traffic_type == "two_way"
                            else float(line.total_traffic)
                        )
                        price_per_gb = float(monthly_price) / effective_traffic
                        traffic_gb = traffic_bytes / 1024**3
                        credits_to_reward = (
                            traffic_gb
                            * price_per_gb
                            * donation_service.get_donation_multiplier()
                            * 0.8
                        )
                        settlement_id = _insert_custom_line_settlement_tx(
                            session,
                            line_id=int(line.id),
                            tg_id=int(line.tg_id),
                            domain=line.domain,
                            year_month=settle_month,
                            trigger="delete" if force_current_month else "monthly",
                            traffic_bytes=traffic_bytes,
                            credits=credits_to_reward,
                        )
                        if settlement_id is None:
                            continue
                        mutation = credits_service.apply_tx(
                            session,
                            CreditAccount.tg(int(line.tg_id)),
                            credits_to_reward,
                        )
                        if mutation is not None:
                            credits_service.register_cache_invalidation(
                                session, mutation
                            )
                        settlement_details.append(
                            {
                                "domain": line.domain,
                                "tg_id": int(line.tg_id),
                                "traffic_gb": traffic_gb,
                                "price_per_gb": price_per_gb,
                                "credits": credits_to_reward,
                                "month": settle_month,
                            }
                        )
                except Exception as error:
                    logger.exception(
                        "线路 %s (%s) %s 结算失败", line.domain, line.id, settle_month
                    )
                    failures.append(f"{line.domain} ({settle_month}): {error}")

    for detail in settlement_details:
        try:
            await send_message_by_url(
                chat_id=detail["tg_id"],
                text=(
                    "💰 自定义线路流量结算通知\n\n"
                    f"线路域名：{detail['domain']}\n"
                    f"结算月份：{detail['month']}\n"
                    f"消耗流量：{detail['traffic_gb']:.2f}GB (单向)\n"
                    f"获得积分：{detail['credits']:.2f}\n\n"
                    "感谢您的分享，积分已自动发放到您的账户 🎉"
                ),
                disable_notification=False,
            )
        except Exception:
            logger.exception("发送线路 %s 结算通知失败", detail["domain"])

    if settlement_details and not line_domain and settings.TG_ADMIN_CHAT_ID:
        try:
            await _send_admin_settlement_summary(
                current_month,
                settlement_details,
                len(settlement_details),
                sum(item["credits"] for item in settlement_details),
            )
        except Exception:
            logger.exception("发送自建线路管理员结算汇总失败")
    if failures:
        logger.error("自建线路结算失败列表: %s", failures)


def _insert_custom_line_settlement_tx(
    session,
    *,
    line_id: int,
    tg_id: int,
    domain: str,
    year_month: str,
    trigger: str,
    traffic_bytes: int,
    credits: float,
) -> int | None:
    """Insert the monthly ledger row, returning None for an idempotent replay."""
    existing = session.execute(
        select(CustomLineSettlement.id).where(
            CustomLineSettlement.line_id == int(line_id),
            CustomLineSettlement.year_month == year_month,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None
    row = CustomLineSettlement(
        line_id=int(line_id),
        tg_id=int(tg_id),
        domain=domain,
        year_month=year_month,
        trigger=trigger,
        traffic_bytes=int(traffic_bytes),
        credits=credits,
        created_at=int(datetime.now(tz=settings.TZ).timestamp()),
    )
    if session.bind.dialect.name == "sqlite":
        row.id = (
            int(
                session.execute(
                    select(func.coalesce(func.max(CustomLineSettlement.id), 0))
                ).scalar_one()
            )
            + 1
        )
    session.add(row)
    session.flush()
    return int(row.id)


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
