"""
Premium 会员相关功能,包括检查过期状态和即将过期的用户。
"""

from collections.abc import Sequence
from datetime import datetime

from app.core.byte_size import format_bytes
from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.media_access import service as media_access_service
from app.domains.premium import repository as premium_repository
from app.domains.premium.config import PREMIUM_CONFIG
from app.domains.traffic import service as traffic_service
from app.integrations.telegram.messaging import send_message_by_url
from app.integrations.telegram.profiles import get_user_name_from_tg_id

is_download_unlocked = media_access_service.is_download_unlocked


def get_premium_config():
    return PREMIUM_CONFIG.get()


def is_premium_unlock_enabled() -> bool:
    return bool(PREMIUM_CONFIG.get().premium_unlock_enabled)


def get_premium_daily_credits() -> int:
    return int(PREMIUM_CONFIG.get().premium_daily_credits)


def set_premium_unlock_enabled(enabled: bool):
    return PREMIUM_CONFIG.update(premium_unlock_enabled=enabled)


def set_premium_daily_credits(credits: int) -> int:
    return int(
        PREMIUM_CONFIG.update(premium_daily_credits=credits).premium_daily_credits
    )


def get_credits_cost_per_10gb() -> int:
    return int(PREMIUM_CONFIG.get().credits_cost_per_10gb)


def set_credits_cost_per_10gb(credits: int) -> int:
    return int(
        PREMIUM_CONFIG.update(credits_cost_per_10gb=credits).credits_cost_per_10gb
    )


async def check_premium_expiry():
    """Expire each Premium account independently and perform cleanup post-commit."""

    try:
        expired_users = premium_repository.get_expired_premium_users()
    except Exception:
        logger.exception("读取 Premium 过期用户失败")
        return

    failures: list[str] = []
    query_failures: list[str] = []
    for candidate in expired_users:
        tg_id = int(candidate["tg_id"])
        service = str(candidate["service"])
        try:
            now = datetime.now(settings.TZ)
            with get_session() as session:
                expired = premium_repository.expire_user_tx(
                    session, tg_id=tg_id, service=service, now=now
                )
            if expired is None:
                continue

            username = expired.get("username") or tg_id
            target = expired.get("target")
            try:
                already_unlocked = is_download_unlocked(tg_id, service)
            except Exception as error:
                failure = f"{service} {username}: 查询下载权限失败: {error}"
                failures.append(failure)
                query_failures.append(failure)
                continue

            if not already_unlocked and target:
                try:
                    if service == "plex":
                        from app.integrations.plex import Plex

                        Plex().update_sync_for_user(target, allow_sync=False)
                    else:
                        from app.integrations.emby import Emby

                        Emby().update_download_permission_for_user(
                            target, allow_download=False
                        )
                except Exception as error:
                    failures.append(f"{service} {username}: 撤销下载权限失败: {error}")

            line = expired.get("line")
            display_line = line or "自动线路"
            if line and (
                line in settings.PREMIUM_STREAM_BACKEND
                or "premium" in str(line).lower()
            ):
                try:
                    new_line = (
                        _unbind_premium_line(service, username, tg_id) or "自动线路"
                    )
                except Exception as error:
                    failures.append(f"{service} {username}: 解绑会员线路失败: {error}")
                    new_line = display_line
            else:
                new_line = display_line

            try:
                await send_message_by_url(
                    tg_id,
                    f"您的 {service} Premium 已过期，到期时间为 {expired['expiry_time']}。"
                    f"当前线路为: {new_line}。请重新解锁 Premium 以继续使用高级功能。",
                )
            except Exception as error:
                failures.append(f"{service} {username}: 发送通知失败: {error}")
        except Exception as error:
            logger.exception("处理 Premium 过期用户 %s/%s 失败", service, tg_id)
            failures.append(f"{service} {tg_id}: {error}")

    for failure in failures:
        logger.warning("Premium 过期处理未完成: %s", failure)
    if query_failures:
        summary = "Premium 过期权限查询失败:\n" + "\n".join(
            f"- {failure}" for failure in query_failures
        )
        for chat_id in settings.TG_ADMIN_CHAT_ID:
            try:
                await send_message_by_url(chat_id, summary)
            except Exception:
                logger.exception("发送 Premium 过期查询失败汇总失败")


