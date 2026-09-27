"""Capture the gift-pack behavior surfaces used by the promotion baseline."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from scripts.refactor.snapshot import _dump, build_snapshot

GIFT_PACK_MARKERS = ("gift_pack", "gift-pack", "礼包")

# 礼包读取的宽表列所在表（只读由架构允许，冻结以免搬迁中丢失读取路径）
RELATED_TABLES = {"statistics", "gift_pack", "gift_pack_user_state"}


def _is_gift_pack(value: Any) -> bool:
    text = str(value)
    return any(marker in text for marker in GIFT_PACK_MARKERS)


def _repository_members() -> list[str]:
    from app.domains.gift_pack.repository import GiftPackRepository

    return sorted(name for name in dir(GiftPackRepository) if not name.startswith("__"))


def build_gift_pack_snapshot() -> dict[str, Any]:
    snapshot = build_snapshot()
    routes = [
        route
        for route in snapshot["openapi"]["routes"]
        if _is_gift_pack(route["path"]) or _is_gift_pack(route["name"])
    ]
    paths = {
        path: value
        for path, value in snapshot["openapi"]["openapi"]["paths"].items()
        if _is_gift_pack(path)
    }
    jobs = [
        job
        for job in snapshot["scheduler"]["jobs"]
        if _is_gift_pack(job["func"]) or _is_gift_pack(job["kwargs"].get("id"))
    ]
    public_methods = [
        method
        for method in snapshot["facade"]["public_methods"]
        if _is_gift_pack(method)
    ]
    tables = [
        table
        for table in snapshot["metadata"]["tables"]
        if _is_gift_pack(table["name"]) or table["name"] in RELATED_TABLES
    ]
    imports = [
        {key: value for key, value in item.items() if key != "line"}
        for item in snapshot["references"]["imports"]
        if _is_gift_pack(item.get("module")) or _is_gift_pack(item.get("target"))
    ]
    strings = [
        {key: value for key, value in item.items() if key != "line"}
        for item in snapshot["references"]["strings"]
        if _is_gift_pack(item.get("value"))
    ]
    return {
        "schema": 1,
        "routes": routes,
        "openapi_paths": paths,
        "scheduler_jobs": jobs,
        "facade_gift_pack_methods": public_methods,
        "metadata_tables": tables,
        "repository_members": _repository_members(),
        "gift_pack_references": {"imports": imports, "strings": strings},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_dump(build_gift_pack_snapshot()), encoding="utf-8")


if __name__ == "__main__":
    main()
