"""Database boundary for the custom-lines domain.

All SQL and transaction ownership for custom lines lives here.  Callers receive
plain dictionaries so routers, jobs, and services do not retain ORM instances
while performing network side effects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.credits import repository as credits_repository
from app.domains.credits.types import CreditAccount
from app.domains.custom_lines import rules
from app.domains.custom_lines.models import CustomLine, CustomLineSettlement
from app.domains.identity.models import EmbyUser, PlexUser
from app.domains.lines.models import LineSchedule

_ACTIVE_DOMAIN_STATUSES = ("pending", "approved", "offline")


def line_to_dict(line: Any) -> dict[str, Any]:
    """Detach the public line representation from SQLAlchemy."""
    tags = line.tags
    if isinstance(tags, str):
        tags = [item.strip() for item in tags.split(",") if item.strip()]
    return {
        "id": int(line.id),
        "tg_id": int(line.tg_id),
        "domain": line.domain,
        "network_info": line.network_info,
        "price_monthly": line.price_monthly,
        "price_yearly": line.price_yearly,
        "traffic_limit": line.traffic_limit,
        "traffic_type": line.traffic_type,
        "valid_days": line.valid_days,
        "is_permanent": bool(line.is_permanent),
        "status": line.status,
        "auto_offline_reason": line.auto_offline_reason,
        "admin_note": line.admin_note,
        "user_note": line.user_note,
        "tags": tags or [],
        "approved_at": line.approved_at,
        "approved_by": line.approved_by,
        "expires_at": line.expires_at,
        "expiry_notified_at": line.expiry_notified_at,
        "created_at": line.created_at,
        "updated_at": line.updated_at,
        "total_traffic": line.total_traffic,
    }


def _get_tx(session, line_id: int, *, for_update: bool = False) -> CustomLine | None:
    statement = select(CustomLine).where(CustomLine.id == int(line_id))
    if for_update:
        statement = statement.with_for_update()
    return session.execute(statement).scalar_one_or_none()


def get_line(line_id: int) -> dict[str, Any] | None:
    with get_session() as session:
        line = _get_tx(session, line_id)
        return line_to_dict(line) if line else None


def list_user_lines(tg_id: int) -> list[dict[str, Any]]:
    with get_session() as session:
        lines = session.execute(
            select(CustomLine)
            .where(CustomLine.tg_id == int(tg_id))
            .order_by(CustomLine.created_at.desc())
        ).scalars()
        return [line_to_dict(line) for line in lines]


def list_approved_lines() -> list[dict[str, Any]]:
    with get_session() as session:
        lines = session.execute(
            select(CustomLine)
            .where(CustomLine.status == "approved")
            .order_by(CustomLine.domain.asc())
        ).scalars()
        return [line_to_dict(line) for line in lines]


def list_admin_lines(status: str | None = None) -> list[dict[str, Any]]:
    with get_session() as session:
        statement = select(CustomLine)
        if status is not None:
            statement = statement.where(CustomLine.status == status)
        lines = session.execute(
            statement.order_by(CustomLine.created_at.desc())
        ).scalars()
        return [line_to_dict(line) for line in lines]


def _disable_schedules_tx(
    session, line_name: str, *, only_non_premium: bool = False
) -> list[dict[str, int | str]]:
    """Disable schedules in the caller's transaction and return notification data.

    New lines repositories expose this operation as a ``*_tx`` helper.  The
    direct fallback keeps this change usable on the pre-promotion tree without
    opening a second transaction.
    """
    schedules = (
        session.execute(
            select(LineSchedule).where(
                LineSchedule.line == line_name, LineSchedule.is_enabled == 1
            )
        )
        .scalars()
        .all()
    )
    if not schedules:
        return []

    premium_tg_ids: set[int] = set()
    if only_non_premium:
        tg_ids = {int(schedule.tg_id) for schedule in schedules}
        premium_tg_ids.update(
            session.execute(
                select(PlexUser.tg_id).where(
                    PlexUser.tg_id.in_(tg_ids), PlexUser.is_premium == 1
                )
            ).scalars()
        )
        premium_tg_ids.update(
            session.execute(
                select(EmbyUser.tg_id).where(
                    EmbyUser.tg_id.in_(tg_ids), EmbyUser.is_premium == 1
                )
            ).scalars()
        )

    affected: dict[tuple[int, str], int] = {}
    now = int(datetime.now(settings.TZ).timestamp())
    for schedule in schedules:
        if only_non_premium and schedule.tg_id in premium_tg_ids:
            continue
        schedule.is_enabled = 0
        schedule.updated_at = now
        key = (int(schedule.tg_id), schedule.service)
        affected[key] = affected.get(key, 0) + 1
    return [
        {"tg_id": tg_id, "service": service, "schedule_count": count}
        for (tg_id, service), count in affected.items()
    ]


def _new_line(values: dict[str, Any]) -> CustomLine:
    return CustomLine(**values)


def submit_line(values: dict[str, Any]) -> dict[str, Any]:
    with get_session() as session:
        duplicate = session.execute(
            select(CustomLine.id).where(
                CustomLine.domain == values["domain"],
                CustomLine.status.in_(_ACTIVE_DOMAIN_STATUSES),
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise ValueError(f"域名 '{values['domain']}' 已存在，请使用其他域名")
        line = _new_line(values)
        session.add(line)
        session.flush()
        return line_to_dict(line)


def update_line(
    line_id: int, values: dict[str, Any], *, owner_tg_id: int | None = None
) -> dict[str, Any]:
    with get_session() as session:
        line = _get_tx(session, line_id, for_update=True)
        if line is None:
            raise LookupError("线路不存在")
        if owner_tg_id is not None and int(line.tg_id) != int(owner_tg_id):
            raise PermissionError("无权修改此线路")
        if owner_tg_id is not None and line.status != "pending":
            raise ValueError(f"只能修改待审核的线路，当前状态: {line.status}")
        previous_status = line.status
        if values.get("domain") is not None:
            duplicate = session.execute(
                select(CustomLine.id).where(
                    CustomLine.domain == values["domain"],
                    CustomLine.id != int(line_id),
                    CustomLine.status.in_(_ACTIVE_DOMAIN_STATUSES),
                )
            ).scalar_one_or_none()
            if duplicate is not None:
                raise ValueError(f"域名 '{values['domain']}' 已被使用")
        for name, value in values.items():
            if value is not None:
                setattr(line, name, value)
        if line.traffic_type not in ("one_way", "two_way"):
            raise ValueError("无效的流量类型")
        if (
            line.traffic_limit is not None
            and line.total_traffic is not None
            and line.traffic_limit > line.total_traffic
        ):
            raise ValueError(
                f"分享限制 ({line.traffic_limit}GB) 不能大于总流量 ({line.total_traffic}GB)"
            )
        now = int(datetime.now(settings.TZ).timestamp())
        if "is_permanent" in values or "valid_days" in values:
            line.expires_at = (
                None
                if line.is_permanent
                else now + line.valid_days * 24 * 60 * 60
                if line.valid_days
                else None
            )
        line.updated_at = now
        snapshot = line_to_dict(line)
        if previous_status != "offline" and line.status == "offline":
            snapshot["affected_schedules"] = _disable_schedules_tx(session, line.domain)
            snapshot["transition_reason"] = "线路已被管理员下线"
        return snapshot


def approve_line(
    line_id: int,
    *,
    admin_id: int,
    action: str,
    admin_note: str | None,
    valid_days: int | None,
    is_permanent: bool | None,
) -> dict[str, Any]:
    with get_session() as session:
        line = _get_tx(session, line_id, for_update=True)
        if line is None:
            raise LookupError("线路不存在")
        if line.status != "pending":
            raise ValueError(f"只能审批待审核的线路，当前状态: {line.status}")
        if action not in ("approve", "reject"):
            raise ValueError("无效的操作")
        now = int(datetime.now(settings.TZ).timestamp())
        if action == "approve":
            line.status = "approved"
            line.approved_at = now
            line.approved_by = int(admin_id)
            if is_permanent is not None:
                line.is_permanent = int(is_permanent)
            if valid_days is not None:
                line.valid_days = valid_days
            line.expires_at = (
                None
                if line.is_permanent
                else now + line.valid_days * 24 * 60 * 60
                if line.valid_days
                else None
            )
        else:
            line.status = "rejected"
        if admin_note:
            line.admin_note = admin_note
        line.updated_at = now
        return line_to_dict(line)


def transition_offline(line_id: int, *, reason: str) -> dict[str, Any]:
    with get_session() as session:
        line = _get_tx(session, line_id, for_update=True)
        if line is None:
            raise LookupError("线路不存在")
        if line.status != "approved":
            raise ValueError(f"只能下线已批准的线路，当前状态: {line.status}")
        line.status = "offline"
        line.updated_at = int(datetime.now(settings.TZ).timestamp())
        affected = _disable_schedules_tx(session, line.domain)
        return {
            "line": line_to_dict(line),
            "affected_schedules": affected,
            "reason": reason,
        }


def transition_online(line_id: int, values: dict[str, Any]) -> dict[str, Any]:
    with get_session() as session:
        line = _get_tx(session, line_id, for_update=True)
        if line is None:
            raise LookupError("线路不存在")
        if line.status != "offline":
            raise ValueError(f"只能上线已下线的线路，当前状态: {line.status}")
        final_limit = values.get("traffic_limit", line.traffic_limit)
        final_total = values.get("total_traffic", line.total_traffic)
        if (
            final_limit is not None
            and final_total is not None
            and final_limit > final_total
        ):
            raise ValueError(
                f"分享限制 ({final_limit}GB) 不能大于总流量 ({final_total}GB)"
            )
        for name, value in values.items():
            if value is not None:
                setattr(line, name, value)
        now = int(datetime.now(settings.TZ).timestamp())
        if values.get("valid_days") is not None:
            line.is_permanent = 0
            line.expires_at = now + values["valid_days"] * 24 * 60 * 60
        elif values.get("is_permanent") is True:
            line.is_permanent = 1
            line.expires_at = None
        elif (
            values.get("is_permanent") is False
            and not line.is_permanent
            and line.valid_days
        ):
            line.expires_at = now + line.valid_days * 24 * 60 * 60
        line.status = "approved"
        line.auto_offline_reason = None
        line.updated_at = now
        return line_to_dict(line)


def renew_line(line_id: int, valid_days: int, *, owner_tg_id: int) -> dict[str, Any]:
    with get_session() as session:
        line = _get_tx(session, line_id, for_update=True)
        if line is None:
            raise LookupError("线路不存在")
        if int(line.tg_id) != int(owner_tg_id):
            raise PermissionError("无权续期此线路")
        if line.status not in ("approved", "expired"):
            raise ValueError(f"只能续期已批准或已过期的线路，当前状态: {line.status}")
        if line.is_permanent:
            raise ValueError("永久线路无需续期")
        now = int(datetime.now(settings.TZ).timestamp())
        old_expires_at = line.expires_at
        line.expires_at = max(line.expires_at or now, now) + valid_days * 24 * 60 * 60
        line.updated_at = now
        if line.status == "expired":
            line.status = "approved"
        return {"line": line_to_dict(line), "old_expires_at": old_expires_at}


def delete_line(line_id: int, *, owner_tg_id: int | None = None) -> dict[str, Any]:
    with get_session() as session:
        line = _get_tx(session, line_id, for_update=True)
        if line is None:
            raise LookupError("线路不存在")
        if owner_tg_id is not None and int(line.tg_id) != int(owner_tg_id):
            raise PermissionError("无权删除此线路")
        if owner_tg_id is not None and line.status == "approved":
            raise ValueError("不能直接删除已上线的线路，请先下线后再删除")
        result = line_to_dict(line)
        session.execute(
            delete(CustomLineSettlement).where(CustomLineSettlement.line_id == line.id)
        )
        session.delete(line)
        return result


def set_tags(line_id: int, tags: list[str]) -> dict[str, Any]:
    with get_session() as session:
        line = _get_tx(session, line_id, for_update=True)
        if line is None:
            raise LookupError("线路不存在")
        line.tags = tags or []
        line.updated_at = int(datetime.now(settings.TZ).timestamp())
        return line_to_dict(line)


def expiring_lines(now: int) -> list[dict[str, Any]]:
    with get_session() as session:
        lines = session.execute(
            select(CustomLine).where(
                CustomLine.status == "approved",
                CustomLine.is_permanent == 0,
                CustomLine.expires_at.isnot(None),
                CustomLine.expires_at > now,
                CustomLine.expires_at <= now + 24 * 60 * 60,
            )
        ).scalars()
        return [line_to_dict(line) for line in lines]


def mark_expiry_notified(line_id: int, notified_at: int) -> None:
    with get_session() as session:
        line = _get_tx(session, line_id, for_update=True)
        if line is not None:
            line.expiry_notified_at = int(notified_at)


def expire_lines(now: int) -> list[dict[str, Any]]:
    with get_session() as session:
        lines = (
            session.execute(
                select(CustomLine).where(
                    CustomLine.status == "approved",
                    CustomLine.is_permanent == 0,
                    CustomLine.expires_at.isnot(None),
                    CustomLine.expires_at <= now,
                )
            )
            .scalars()
            .all()
        )
        result = []
        for line in lines:
            line.status = "expired"
            line.updated_at = int(now)
            result.append(
                {
                    "line": line_to_dict(line),
                    "affected_schedules": _disable_schedules_tx(session, line.domain),
                    "reason": "用户分享线路已过期",
                }
            )
        return result


async def check_traffic() -> list[dict[str, Any]]:
    """Read traffic and atomically apply all resulting state transitions."""
    from app.domains.traffic import repository as traffic_repository

    now_dt = datetime.now(settings.TZ)
    current_month = now_dt.strftime("%Y-%m")
    now = int(now_dt.timestamp())
    with get_session() as session:
        lines = (
            session.execute(
                select(CustomLine).where(
                    CustomLine.status.in_(("approved", "offline")),
                    CustomLine.traffic_limit.isnot(None),
                    CustomLine.traffic_limit > 0,
                )
            )
            .scalars()
            .all()
        )
        transitions: list[dict[str, Any]] = []
        for line in lines:
            try:
                traffic_reader = getattr(
                    traffic_repository, "get_line_monthly_traffic", None
                )
                if traffic_reader is not None:
                    traffic_gb = await traffic_reader(
                        line.domain,
                        current_month,
                        owner_tg_id=None,
                        from_raw_table=True,
                    )
                else:
                    traffic_gb = await traffic_repository._get_line_monthly_traffic(
                        session,
                        line.domain,
                        current_month,
                        owner_tg_id=None,
                        from_raw_table=True,
                    )
            except Exception:
                logger.exception("检查线路 %s 流量失败，继续处理下一条", line.domain)
                continue
            actual = traffic_gb * 2 if line.traffic_type == "two_way" else traffic_gb
            if actual >= line.traffic_limit and line.status == "approved":
                line.status = "offline"
                line.auto_offline_reason = "traffic_exceeded"
                line.updated_at = now
                transitions.append(
                    {
                        "line": line_to_dict(line),
                        "actual_traffic": actual,
                        "kind": "offline",
                        "affected_schedules": _disable_schedules_tx(
                            session, line.domain
                        ),
                        "reason": "用户分享线路月流量已用尽",
                    }
                )
            elif (
                actual < line.traffic_limit
                and line.status == "offline"
                and line.auto_offline_reason == "traffic_exceeded"
                and rules.is_line_valid(line.is_permanent, line.expires_at, now)
            ):
                line.status = "approved"
                line.auto_offline_reason = None
                line.updated_at = now
                transitions.append(
                    {
                        "line": line_to_dict(line),
                        "actual_traffic": actual,
                        "kind": "online",
                        "affected_schedules": [],
                        "reason": "线路流量已重置，现已恢复上线",
                    }
                )
        return transitions


def _insert_settlement_tx(
    session,
    *,
    line: dict[str, Any],
    month: str,
    trigger: str,
    traffic_bytes: int,
    credits: float,
    created_at: int,
) -> int | None:
    existing = session.execute(
        select(CustomLineSettlement.id).where(
            CustomLineSettlement.line_id == int(line["id"]),
            CustomLineSettlement.year_month == month,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None
    row = CustomLineSettlement(
        line_id=int(line["id"]),
        tg_id=int(line["tg_id"]),
        domain=line["domain"],
        year_month=month,
        trigger=trigger,
        traffic_bytes=int(traffic_bytes),
        credits=float(credits),
        created_at=int(created_at),
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


async def settle_lines(
    *,
    months: list[tuple[str, bool]],
    line_domain: str | None,
    donation_multiplier: float,
    now: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Settle each line in an atomic line/ledger/credit transaction."""
    from app.domains.traffic import repository as traffic_repository

    details: list[dict[str, Any]] = []
    failures: list[str] = []
    for settle_month, from_raw_table in months:
        with get_session() as session:
            statement = select(CustomLine).where(
                CustomLine.total_traffic.isnot(None),
                CustomLine.total_traffic > 0,
                (
                    CustomLine.price_monthly.isnot(None)
                    | CustomLine.price_yearly.isnot(None)
                ),
            )
            if line_domain:
                statement = statement.where(CustomLine.domain == line_domain)
            lines = session.execute(statement).scalars().all()
            for orm_line in lines:
                line = line_to_dict(orm_line)
                try:
                    with session.begin_nested():
                        traffic_reader = getattr(
                            traffic_repository, "get_line_monthly_traffic", None
                        )
                        if traffic_reader is not None:
                            traffic_gb = await traffic_reader(
                                line["domain"],
                                settle_month,
                                owner_tg_id=line["tg_id"],
                                from_raw_table=from_raw_table,
                            )
                        else:
                            traffic_gb = (
                                await traffic_repository._get_line_monthly_traffic(
                                    session,
                                    line["domain"],
                                    settle_month,
                                    line["tg_id"],
                                    from_raw_table=from_raw_table,
                                )
                            )
                        already_settled = (
                            session.execute(
                                select(
                                    func.coalesce(
                                        func.sum(CustomLineSettlement.traffic_bytes), 0
                                    )
                                ).where(
                                    CustomLineSettlement.domain == line["domain"],
                                    CustomLineSettlement.year_month == settle_month,
                                )
                            ).scalar_one()
                            or 0
                        )
                        traffic_bytes = max(
                            0, int(float(traffic_gb) * 1024**3) - int(already_settled)
                        )
                        if traffic_bytes <= 0:
                            continue
                        monthly_price = line["price_monthly"]
                        if monthly_price is None:
                            monthly_price = float(line["price_yearly"]) / 12
                        traffic_gb_delta = traffic_bytes / 1024**3
                        credits = rules.settlement_credits(
                            traffic_gb_delta,
                            monthly_price=monthly_price,
                            total_traffic=line["total_traffic"],
                            traffic_type=line["traffic_type"],
                            donation_multiplier=donation_multiplier,
                        )
                        settlement_id = _insert_settlement_tx(
                            session,
                            line=line,
                            month=settle_month,
                            trigger="delete" if from_raw_table else "monthly",
                            traffic_bytes=traffic_bytes,
                            credits=credits,
                            created_at=int(now.timestamp()),
                        )
                        if settlement_id is None:
                            continue
                        credits_repository.add_tx(
                            session, CreditAccount.tg(line["tg_id"]), credits
                        )
                        details.append(
                            {
                                "domain": line["domain"],
                                "tg_id": line["tg_id"],
                                "traffic_gb": traffic_gb_delta,
                                "price_per_gb": rules.price_per_gb(
                                    monthly_price=monthly_price,
                                    total_traffic=line["total_traffic"],
                                    traffic_type=line["traffic_type"],
                                ),
                                "credits": credits,
                                "month": settle_month,
                            }
                        )
                except Exception as error:
                    logger.exception(
                        "线路 %s (%s) %s 结算失败",
                        line["domain"],
                        line["id"],
                        settle_month,
                    )
                    failures.append(f"{line['domain']} ({settle_month}): {error}")
    return details, failures


def delete_settlement_candidates(line_domain: str) -> dict[str, Any] | None:
    with get_session() as session:
        line = session.execute(
            select(CustomLine).where(CustomLine.domain == line_domain)
        ).scalar_one_or_none()
        return line_to_dict(line) if line else None


def list_approved_domains_tx(session: Any) -> list[str]:
    """List domains of custom lines with status 'approved' in caller transaction."""
    stmt = select(CustomLine.domain).where(CustomLine.status == "approved")
    return list(session.execute(stmt).scalars().all())


def list_approved_domains() -> list[str]:
    """List domains of custom lines with status 'approved' for traffic classification."""
    with get_session() as session:
        return list_approved_domains_tx(session)