async def check_premium_expiring_soon(days: int = 3):
    """检查即将过期的 Premium 用户并记录日志"""
    try:
        logger.info(f"检查 {days} 天内即将过期的 Premium 用户")
        expiring_users = premium_repository.get_premium_users_expiring_soon(days)

        if expiring_users:
            logger.info(f"发现 {len(expiring_users)} 个即将过期的 Premium 用户")

            for user in expiring_users:
                user_name = get_user_name_from_tg_id(user["tg_id"])
                logger.info(
                    f"用户 {user_name} ({user['username']}) 的 {user['service']} Premium 将在 {user['days_remaining']} 天后过期 (到期时间: {user['expiry_time']})"
                )
                # 发送通知消息
                message = f"您的 {user['service']} Premium 将在 {user['days_remaining']} 天后过期，到期时间为 {user['expiry_time']}。"
                await send_message_by_url(user["tg_id"], message)
        else:
            logger.debug(f"未发现 {days} 天内即将过期的 Premium 用户")

    except Exception as e:
        logger.error(f"检查即将过期的 Premium 用户时出错: {e!s}")


def is_permanent_member(tg_id: int, service: str) -> bool:
    return premium_repository.is_permanent_member(int(tg_id), service)


def purchase_premium(*, tg_id: int, service: str, days: int, cost: float):
    result = premium_repository.purchase_premium(
        tg_id=int(tg_id), service=service, days=int(days), cost=float(cost)
    )
    # The repository transaction has committed before the external media call.
    sync_premium_media_access(int(tg_id), (service,))
    return result


def update_premium_status(tg_id: int, service: str, days: int = 30) -> datetime | None:
    """给用户延长 Premium 天数，提交后再同步媒体权限。

    行为与旧实现一致：永久会员返回 None 且不写入；未过期从原到期时间续期，
    否则从当前时间起算。写入本身在 `premium.repository.grant_premium_days_tx`
    里完成（行锁 + 调用方事务），需要复用外层事务的调用方直接用那个 `*_tx`。
    """
    with get_session() as session:
        new_expiry = premium_repository.grant_premium_days_tx(
            session, tg_id, service, days
        )
    if new_expiry is not None:
        sync_premium_media_access(tg_id, (service,))
    return new_expiry


def sync_premium_media_access(
    tg_id: int, services: Sequence[str] | None = None
) -> None:
    """把 Premium 对应的下载/同步权限同步到媒体服务器（提交后 best-effort）。

    这是纯外部副作用：失败只记 warning，不影响 Premium 本身的发放，也不会把
    HTTP 往返关进事务。`services` 为空时检查用户绑定过的 Plex 与 Emby；已经用
    积分解锁下载权限的用户直接跳过，保持原有行为。签名里不再需要门面实例。
    """
    for service in services if services is not None else ("plex", "emby"):
        if service not in ("plex", "emby"):
            continue
        target = premium_repository.get_premium_sync_target(tg_id, service)
        if not target:
            continue
        if media_access_service.is_download_unlocked(tg_id, service):
            logger.info(
                f"用户 {tg_id} 已用积分解锁 {service.capitalize()} 下载权限，跳过 Premium 授权"
            )
            continue
        try:
            if service == "plex":
                from app.integrations.plex import Plex

                Plex().update_sync_for_user(target, allow_sync=True)
                logger.info(f"已为 Premium 用户 {tg_id} 启用 Plex 同步权限")
            else:
                from app.integrations.emby import Emby

                Emby().update_download_permission_for_user(target, allow_download=True)
                logger.info(f"已为 Premium 用户 {tg_id} 启用 Emby 下载权限")
        except Exception as e:
            logger.warning(f"为 Premium 用户 {tg_id} 启用 {service} 权限失败: {e}")


def apply_download_unlock_to_media(tg_id: int, service: str) -> None:
    """Delegate the post-commit media permission sync to media_access."""
    media_access_service.apply_download_unlock_to_media(int(tg_id), service)


def _unbind_premium_line(service: str, username: str, tg_id: int):
    """Use the lines service unbinder, retaining a local compatibility fallback."""
    from app.domains.lines import repository as lines_repository
    from app.domains.lines import service as lines_service

    unbinder = getattr(lines_service, "unbind_premium_line", None)
    if unbinder is not None:
        return unbinder(service, username, tg_id)

    if service not in ("plex", "emby"):
        raise ValueError("不支持的服务类型")
    last_line = None
    try:
        last_line = lines_service.get_cached_line(service, username, last=True)
    except Exception as error:
        logger.warning("读取用户 %s 的历史线路失败: %s", username, error)
    repository = lines_repository.LinesRepository()
    if service == "plex":
        repository.set_plex_line(last_line, tg_id=tg_id)
    else:
        repository.set_emby_line(last_line, tg_id=tg_id)
    try:
        if last_line:
            lines_service.put_cached_line(service, username, last_line)
            lines_service.delete_cached_line(service, username, last=True)
        else:
            lines_service.delete_cached_line(service, username)
    except Exception as error:
        logger.warning("清理用户 %s 的线路缓存失败: %s", username, error)
    return last_line or "AUTO"


