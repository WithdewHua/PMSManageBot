"""Application workflows for custom lines.

The service layer coordinates repository transactions and post-commit side
 effects.  It deliberately does not import SQLAlchemy, sessions, or ORM models.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.core.config import settings
from app.core.log import logger
from app.domains.custom_lines import notifications, repository, rules
from app.domains.donation import service as donation_service
from app.integrations.telegram.messaging import send_message_by_url
from app.integrations.telegram.profiles import get_user_name_from_tg_id


async def _unbind(domain: str, reason: str) -> int:
    from app.domains.lines.service import unbind_specified_line_for_all_users

    try:
        success, count = await unbind_specified_line_for_all_users(domain, reason)
        if success:
            return int(count or 0)
    except Exception:
        logger.exception("解绑线路 %s 用户失败", domain)
    return 0


async def _notify_schedules(
    domain: str, reason: str, affected: list[dict[str, Any]]
) -> None:
    for item in affected:
        service_name = "Emby" if item["service"] == "emby" else "Plex"
        try:
            await send_message_by_url(
                chat_id=item["tg_id"],
                text=(
                    "\n⚠️ 线路调度变更通知\n\n"
                    f"线路：`{domain}`\n"
                    f"原因：{reason}\n\n"
                    f"您的 {item['schedule_count']} 个 {service_name} 线路调度已被自动禁用。\n\n"
                    "如需继续使用该线路，请在管理面板中重新启用调度或选择其他线路。\n"
                ),
                parse_mode="markdownv2",
            )
        except Exception as error:
            logger.warning("发送线路调度通知给用户 %s 失败: %s", item["tg_id"], error)


async def _post_transition(result: dict[str, Any], *, unbind_reason: str) -> int:
    domain = result["line"]["domain"]
    count = await _unbind(domain, unbind_reason)
    await _notify_schedules(
        domain,
        result.get("reason", unbind_reason),
        result.get("affected_schedules", []),
    )
    return count


def _safe_username(tg_id: int) -> str:
    try:
        return get_user_name_from_tg_id(tg_id)
    except Exception:
        return str(tg_id)


def _validate_common(data: Any) -> str | None:
    if data.traffic_type not in ("one_way", "two_way"):
        return "无效的流量类型"
    if data.traffic_limit is not None and data.traffic_limit > data.total_traffic:
        return (
            f"分享限制 ({data.traffic_limit}GB) 不能大于总流量 ({data.total_traffic}GB)"
        )
    return None


async def submit_custom_line(data: Any, tg_id: int, *, now: int) -> dict[str, Any]:
    error = _validate_common(data)
    if error:
        return {"ok": False, "message": error}
    expires_at = (
        None
        if data.is_permanent or not data.valid_days
        else now + data.valid_days * 86400
    )
    try:
        line = repository.submit_line(
            {
                "tg_id": tg_id,
                "domain": data.domain,
                "network_info": data.network_info,
                "price_monthly": data.price_monthly,
                "price_yearly": data.price_yearly,
                "traffic_limit": data.traffic_limit,
                "traffic_type": data.traffic_type,
                "total_traffic": data.total_traffic,
                "valid_days": data.valid_days,
                "is_permanent": int(data.is_permanent),
                "status": "pending",
                "user_note": data.user_note,
                "expires_at": expires_at,
                "created_at": now,
                "updated_at": now,
            }
        )
    except ValueError as error:
        return {"ok": False, "message": str(error)}

    user_name = _safe_username(tg_id)
    price = []
    if data.price_monthly:
        price.append(f"月付: ¥{data.price_monthly}")
    if data.price_yearly:
        price.append(f"年付: ¥{data.price_yearly}")
    traffic = []
    if data.traffic_limit:
        traffic.append(f"月限 {data.traffic_limit}GB")
    if data.total_traffic:
        traffic.append(f"总量 {data.total_traffic}GB")
    message = (
        "🛣️ 新的自定义线路提交\n\n"
        f"👤 提交用户: {user_name} (ID: {tg_id})\n"
        f"🌐 域名: {data.domain}\n"
        f"📡 网络情况: {data.network_info}\n"
        f"💰 价格: {' / '.join(price) if price else '未提供'}\n"
        f"📊 流量: {' | '.join(traffic)} ({data.traffic_type})\n"
        f"⏰ 有效期: {'长期可用' if data.is_permanent else f'{data.valid_days}天'}\n"
        f"📝 备注: {data.user_note or '无'}\n\n"
    )
    for admin_id in settings.TG_ADMIN_CHAT_ID:
        try:
            await send_message_by_url(chat_id=admin_id, text=message)
        except Exception as error:
            logger.warning("发送自定义线路提交通知失败: %s", error)
    return {
        "ok": True,
        "line": line,
        "message": f"自定义线路 '{data.domain}' 提交成功，请等待管理员审核",
    }


def get_my_custom_lines(tg_id: int) -> list[dict[str, Any]]:
    return repository.list_user_lines(tg_id)


def get_approved_custom_lines() -> list[dict[str, Any]]:
    return repository.list_approved_lines()


def get_custom_line_detail(line_id: int) -> dict[str, Any] | None:
    return repository.get_line(line_id)


def update_custom_line(
    data: Any, line_id: int, tg_id: int, *, now: int
) -> dict[str, Any]:
    values = data.model_dump(exclude_unset=True)
    try:
        line = repository.update_line(line_id, values, owner_tg_id=tg_id)
    except (LookupError, PermissionError, ValueError) as error:
        return {"ok": False, "message": str(error)}
    return {"ok": True, "line": line, "message": "更新成功"}


async def approve_custom_line(
    data: Any, line_id: int, admin_id: int, admin_username: str | None
) -> dict[str, Any]:
    try:
        result = repository.approve_line(
            line_id,
            admin_id=admin_id,
            action=data.action,
            admin_note=data.admin_note,
            valid_days=data.valid_days,
            is_permanent=data.is_permanent,
        )
    except (LookupError, ValueError) as error:
        return {"ok": False, "message": str(error)}
    line = result
    submitter_id = line["tg_id"]
    if data.action == "approve":
        traffic = f"{line['traffic_limit']} GB" if line["traffic_limit"] else "无限制"
        expiry = "长期可用" if line["is_permanent"] else f"{line['valid_days']}天"
        text = (
            "✅ 您的自定义线路已通过审核\n\n"
            f"🌐 域名: {line['domain']}\n"
            f"📊 流量限制: {traffic}\n"
            f"⏰ 有效期: {expiry}\n"
        )
        if data.admin_note:
            text += f"\n📝 管理员备注: {data.admin_note}"
        channel_text = (
            "🎉 新线路上线通知\n\n"
            f"🌐 线路: {line['domain']}\n"
            f"🌍 网络信息: {line['network_info'] or '未提供'}\n"
            f"📊 流量限制: {traffic}\n"
            f"⏰ 有效期: {expiry}\n\n"
            f"感谢 {_safe_username(submitter_id)} 分享线路！"
        )
        await _send_optional(submitter_id, text)
        if settings.TG_CHANNEL_ID:
            await _send_optional(settings.TG_CHANNEL_ID, channel_text)
        return {"ok": True, "line": line, "message": f"已批准线路: {line['domain']}"}
    text = f"❌ 您的自定义线路未通过审核\n\n🌐 域名: {line['domain']}\n"
    if data.admin_note:
        text += f"\n📝 拒绝原因: {data.admin_note}"
    await _send_optional(submitter_id, text)
    return {"ok": True, "line": line, "message": f"已拒绝线路: {line['domain']}"}


async def _send_optional(chat_id: int | str, text: str) -> None:
    try:
        await send_message_by_url(chat_id=chat_id, text=text)
    except Exception as error:
        logger.warning("发送自定义线路通知失败: %s", error)


async def admin_update_custom_line(data: Any, line_id: int) -> dict[str, Any]:
    try:
        line = repository.update_line(line_id, data.model_dump(exclude_unset=True))
    except (LookupError, ValueError) as error:
        return {"ok": False, "message": str(error)}
    if line.get("status") == "offline" and "transition_reason" in line:
        await _unbind(line["domain"], "已被管理员下线")
        await _notify_schedules(
            line["domain"],
            line.get("transition_reason", "线路已下线"),
            line["affected_schedules"],
        )
    return {"ok": True, "line": line, "message": "更新成功"}


async def offline_custom_line(
    line_id: int, *, owner_tg_id: int | None, reason: str
) -> dict[str, Any]:
    line = repository.get_line(line_id)
    if line is None:
        return {"ok": False, "message": "线路不存在"}
    if owner_tg_id is not None and line["tg_id"] != owner_tg_id:
        return {"ok": False, "message": "无权下线此线路"}
    try:
        result = repository.transition_offline(line_id, reason=reason)
    except (LookupError, ValueError) as error:
        return {"ok": False, "message": str(error)}
    count = await _post_transition(result, unbind_reason=reason)
    result["unbind_count"] = count
    return {
        "ok": True,
        "line": result["line"],
        "unbind_count": count,
        "message": f"线路 {result['line']['domain']} 已下线",
    }


async def online_custom_line(
    data: Any, line_id: int, owner_tg_id: int
) -> dict[str, Any]:
    current = repository.get_line(line_id)
    if current is None:
        return {"ok": False, "message": "线路不存在"}
    if current["tg_id"] != owner_tg_id:
        return {"ok": False, "message": "无权上线此线路"}
    try:
        line = repository.transition_online(
            line_id, data.model_dump(exclude_unset=True)
        )
    except (LookupError, ValueError) as error:
        return {"ok": False, "message": str(error)}
    expire_info = (
        "长期可用"
        if line["is_permanent"]
        else datetime.fromtimestamp(line["expires_at"], tz=settings.TZ).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        if line["expires_at"]
        else "未设置"
    )
    if settings.TG_CHANNEL_ID:
        await _send_optional(
            settings.TG_CHANNEL_ID,
            f"🎉 线路重新上线通知\n\n🌐 线路: {line['domain']}\n🌍 网络信息: {line['network_info'] or '未提供'}\n📊 流量限制: {line['traffic_limit'] or '无限制'} GB\n⏰ 有效期: {expire_info}\n\n线路由 {_safe_username(owner_tg_id)} 重新上线！感谢分享！",
        )
    return {
        "ok": True,
        "line": line,
        "message": f"线路 {line['domain']} 已上线\n流量限制: {line['traffic_limit'] or '无限制'} GB\n过期时间: {expire_info}",
    }


async def renew_custom_line(
    line_id: int, valid_days: int, owner_tg_id: int
) -> dict[str, Any]:
    try:
        result = repository.renew_line(line_id, valid_days, owner_tg_id=owner_tg_id)
    except (LookupError, PermissionError, ValueError) as error:
        return {"ok": False, "message": str(error)}
    old = result["old_expires_at"]
    new = result["line"]["expires_at"]
    fmt = lambda value: (
        datetime.fromtimestamp(value, tz=settings.TZ).strftime("%Y-%m-%d %H:%M:%S")
        if value
        else "未设置"
    )
    return {
        "ok": True,
        "line": result["line"],
        "message": f"续期成功！延长 {valid_days} 天\n原过期时间: {fmt(old)}\n新过期时间: {fmt(new)}",
    }


async def delete_custom_line(
    line_id: int, *, owner_tg_id: int | None, is_admin: bool = False
) -> dict[str, Any]:
    line = repository.get_line(line_id)
    if line is None:
        return {"ok": False, "message": "线路不存在"}
    if is_admin or line["status"] in ("offline", "expired"):
        await settle_custom_line_traffic(
            line_domain=line["domain"], force_current_month=True
        )
    try:
        deleted = repository.delete_line(
            line_id, owner_tg_id=None if is_admin else owner_tg_id
        )
    except (LookupError, PermissionError, ValueError) as error:
        return {"ok": False, "message": str(error)}
    count = 0
    if line["status"] == "approved":
        count = await _unbind(line["domain"], "已被管理员删除")
    await _send_optional(
        line["tg_id"],
        f"⚠️ 您的自定义线路已被{'管理员' if is_admin else '用户'}删除\n\n🌐 域名: {deleted['domain']}\n\n如有疑问，请联系管理员。",
    )
    return {
        "ok": True,
        "line": deleted,
        "unbind_count": count,
        "message": "删除成功" if not is_admin else f"已删除线路: {deleted['domain']}",
    }


async def set_custom_line_tags(line_id: int, tags: list[str]) -> dict[str, Any]:
    try:
        line = repository.set_tags(line_id, tags)
    except LookupError as error:
        return {"ok": False, "message": str(error)}
    return {
        "ok": True,
        "line": line,
        "message": "已更新线路标签",
        "data": {"tags": tags},
    }


async def _send_expiring_soon_notifications(
    lines: list[dict[str, Any]], current_time: int
) -> None:
    logger.info("找到 %s 条即将过期的自定义线路", len(lines))
    for line in lines:
        if (
            line["expiry_notified_at"] is not None
            and line["expiry_notified_at"] >= line["expires_at"] - 86400
        ):
            continue
        remaining = round((line["expires_at"] - current_time) / 3600, 1)
        text = (
            "⏰ 自定义线路即将过期提醒\n\n"
            f"域名：{line['domain']}\n网络情况：{line['network_info']}\n"
            f"过期时间：{datetime.fromtimestamp(line['expires_at'], tz=settings.TZ):%Y-%m-%d %H:%M:%S}\n"
            f"剩余时间：约 {remaining} 小时\n\n⚠️ 过期后线路将自动下线并解绑所有用户\n请及时在个人中心续期以继续使用"
        )
        try:
            await send_message_by_url(
                chat_id=line["tg_id"], text=text, disable_notification=False
            )
            repository.mark_expiry_notified(line["id"], current_time)
        except Exception as error:
            logger.error("发送即将过期提醒失败 (线路 %s): %s", line["domain"], error)


async def process_expired_lines(current_time: int) -> list[dict[str, Any]]:
    results = repository.expire_lines(current_time)
    for result in results:
        count = await _post_transition(result, unbind_reason="已过期")
        result["unbind_count"] = count
        await _send_optional(
            result["line"]["tg_id"],
            f"📢 自定义线路过期通知\n\n您提交的自定义线路已过期：\n域名：{result['line']['domain']}\n网络情况：{result['line']['network_info']}\n\n线路已自动下线并解绑所有用户\n您可以在个人中心续期或删除该线路",
        )
    return results


async def check_custom_line_traffic() -> list[dict[str, Any]]:
    results = await repository.check_traffic()
    for result in results:
        line = result["line"]
        if result["kind"] == "offline":
            await _post_transition(result, unbind_reason="流量已用尽")
            await _send_optional(
                line["tg_id"],
                f"⚠️ 自定义线路流量超限通知\n\n域名：{line['domain']}\n当月流量：{result['actual_traffic']:.2f}GB\n流量限制：{line['traffic_limit']}GB\n\n线路已自动下线并解绑所有用户\n下月 1 号将自动恢复使用",
            )
        else:
            await _send_optional(
                line["tg_id"],
                f"✅ 自定义线路已恢复上线\n\n域名: {line['domain']}\n当月流量: {result['actual_traffic']:.2f}GB\n流量限制: {line['traffic_limit']}GB\n\n用户现在可以重新绑定此线路",
            )
            if settings.TG_CHANNEL_ID:
                await _send_optional(
                    settings.TG_CHANNEL_ID,
                    f"🎉 线路恢复上线通知\n\n🌐 线路: {line['domain']}\n线路流量已重置，现已恢复上线！",
                )
    return results


async def settle_custom_line_traffic(
    line_domain: str | None = None, force_current_month: bool = False
) -> None:
    now = datetime.now(tz=settings.TZ)
    current_month = rules.month_key(now, settings.TZ)
    previous_month = rules.month_key(
        datetime(now.year, now.month, 1, tzinfo=settings.TZ) - timedelta(days=1),
        settings.TZ,
    )
    months = (
        [(current_month, True), (previous_month, False)]
        if force_current_month
        else [(previous_month, False)]
    )
    details, failures = await repository.settle_lines(
        months=months,
        line_domain=line_domain,
        donation_multiplier=donation_service.get_donation_multiplier(),
        now=now,
    )
    for detail in details:
        await _send_optional(
            detail["tg_id"],
            f"💰 自定义线路流量结算通知\n\n线路域名：{detail['domain']}\n结算月份：{detail['month']}\n消耗流量：{detail['traffic_gb']:.2f}GB (单向)\n获得积分：{detail['credits']:.2f}\n\n感谢您的分享，积分已自动发放到您的账户 🎉",
        )
    if details and not line_domain and settings.TG_ADMIN_CHAT_ID:
        await _send_admin_settlement_summary(
            current_month,
            details,
            len(details),
            sum(item["credits"] for item in details),
        )
    if failures:
        logger.error("自建线路结算失败列表: %s", failures)


# Kept as a small compatibility alias for callers from the pre-promotion tree.
def _is_line_valid(line: Any, current_time: int) -> bool:
    return (
        rules.is_line_valid(line["is_permanent"], line["expires_at"], current_time)
        if isinstance(line, dict)
        else rules.is_line_valid(line.is_permanent, line.expires_at, current_time)
    )


_send_admin_settlement_summary = notifications._send_admin_settlement_summary


def list_approved_domains() -> list[str]:
    """List domains of approved custom lines for traffic classification."""
    return repository.list_approved_domains()
