"""Line catalog database repository."""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.db import get_session
from app.core.kv import SystemConfig, upsert_tx
from app.core.log import logger
from app.domains.lines.models import LineCatalog


@dataclass(frozen=True)
class CatalogRow:
    id: int
    name: str
    kind: str
    position: int
    tags: str
    free_open: int


def get_all_catalog_entries() -> list[CatalogRow]:
    """Retrieve all catalog lines ordered by position."""
    with get_session() as session:
        stmt = select(LineCatalog).order_by(LineCatalog.position)
        rows = session.execute(stmt).scalars().all()
        return [
            CatalogRow(
                id=r.id,
                name=r.name,
                kind=r.kind,
                position=r.position,
                tags=r.tags,
                free_open=r.free_open,
            )
            for r in rows
        ]


def add_line_catalog_entry(name: str, kind: str) -> None:
    """Add a new line to the catalog at the end of its kind.

    Retries once on position collision under concurrent writes.
    """
    for attempt in range(2):
        try:
            with get_session() as session:
                existing = session.execute(
                    select(LineCatalog).where(LineCatalog.name == name)
                ).scalar_one_or_none()
                if existing:
                    if existing.kind == kind:
                        raise ValueError("该线路已存在")
                    raise ValueError("该线路已存在于另一线路列表中")

                max_pos = session.execute(
                    select(func.max(LineCatalog.position)).where(
                        LineCatalog.kind == kind
                    )
                ).scalar()
                next_pos = 0 if max_pos is None else max_pos + 1
                now = int(time.time())
                entry = LineCatalog(
                    name=name,
                    kind=kind,
                    position=next_pos,
                    tags="[]",
                    free_open=0,
                    created_at=now,
                    updated_at=now,
                )
                session.add(entry)
            return
        except IntegrityError as error:
            error_str = str(error).lower()
            if "uq_line_catalog_name" in error_str or "line_catalog.name" in error_str:
                with get_session() as check_session:
                    other = check_session.execute(
                        select(LineCatalog).where(LineCatalog.name == name)
                    ).scalar_one_or_none()
                    if other and other.kind != kind:
                        raise ValueError("该线路已存在于另一线路列表中") from error
                    raise ValueError("该线路已存在") from error
            if attempt < 1:
                logger.warning(
                    "并发新增线路 position 冲突，重试分配: name=%s kind=%s",
                    name,
                    kind,
                )
                time.sleep(random.uniform(0.02, 0.08))
                continue
            raise


def delete_line_catalog_entry(name: str, kind: str) -> bool:
    """Delete a line from the catalog."""
    with get_session() as session:
        row = session.execute(
            select(LineCatalog).where(
                LineCatalog.name == name,
                LineCatalog.kind == kind,
            )
        ).scalar_one_or_none()
        if not row:
            raise ValueError("该线路不存在")
        session.delete(row)
        return True


def set_line_catalog_tags(name: str, tags: list[str]) -> bool:
    """Update tags for an existing line in the catalog."""
    with get_session() as session:
        row = session.execute(
            select(LineCatalog).where(LineCatalog.name == name)
        ).scalar_one_or_none()
        if not row:
            return False
        row.tags = json.dumps(tags, ensure_ascii=False)
        row.updated_at = int(time.time())
        return True


def delete_line_catalog_tags(name: str) -> bool:
    """Clear tags for an existing line in the catalog."""
    with get_session() as session:
        row = session.execute(
            select(LineCatalog).where(LineCatalog.name == name)
        ).scalar_one_or_none()
        if not row:
            return False
        row.tags = "[]"
        row.updated_at = int(time.time())
        return True


def set_free_premium_catalog_lines(names: list[str]) -> bool:
    """Set free-open flag on premium lines atomically."""
    with get_session() as session:
        premium_rows = (
            session.execute(
                select(LineCatalog)
                .where(LineCatalog.kind == "premium")
                .order_by(LineCatalog.id)
                .with_for_update()
            )
            .scalars()
            .all()
        )
        premium_names = {r.name for r in premium_rows}
        desired = set(names)
        if desired - premium_names:
            logger.warning(
                "设置免费高级线路失败，包含非高级线路: %s", desired - premium_names
            )
            return False
        now = int(time.time())
        for r in premium_rows:
            new_val = 1 if r.name in desired else 0
            if r.free_open != new_val:
                r.free_open = new_val
                r.updated_at = now
        logger.info("设置免费高级线路成功，共 %s 条线路", len(names))
        return True


