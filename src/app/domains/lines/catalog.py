"""Line catalog storage adapter.

Line catalog is stored in the `line_catalog` database table with an in-process
read cache (TTL 30s) invalidated on local writes.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from threading import Lock

from app.core.log import logger
from app.domains.lines.repository import catalog as repository_catalog
from app.domains.lines.repository.catalog import CatalogRow


@dataclass(frozen=True)
class _CachedCatalog:
    items: tuple[CatalogRow, ...]
    cached_at: float


_cache: _CachedCatalog | None = None
_cache_lock = Lock()
_cache_generation = 0
CACHE_TTL: float = 30.0


def invalidate_cache() -> None:
    global _cache, _cache_generation
    with _cache_lock:
        _cache = None
        _cache_generation += 1


def _get_items() -> tuple[CatalogRow, ...]:
    global _cache
    while True:
        with _cache_lock:
            cached = _cache
            if cached is not None and (time.monotonic() - cached.cached_at) < CACHE_TTL:
                return cached.items
            generation = _cache_generation
        entries = tuple(repository_catalog.get_all_catalog_entries())
        with _cache_lock:
            # A committed write invalidated this in-flight read. Never publish
            # its stale snapshot after invalidation; reload the committed data.
            if generation != _cache_generation:
                continue
            _cache = _CachedCatalog(items=entries, cached_at=time.monotonic())
            return entries


def normal_lines() -> list[str]:
    return [r.name for r in _get_items() if r.kind == "normal"]


def premium_lines() -> list[str]:
    return [r.name for r in _get_items() if r.kind == "premium"]


def free_premium_lines() -> list[str]:
    return [r.name for r in _get_items() if r.kind == "premium" and r.free_open == 1]


def line_tags(name: str) -> list[str]:
    for r in _get_items():
        if r.name == name:
            try:
                parsed = json.loads(r.tags)
                return list(parsed) if isinstance(parsed, list) else []
            except Exception:
                return []
    return []


def all_line_tags() -> dict[str, list[str]]:
    items = _get_items()
    normals = [r for r in items if r.kind == "normal"]
    premiums = [r for r in items if r.kind == "premium"]
    result: dict[str, list[str]] = {}
    for r in normals + premiums:
        try:
            parsed = json.loads(r.tags)
            result[r.name] = list(parsed) if isinstance(parsed, list) else []
        except Exception:
            result[r.name] = []
    return result


def add_line(name: str, *, premium: bool) -> None:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("线路名称不能为空")
    if "/" in cleaned or "," in cleaned:
        raise ValueError("线路名称不能包含 / 或 ,")

    kind = "premium" if premium else "normal"
    for r in _get_items():
        if r.name == cleaned:
            if r.kind == kind:
                raise ValueError("该线路已存在")
            raise ValueError("该线路已存在于另一线路列表中")

    repository_catalog.add_line_catalog_entry(cleaned, kind)
    invalidate_cache()


def delete_line(name: str, *, premium: bool) -> None:
    kind = "premium" if premium else "normal"
    repository_catalog.delete_line_catalog_entry(name, kind)
    invalidate_cache()


def set_line_tags(name: str, tags: list[str]) -> bool:
    normalized: list[str] = []
    seen = set()
    for raw_tag in tags:
        parts = raw_tag.split(",") if "," in raw_tag else [raw_tag]
        for part in parts:
            cleaned = part.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                normalized.append(cleaned)

    ok = repository_catalog.set_line_catalog_tags(name, normalized)
    if ok:
        invalidate_cache()
    return ok


def delete_line_tags(name: str) -> bool:
    ok = repository_catalog.delete_line_catalog_tags(name)
    if ok:
        invalidate_cache()
    return ok


def set_free_premium_lines(names: list[str]) -> bool:
    try:
        ok = repository_catalog.set_free_premium_catalog_lines(names)
        if ok:
            invalidate_cache()
        return ok
    except Exception as error:
        logger.error("设置免费高级线路失败: %s", error)
        return False


def import_legacy_line_catalog_if_needed(
    legacy_source=None,
) -> bool:
    """Import legacy line catalog from .env and SystemConfig once."""
    from app.core import kv as core_kv
    from app.core.legacy_env import LegacyEnvSource

    if legacy_source is None:
        legacy_source = LegacyEnvSource(
            {
                "STREAM_BACKEND": [],
                "PREMIUM_STREAM_BACKEND": [],
            }
        )

    for key in sorted(legacy_source.present_keys()):
        logger.warning("业务配置键 %s 已迁出 .env，将以数据库配置为准", key)

    if core_kv.get("lines", "catalog_imported"):
        return False

    raw_normal = legacy_source.read("STREAM_BACKEND")
    raw_premium = legacy_source.read("PREMIUM_STREAM_BACKEND")

    raw_tags = core_kv.get_all("line_tag")
    tags_map = {
        line: [tag.strip() for tag in val.split(",") if tag.strip()]
        for line, val in raw_tags.items()
    }

    raw_free = core_kv.get_all("free_premium_line")
    free_set = {line for line, val in raw_free.items() if val == "1"}

    now = int(time.time())
    ok = repository_catalog.import_legacy_line_catalog(
        normal_lines=raw_normal,
        premium_lines=raw_premium,
        tags_map=tags_map,
        free_premium_set=free_set,
        now=now,
    )
    if ok:
        invalidate_cache()
    return ok


__all__ = [
    "add_line",
    "all_line_tags",
    "delete_line",
    "delete_line_tags",
    "free_premium_lines",
    "import_legacy_line_catalog_if_needed",
    "invalidate_cache",
    "line_tags",
    "normal_lines",
    "premium_lines",
    "set_free_premium_lines",
    "set_line_tags",
]
