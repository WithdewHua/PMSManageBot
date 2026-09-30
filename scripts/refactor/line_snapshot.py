"""Freeze the external behavior surface of the five line-related domains.

The snapshot deliberately records only stable public behavior: route order and
endpoint names, scheduler job identities, Redis key/value literals and
notification text. Internal module paths and repository implementation names
are intentionally excluded so the promotion can move SQL without changing the
contract.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Any

from scripts.refactor.snapshot import _dump, build_snapshot

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src/app/domains"
DOMAIN_DIRS = ("lines", "custom_lines", "traffic", "premium", "media_access")
LEGACY_MIXIN_MEMBERS = {
    "LinesRepository": [
        "set_emby_line",
        "get_emby_line",
        "get_emby_user_with_binded_line",
        "set_plex_line",
        "get_plex_line",
        "get_plex_user_with_binded_line",
        "get_free_premium_lines",
        "set_free_premium_lines",
        "is_free_premium_line",
        "get_line_tags",
        "set_line_tags",
        "delete_line_tags",
        "get_all_line_tags",
        "check_line_schedule_unlock",
        "unlock_line_schedule_with_credit",
        "unlock_line_schedule",
        "create_line_schedule",
        "get_user_line_schedules",
        "update_line_schedule",
        "delete_line_schedule",
        "check_schedule_conflict",
        "get_current_active_schedule",
        "disable_schedules_by_line",
        "get_users_with_line_schedule",
    ],
    "TrafficRepository": [
        "create_line_traffic_entry",
        "bulk_create_line_traffic_entries",
        "get_premium_line_traffic_statistics",
        "get_user_daily_traffic",
        "get_plex_traffic_rank",
        "get_emby_traffic_rank",
        "aggregate_monthly_traffic_data",
        "cleanup_monthly_traffic_data",
        "update_traffic_username",
    ],
}
ROUTE_MARKERS = (
    "/line",
    "/traffic",
    "/premium",
    "/download",
    "/nsfw",
    "/custom",
)
JOB_MARKERS = (
    "line",
    "traffic",
    "premium",
    "custom",
    "download",
    "permission",
)
REDIS_MARKERS = (
    "user_info:",
    "user_defined_line",
    "last_user_defined_line",
    "plex_token",
    "emby_api_key",
    "stream_traffic",
    "traffic:",
)


def _source_files() -> list[Path]:
    return sorted(
        path
        for domain in DOMAIN_DIRS
        for path in (SOURCE_ROOT / domain).rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _string_literals() -> list[str]:
    values: set[str] = set()
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            value = node.value
            if any(marker in value for marker in REDIS_MARKERS):
                values.add(value)
    return sorted(values)


def _redis_expressions() -> list[dict[str, str]]:
    operations: set[tuple[str, str]] = set()
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            if node.func.attr not in {
                "get",
                "put",
                "set",
                "delete",
                "exists",
                "hget",
                "hset",
            }:
                continue
            receiver = ast.unparse(node.func.value)
            if not any(
                token in receiver.lower() for token in ("cache", "redis", "token")
            ):
                continue
            expression = ", ".join(
                [
                    *(ast.unparse(arg) for arg in node.args),
                    *(ast.unparse(keyword) for keyword in node.keywords),
                ]
            )
            operations.add((f"{receiver}.{node.func.attr}", expression))
    return [
        {"operation": operation, "expression": expression}
        for operation, expression in sorted(operations)
    ]


def _notification_literals() -> list[str]:
    values: set[str] = set()
    for path in _source_files():
        if path.name not in {
            "notifications.py",
            "router.py",
            "admin_router.py",
            "jobs.py",
            "service.py",
        }:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value.strip()
                if value and any(char >= "\u4e00" for char in value):
                    values.add(value)
    return sorted(values)


def _stable_routes(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "order": route["order"],
            "path": route["path"],
            "methods": route["methods"],
            "name": route["name"],
            "endpoint": route["endpoint"],
            "response_model": route["response_model"],
        }
        for route in snapshot["openapi"]["routes"]
        if any(marker in str(route["path"]) for marker in ROUTE_MARKERS)
    ]


def _stable_jobs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for job in snapshot["scheduler"]["jobs"]:
        haystack = " ".join(
            [
                str(job.get("func", "")),
                str(job.get("kwargs", {}).get("id", "")),
                str(job.get("kwargs", {}).get("name", "")),
            ]
        ).lower()
        if not any(marker in haystack for marker in JOB_MARKERS):
            continue
        jobs.append(
            {
                "executor": job.get("executor"),
                "args": job.get("args", []),
                "kwargs": job.get("kwargs", {}),
            }
        )
    return jobs


def build_line_snapshot() -> dict[str, Any]:
    snapshot = build_snapshot()
    return {
        "schema": 1,
        "routes": _stable_routes(snapshot),
        "scheduler_jobs": _stable_jobs(snapshot),
        "redis_literals": _string_literals(),
        "redis_expressions": _redis_expressions(),
        "notification_literals": _notification_literals(),
        "legacy_mixin_members": LEGACY_MIXIN_MEMBERS,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_dump(build_line_snapshot()), encoding="utf-8")


if __name__ == "__main__":
    main()
