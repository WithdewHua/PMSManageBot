"""Capture the blackjack behavior surfaces used by the promotion baseline."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from scripts.refactor.snapshot import _dump, build_snapshot

BLACKJACK_MARKERS = ("blackjack", "21点")


def _is_blackjack(value: Any) -> bool:
    return "blackjack" in str(value).lower() or "21点" in str(value)


def build_blackjack_snapshot() -> dict[str, Any]:
    snapshot = build_snapshot()
    routes = [
        route
        for route in snapshot["openapi"]["routes"]
        if _is_blackjack(route["path"]) or _is_blackjack(route["name"])
    ]
    paths = {
        path: value
        for path, value in snapshot["openapi"]["openapi"]["paths"].items()
        if _is_blackjack(path)
    }
    jobs = [
        job
        for job in snapshot["scheduler"]["jobs"]
        if _is_blackjack(job["func"]) or _is_blackjack(job["kwargs"].get("id"))
    ]
    public_methods = [
        method
        for method in snapshot["facade"]["public_methods"]
        if _is_blackjack(method)
    ]
    tables = [
        table
        for table in snapshot["metadata"]["tables"]
        if _is_blackjack(table["name"])
        or table["name"] in {"statistics", "luckywheel_free_spins", "wheel_stats"}
    ]
    imports = [
        {key: value for key, value in item.items() if key != "line"}
        for item in snapshot["references"]["imports"]
        if _is_blackjack(item.get("module")) or _is_blackjack(item.get("target"))
    ]
    strings = [
        {key: value for key, value in item.items() if key != "line"}
        for item in snapshot["references"]["strings"]
        if _is_blackjack(item.get("value"))
    ]
    return {
        "schema": 1,
        "routes": routes,
        "openapi_paths": paths,
        "scheduler_jobs": jobs,
        "facade_blackjack_methods": public_methods,
        "metadata_tables": tables,
        "blackjack_references": {"imports": imports, "strings": strings},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_dump(build_blackjack_snapshot()), encoding="utf-8")


if __name__ == "__main__":
    main()