def import_legacy_line_catalog_tx(
    session,
    *,
    normal_lines: list[str],
    premium_lines: list[str],
    tags_map: dict[str, list[str]],
    free_premium_set: set[str],
    now: int,
) -> bool:
    """Import legacy line catalog from .env lists and kv rows into database."""
    imported = session.execute(
        select(SystemConfig).where(
            SystemConfig.config_type == "lines",
            SystemConfig.config_key == "catalog_imported",
        )
    ).scalar_one_or_none()
    if imported:
        return False

    seen_names: set[str] = set()
    final_normal: list[str] = []
    for name in normal_lines:
        if name in seen_names:
            logger.warning("线路目录导入：跳过普通线路中的重复项 '%s'", name)
            continue
        seen_names.add(name)
        final_normal.append(name)

    final_premium: list[str] = []
    for name in premium_lines:
        if name in seen_names:
            if name in final_normal:
                logger.warning(
                    "线路目录导入：跳过高级线路中与普通线路重名的项 '%s'", name
                )
            else:
                logger.warning("线路目录导入：跳过高级线路中的重复项 '%s'", name)
            continue
        seen_names.add(name)
        final_premium.append(name)

    all_catalog_names = set(final_normal) | set(final_premium)

    for line_name in tags_map:
        if line_name not in all_catalog_names:
            logger.warning("线路目录导入：跳过不存在线路的标签 '%s'", line_name)

    for line_name in free_premium_set:
        if line_name in final_normal:
            logger.warning("线路目录导入：跳过普通线路上的免费标记 '%s'", line_name)
        elif line_name not in final_premium:
            logger.warning("线路目录导入：跳过不存在线路的免费标记 '%s'", line_name)

    for pos, name in enumerate(final_normal):
        tags = tags_map.get(name, [])
        entry = LineCatalog(
            name=name,
            kind="normal",
            position=pos,
            tags=json.dumps(tags, ensure_ascii=False),
            free_open=0,
            created_at=now,
            updated_at=now,
        )
        session.add(entry)

    for pos, name in enumerate(final_premium):
        tags = tags_map.get(name, [])
        is_free = 1 if name in free_premium_set else 0
        entry = LineCatalog(
            name=name,
            kind="premium",
            position=pos,
            tags=json.dumps(tags, ensure_ascii=False),
            free_open=is_free,
            created_at=now,
            updated_at=now,
        )
        session.add(entry)

    session.execute(
        sql_delete(SystemConfig).where(
            SystemConfig.config_type.in_(["line_tag", "free_premium_line"])
        )
    )

    marker_data = {
        "imported_at": now,
        "normal_count": len(final_normal),
        "premium_count": len(final_premium),
    }
    upsert_tx(
        session,
        "lines",
        "catalog_imported",
        json.dumps(marker_data, ensure_ascii=False),
    )
    logger.info(
        "线路目录导入完成：普通线路 %d 条，高级线路 %d 条",
        len(final_normal),
        len(final_premium),
    )
    return True


def import_legacy_line_catalog(
    *,
    normal_lines: list[str],
    premium_lines: list[str],
    tags_map: dict[str, list[str]],
    free_premium_set: set[str],
    now: int,
) -> bool:
    """Execute line catalog import in a complete transaction."""
    with get_session() as session:
        return import_legacy_line_catalog_tx(
            session,
            normal_lines=normal_lines,
            premium_lines=premium_lines,
            tags_map=tags_map,
            free_premium_set=free_premium_set,
            now=now,
        )


__all__ = [
    "CatalogRow",
    "add_line_catalog_entry",
    "delete_line_catalog_entry",
    "delete_line_catalog_tags",
    "get_all_catalog_entries",
    "import_legacy_line_catalog",
    "import_legacy_line_catalog_tx",
    "set_free_premium_catalog_lines",
    "set_line_catalog_tags",
]
