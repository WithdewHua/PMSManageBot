"""Persistent invite budgets, audit decisions and explicitly verified bootstrap."""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from dataclasses import dataclass
from typing import cast

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core import kv
from app.core.config import settings
from app.core.db import get_session
from app.domains.luckywheel import config as quota_config
from app.domains.luckywheel import exceptions as errors
from app.domains.luckywheel import rules
from app.domains.luckywheel.models import (
    WheelInviteAudit,
    WheelInviteQuotaWeek,
    WheelStats,
)
from app.domains.luckywheel.schemas import LuckyWheelConfig, LuckyWheelItem

WEEK_MS = 7 * 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class QuotaContext:
    now_ms: int
    week_start_ms: int
    global_limit: int
    personal_limit: int
    fallback: list[LuckyWheelItem]
    randomness: dict


def unavailable() -> errors.LuckywheelError:
    return errors.LuckywheelError(
        "luckywheel.unavailable",
        "转盘暂不可用，请稍后再试",
        status_code=503,
        payload={"detail": "转盘暂不可用，请稍后再试"},
    )


def _config_tx(session, *, seed: bool = False) -> quota_config.InviteQuotaConfigModel:
    raw = kv.get_tx(
        session, quota_config.CONFIG_TYPE, quota_config.INVITE_QUOTA_CONFIG_KEY
    )
    if raw is None and seed:
        # Defaults are safe only before any quota state has ever been recorded.
        # Administrative reads or repeated initialization must not repair lost
        # restrictive settings with permissive defaults.
        if (
            session.scalar(select(WheelInviteQuotaWeek.week_start_ms).limit(1))
            is not None
            or session.scalar(select(WheelInviteAudit.id).limit(1)) is not None
        ):
            raise unavailable()
        default = quota_config.InviteQuotaConfigModel()
        raw = kv.insert_if_absent_tx(
            session,
            quota_config.CONFIG_TYPE,
            quota_config.INVITE_QUOTA_CONFIG_KEY,
            default.model_dump_json(),
        )
    if raw is None:
        raise unavailable()
    try:
        document = json.loads(raw)
        if not isinstance(document, dict) or set(document) != {
            "global_weekly_limit",
            "personal_weekly_limit",
        }:
            raise ValueError("incomplete quota document")
        return quota_config.InviteQuotaConfigModel.model_validate(document)
    except (TypeError, ValueError) as error:
        raise unavailable() from error


def get_config() -> dict:
    with get_session() as session:
        return _config_tx(session, seed=True).model_dump()


def prepare_tx(
    session: Session, config: LuckyWheelConfig, *, randomness: dict | None = None
) -> QuotaContext:
    """Capture one period and authoritative quota snapshot before any spin effects."""
    now_ms = int(time.time() * 1000)
    week = rules.natural_week_start_ms(now_ms, settings.TZ)
    try:
        fallback = rules.non_invite_items(config.items)
    except ValueError as error:
        raise unavailable() from error
    baseline = session.scalar(
        select(WheelInviteQuotaWeek.week_start_ms).where(
            WheelInviteQuotaWeek.is_baseline.is_(True)
        )
    )
    if baseline is None or baseline > week:
        raise unavailable()
    limits = _config_tx(session)
    options = (
        randomness
        if randomness is not None
        else quota_config.RANDOMNESS_CONFIG.get_tx(session).model_dump()
    )
    return QuotaContext(
        now_ms,
        week,
        limits.global_weekly_limit,
        limits.personal_weekly_limit,
        fallback,
        options,
    )


def reserve_tx(session: Session, context: QuotaContext, tg_id: int) -> dict:
    """Serialize invite candidates before reading personal usage, on both databases."""
    table = WheelInviteQuotaWeek
    dialect = session.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise unavailable()
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    session.execute(
        insert(table)
        .values(
            week_start_ms=context.week_start_ms,
            issued=0,
            initialized_at_ms=context.now_ms,
            is_baseline=False,
        )
        .on_conflict_do_nothing(index_elements=["week_start_ms"])
    )
    # A real write establishes SQLite's writer lock too; FOR UPDATE alone does not.
    session.execute(
        update(WheelInviteQuotaWeek)
        .where(WheelInviteQuotaWeek.week_start_ms == context.week_start_ms)
        .values(issued=WheelInviteQuotaWeek.issued)
    )
    used = session.execute(
        select(WheelInviteQuotaWeek.issued).where(
            WheelInviteQuotaWeek.week_start_ms == context.week_start_ms
        )
    ).scalar_one()
    personal = int(
        session.execute(
            select(func.coalesce(func.sum(WheelInviteAudit.issued), 0)).where(
                WheelInviteAudit.week_start_ms == context.week_start_ms,
                WheelInviteAudit.tg_id == tg_id,
            )
        ).scalar_one()
    )
    global_blocked = used >= context.global_limit
    personal_blocked = personal >= context.personal_limit
    allowed = not (global_blocked or personal_blocked)
    if allowed:
        changed = session.execute(
            update(WheelInviteQuotaWeek)
            .where(
                WheelInviteQuotaWeek.week_start_ms == context.week_start_ms,
                WheelInviteQuotaWeek.issued < context.global_limit,
            )
            .values(issued=WheelInviteQuotaWeek.issued + 1)
        )
        if cast(CursorResult, changed).rowcount != 1:
            raise unavailable()
        used += 1
    return {
        "allowed": allowed,
        "global_blocked": global_blocked,
        "personal_blocked": personal_blocked,
        "global_used_after": used,
    }


