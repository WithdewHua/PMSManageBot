"""Capture the accounts, identity, and invitation behavior surface.

The snapshot is intentionally read-only and deterministic. It freezes the public
HTTP routes, bot handlers, named scheduler task, legacy facade members, and the
module-level service/repository names that the account promotion must preserve.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from scripts.refactor.snapshot import _dump, build_snapshot

ROOT = Path(__file__).resolve().parents[2]
DOMAINS = {"accounts", "identity", "invitation"}
ROUTE_MARKERS = (
    "/api/user/bind/plex",
    "/api/user/bind/emby",
    "/api/invite/",
    "/api/admin/invite-codes/",
    "/api/admin/settings/plex-register",
    "/api/admin/settings/emby-register",
)
HANDLER_MARKERS = {
    "exchange",
    "register_status",
    "set_register",
    "create_overseerr",
}
SERVICE_MODULES = {
    "accounts": ROOT / "src/app/domains/accounts/service.py",
    "invitation": ROOT / "src/app/domains/invitation/service.py",
    "identity": ROOT / "src/app/domains/identity/service.py",
}
REPOSITORY_MODULES = {
    "identity": ROOT / "src/app/domains/identity/repository.py",
    "invitation": ROOT / "src/app/domains/invitation/repository.py",
}


def _public_functions(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sorted(
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    )


def _repository_members(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(
                    member, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and not member.name.startswith("_"):
                    names.add(member.name)
    return sorted(names)


def build_account_snapshot() -> dict[str, Any]:
    snapshot = build_snapshot()
    routes = [
        route
        for route in snapshot["openapi"]["routes"]
        if route["path"] in ROUTE_MARKERS
        or any(route["path"].startswith(marker) for marker in ROUTE_MARKERS)
    ]
    handlers = [
        handler
        for handler in snapshot["bot"]["handlers"]
        if handler["callback"] in HANDLER_MARKERS or handler["name"] in HANDLER_MARKERS
    ]
    jobs = [
        job
        for job in snapshot["scheduler"]["jobs"]
        if any(
            marker in str(job.get("func", ""))
            or marker in str(job.get("kwargs", {}).get("id", ""))
            for marker in ("plex", "emby", "invite", "overseerr", "register")
        )
    ]
    facade_methods = sorted(
        name
        for name in snapshot["facade"]["public_methods"]
        if name.startswith(
            (
                "get_plex_",
                "get_emby_",
                "get_stats_",
                "get_overseerr_",
                "add_plex",
                "add_emby",
                "add_user_data",
                "add_overseerr",
                "add_invitation",
                "update_invitation",
                "verify_invitation",
                "delete_plex",
            )
        )
    )
    from app import schedule

    return {
        "schema": 1,
        "routes": routes,
        "bot_handlers": handlers,
        "scheduler_jobs": jobs,
        "facade_methods": facade_methods,
        "service_functions": {
            domain: _public_functions(path) for domain, path in SERVICE_MODULES.items()
        },
        "repository_functions": {
            domain: _repository_members(path)
            for domain, path in REPOSITORY_MODULES.items()
        },
        "named_tasks": [
            {
                "task_id": task_id,
                "registered": task_id in schedule.TASKS,
            }
            for task_id in sorted(schedule.TASKS)
            if "invitation" in task_id
        ],
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_dump(build_account_snapshot()), encoding="utf-8")


if __name__ == "__main__":
    main()