def format_premium_statistics_message(
    stats, premium_users=None, premium_debt_users=None
) -> str:
    """
    格式化 Premium 线路统计信息为 Telegram 消息格式
    :param stats: 统计数据列表
    :param premium_users: Premium 用户列表（可选）
    :param premium_debt_users: Premium 流量欠额用户列表（可选）
    :return: 格式化后的消息字符串
    """
    if not stats and not premium_users and not premium_debt_users:
        return "📊 Premium 统计信息\n\n❌ 暂无统计数据"

    current_time = datetime.now(settings.TZ).strftime("%Y-%m-%d %H:%M:%S")

    message_parts = [
        "📊 Premium 统计信息",
        f"⏰ 统计时间: {current_time}",
        "─" * 40,
    ]

    total_today = 0
    total_week = 0
    total_month = 0

    if stats:
        for line_stat in stats:
            line = line_stat["line"]
            today_traffic = line_stat["today_traffic"]
            week_traffic = line_stat["week_traffic"]
            month_traffic = line_stat["month_traffic"]
            top_users = line_stat["top_users"]

            total_today += today_traffic
            total_week += week_traffic
            total_month += month_traffic

            # 清理线路名称中的多余字符
            clean_line = line.strip("[]'\"")
            message_parts.append(f"🔗 线路: {clean_line}")
            message_parts.append(f"📈 今日流量: {format_bytes(today_traffic)}")
            message_parts.append(f"📊 本周流量: {format_bytes(week_traffic)}")
            message_parts.append(f"📉 本月流量: {format_bytes(month_traffic)}")

            if top_users:
                message_parts.append("👥 今日TOP用户:")
                for i, user in enumerate(top_users, 1):
                    username = user["username"]
                    traffic = format_bytes(user["traffic"])
                    message_parts.append(f"  {i}. {username}: {traffic}")
            else:
                message_parts.append("👥 今日暂无用户使用")

            message_parts.append("")  # 空行分隔

        # 添加总计信息
        message_parts.extend(
            [
                "📋 流量总计:",
                f"📈 今日总流量: {format_bytes(total_today)}",
                f"📊 本周总流量: {format_bytes(total_week)}",
                f"📉 本月总流量: {format_bytes(total_month)}",
            ]
        )

    # 添加 Premium 用户信息
    if premium_users:
        message_parts.extend(
            [
                "",
                "─" * 40,
                f"👑 Premium 用户统计 (共 {len(premium_users)} 人)",
                "─" * 40,
            ]
        )

        # 按服务类型分组显示
        plex_users = [u for u in premium_users if u["service"] == "Plex"]
        emby_users = [u for u in premium_users if u["service"] == "Emby"]

        if plex_users:
            message_parts.append(f"\n🎬 Plex Premium ({len(plex_users)} 人):")
            for user in plex_users:
                username = user["username"]
                expiry = user["expiry_time"]
                line = user.get("line", "未知")
                if expiry:
                    try:
                        expiry_dt = datetime.fromisoformat(str(expiry)).astimezone(
                            settings.TZ
                        )
                        days_left = (expiry_dt - datetime.now(settings.TZ)).days
                        expiry_str = expiry_dt.strftime("%Y-%m-%d")
                        if days_left <= 3:
                            status = f"⚠️ {days_left}天后到期"
                        else:
                            status = f"{days_left}天后到期"
                        message_parts.append(
                            f"  • {username} | {expiry_str} ({status}) | 线路: {line or 'AUTO'}"
                        )
                    except Exception:
                        message_parts.append(
                            f"  • {username} | 到期时间: {expiry} | 线路: {line or 'AUTO'}"
                        )
                else:
                    message_parts.append(
                        f"  • {username} | 永久会员 | 线路: {line or 'AUTO'}"
                    )

        if emby_users:
            message_parts.append(f"\n📺 Emby Premium ({len(emby_users)} 人):")
            for user in emby_users:
                username = user["username"]
                expiry = user["expiry_time"]
                line = user.get("line", "未知")
                if expiry:
                    try:
                        expiry_dt = datetime.fromisoformat(str(expiry)).astimezone(
                            settings.TZ
                        )
                        days_left = (expiry_dt - datetime.now(settings.TZ)).days
                        expiry_str = expiry_dt.strftime("%Y-%m-%d")
                        if days_left <= 3:
                            status = f"⚠️ {days_left}天后到期"
                        else:
                            status = f"{days_left}天后到期"
                        message_parts.append(
                            f"  • {username} | {expiry_str} ({status}) | 线路: {line or 'AUTO'}"
                        )
                    except Exception:
                        message_parts.append(
                            f"  • {username} | 到期时间: {expiry} | 线路: {line or 'AUTO'}"
                        )
                else:
                    message_parts.append(
                        f"  • {username} | 永久会员 | 线路: {line or 'AUTO'}"
                    )

    if premium_debt_users:
        message_parts.extend(
            [
                "",
                "─" * 40,
                f"💳 Premium 流量欠额用户 (共 {len(premium_debt_users)} 人)",
                "─" * 40,
            ]
        )

        plex_debt_users = [u for u in premium_debt_users if u["service"] == "Plex"]
        emby_debt_users = [u for u in premium_debt_users if u["service"] == "Emby"]

        if plex_debt_users:
            message_parts.append("\n🎬 Plex 欠额:")
            for user in plex_debt_users:
                premium_status = "Premium" if user["is_premium"] else "非 Premium"
                message_parts.append(
                    f"  • {user['username']} | {premium_status} | "
                    f"累计欠额: {format_bytes(user['current_debt'])} | "
                    f"今日超出流量: {format_bytes(user['today_exceed_traffic'])} | "
                    f"预计结算后欠额: {format_bytes(user['projected_debt'])}"
                )

        if emby_debt_users:
            message_parts.append("\n📺 Emby 欠额:")
            for user in emby_debt_users:
                premium_status = "Premium" if user["is_premium"] else "非 Premium"
                message_parts.append(
                    f"  • {user['username']} | {premium_status} | "
                    f"累计欠额: {format_bytes(user['current_debt'])} | "
                    f"今日超出流量: {format_bytes(user['today_exceed_traffic'])} | "
                    f"预计结算后欠额: {format_bytes(user['projected_debt'])}"
                )

    message_parts.extend(["", "─" * 40])

    return "\n".join(message_parts)