def record_tx(
    session: Session,
    *,
    context: QuotaContext,
    decision: dict,
    record: WheelStats,
    candidate_name: str,
    privileged: bool,
) -> None:
    session.add(
        WheelInviteAudit(
            wheel_stats_id=record.id,
            week_start_ms=context.week_start_ms,
            tg_id=record.tg_id,
            issued=int(decision["allowed"]),
            source=record.source,
            candidate_name=candidate_name,
            final_name=record.item_name,
            global_blocked=decision["global_blocked"],
            personal_blocked=decision["personal_blocked"],
            global_limit=context.global_limit,
            personal_limit=context.personal_limit,
            global_used_after=decision["global_used_after"],
            recorded_at_ms=context.now_ms,
            historical=False,
            privileged=privileged if decision["allowed"] else None,
        )
    )
    session.flush()


def _report_tx(session, *, now_ms: int) -> dict:
    week = rules.natural_week_start_ms(now_ms, settings.TZ)
    records = session.execute(
        select(
            WheelStats.id,
            WheelStats.tg_id,
            WheelStats.item_name,
            WheelStats.timestamp,
            WheelStats.source,
        )
        .where(
            WheelStats.timestamp >= week // 1000,
            WheelStats.timestamp < (week + WEEK_MS) // 1000,
        )
        .order_by(WheelStats.id)
    ).all()
    all_rows = [dict(row._mapping) for row in records]
    if any(row["timestamp"] > now_ms // 1000 for row in all_rows):
        raise ValueError("本周统计含未来时间记录，请先核对历史数据")
    encoded = json.dumps(
        {"week_start_ms": week, "rows": all_rows},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    rows = [
        row for row in all_rows if rules.prize_effects(row["item_name"]).invite_codes
    ]
    users = Counter(row["tg_id"] for row in rows)
    names = Counter(row["item_name"] for row in all_rows)
    return {
        "version": 1,
        "week_start_ms": week,
        "week_end_ms": week + WEEK_MS,
        "cutoff_ms": now_ms,
        "digest": hashlib.sha256(encoded).hexdigest(),
        "scanned_count": len(all_rows),
        "issued": len(rows),
        "rows": rows,
        "users": [
            {"tg_id": tg_id, "issued": count} for tg_id, count in sorted(users.items())
        ],
        "prize_counts": dict(sorted(names.items())),
        "warning": "统计不是发码关联账本；必须核实完整性和历史奖项语义，未知或缺失时停止启用。",
    }


def initialization_report(*, now_ms: int | None = None) -> dict:
    with get_session() as session:
        return _report_tx(
            session, now_ms=int(now_ms if now_ms is not None else time.time() * 1000)
        )


def initialize(
    report: dict,
    *,
    history_verified: bool,
    writers_stopped: bool,
    now_ms: int | None = None,
) -> dict:
    """Apply an approved report once, never issue codes or change existing usage."""
    if not history_verified or not writers_stopped:
        raise ValueError("必须确认历史核对完成并停止全部旧版抽奖写入者")
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    week = rules.natural_week_start_ms(now, settings.TZ)
    if report.get("version") != 1 or report.get("week_start_ms") != week:
        raise ValueError("报告版本或自然周已变化，请重新生成并核对报告")
    with get_session() as session:
        existing = session.scalar(
            select(WheelInviteQuotaWeek).where(
                WheelInviteQuotaWeek.is_baseline.is_(True)
            )
        )
        if existing is not None:
            if existing.week_start_ms != week or existing.baseline_digest != report.get(
                "digest"
            ):
                raise ValueError("已存在其他初始化基线，禁止覆盖")
            current = _report_tx(session, now_ms=now)
            recorded = session.scalars(
                select(WheelInviteAudit).where(
                    WheelInviteAudit.week_start_ms == week,
                    WheelInviteAudit.issued > 0,
                )
            ).all()
            by_id = {row.wheel_stats_id: row for row in recorded}
            consistent = set(by_id) == {row["id"] for row in current["rows"]}
            consistent = (
                consistent and sum(row.issued for row in recorded) == existing.issued
            )
            for row in current["rows"]:
                audit = by_id.get(row["id"])
                consistent = (
                    consistent
                    and audit is not None
                    and (
                        audit.tg_id == row["tg_id"]
                        and audit.final_name == row["item_name"]
                        and audit.source == row["source"]
                    )
                )
            if not consistent:
                raise ValueError("历史发码与账本不一致，禁止沿用初始化基线")
            return {
                "already_initialized": True,
                "week_start_ms": week,
                "issued": existing.issued,
            }
        fresh = _report_tx(session, now_ms=now)
        if fresh["digest"] != report.get("digest") or fresh["rows"] != report.get(
            "rows"
        ):
            raise ValueError("历史记录或报告内容已变化，请重新生成并核对报告")
        _config_tx(session, seed=True)
        baseline = WheelInviteQuotaWeek(
            week_start_ms=week,
            issued=fresh["issued"],
            initialized_at_ms=now,
            is_baseline=True,
            baseline_digest=fresh["digest"],
            baseline_cutoff_ms=now,
        )
        session.add(baseline)
        session.flush()
        for row in fresh["rows"]:
            session.add(
                WheelInviteAudit(
                    wheel_stats_id=row["id"],
                    week_start_ms=week,
                    tg_id=row["tg_id"],
                    issued=1,
                    source=row["source"],
                    candidate_name=row["item_name"],
                    final_name=row["item_name"],
                    global_blocked=False,
                    personal_blocked=False,
                    historical=True,
                    recorded_at_ms=row["timestamp"] * 1000,
                    privileged=None,
                )
            )
        session.flush()
        return {
            "already_initialized": False,
            "week_start_ms": week,
            "issued": baseline.issued,
        }


def get_stats(*, week_start_ms: int | None = None) -> dict:
    now = int(time.time() * 1000)
    week = (
        rules.natural_week_start_ms(now, settings.TZ)
        if week_start_ms is None
        else int(week_start_ms)
    )
    try:
        if week < 0 or rules.natural_week_start_ms(week, settings.TZ) != week:
            raise ValueError("invalid week")
    except (OverflowError, OSError) as error:
        raise ValueError("invalid week") from error
    with get_session() as session:
        limits = _config_tx(session, seed=True)
        baseline = session.scalar(
            select(WheelInviteQuotaWeek.week_start_ms).where(
                WheelInviteQuotaWeek.is_baseline.is_(True)
            )
        )
        used = session.scalar(
            select(WheelInviteQuotaWeek.issued).where(
                WheelInviteQuotaWeek.week_start_ms == week
            )
        )
        rows = session.scalars(
            select(WheelInviteAudit).where(WheelInviteAudit.week_start_ms == week)
        ).all()
        users: Counter = Counter()
        sources: Counter = Counter()
        for row in rows:
            if row.issued:
                users[row.tg_id] += row.issued
                sources[row.source] += row.issued
        exhausted = [
            row.recorded_at_ms
            for row in rows
            if not row.historical
            and row.issued
            and (
                row.global_limit is not None
                and row.global_used_after is not None
                and row.global_used_after >= row.global_limit
            )
        ]
        return {
            "initialized": baseline is not None and baseline <= week,
            "week_start_ms": week,
            "week_end_ms": week + WEEK_MS,
            "global_used": int(used or 0),
            "global_limit": limits.global_weekly_limit,
            "personal_limit": limits.personal_weekly_limit,
            "historical_issued": sum(row.issued for row in rows if row.historical),
            "new_issued": sum(row.issued for row in rows if not row.historical),
            "global_blocked_count": sum(bool(row.global_blocked) for row in rows),
            "personal_blocked_count": sum(bool(row.personal_blocked) for row in rows),
            "both_blocked_count": sum(
                bool(row.global_blocked and row.personal_blocked) for row in rows
            ),
            "first_exhausted_at_ms": min(exhausted) if exhausted else None,
            "users": [
                {"tg_id": tg_id, "issued": count}
                for tg_id, count in sorted(users.items())
            ],
            "sources": [
                {"source": source, "issued": count}
                for source, count in sorted(
                    sources.items(), key=lambda item: item[0] or ""
                )
            ],
        }