async def get_and_send_premium_statistics():
    """
    获取Premium线路统计信息并发送给管理员
    """
    try:
        logger.info("开始获取Premium线路统计信息")

        # 获取线路流量统计数据
        stats = traffic_service.premium_line_statistics()

        # 获取 Premium 用户列表
        premium_users = premium_repository.get_all_active_premium_users()

        # 获取所有 Premium 流量欠额或预计结算后欠额用户
        premium_debt_users = premium_repository.get_all_premium_traffic_debt_users()

        if not stats and not premium_users and not premium_debt_users:
            logger.warning("未获取到 Premium 线路统计数据、用户数据和欠额数据")
            return

        # 格式化消息
        message = format_premium_statistics_message(
            stats, premium_users, premium_debt_users
        )

        # 发送给所有管理员
        admin_chat_ids = settings.TG_ADMIN_CHAT_ID
        if not admin_chat_ids:
            logger.warning("未配置管理员 ID，无法发送统计信息")
            return

        success_count = 0
        for admin_id in admin_chat_ids:
            try:
                # 转换为整数类型（如果是字符串）
                chat_id = int(admin_id) if isinstance(admin_id, str) else admin_id

                success = await send_message_by_url(
                    chat_id=chat_id, text=message, parse_mode="HTML"
                )

                if success:
                    success_count += 1
                    logger.info(f"成功发送 Premium 统计信息给管理员 {chat_id}")
                else:
                    logger.error(f"发送 Premium 统计信息给管理员 {chat_id} 失败")

            except Exception as e:
                logger.error(f"发送消息给管理员 {admin_id} 时发生错误: {e!s}")

        logger.info(
            f"Premium 统计信息发送完成，成功发送给 {success_count}/{len(admin_chat_ids)} 个管理员"
        )

    except Exception as e:
        logger.error(f"获取并发送 Premium 统计信息时出错: {e!s}")
