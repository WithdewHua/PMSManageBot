"""Capture the luckywheel / treasure / prediction / auction behavior surfaces.

``promote-activity-domains`` promotes four sibling domains, so the frozen fixture
groups them by domain: OpenAPI routes and paths, scheduler jobs, the facade mixin
members (each with its reviewed destination), owned metadata tables, and the
cross-domain references the promotion must not lose.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from scripts.refactor.snapshot import _dump, build_snapshot

#: 领域 → (路由/任务/文案用的标记, 归属的表, 需要登记的 mixin 类名)
DOMAINS: dict[str, dict[str, Any]] = {
    "luckywheel": {
        "markers": ("luckywheel", "wheel", "转盘"),
        "tables": ("statistics", "luckywheel_free_spins", "wheel_stats"),
        "mixin": "LuckywheelRepository",
    },
    "treasure": {
        "markers": ("treasure", "夺宝"),
        "tables": ("statistics", "treasure_issue", "treasure_participation"),
        "mixin": "TreasureRepository",
    },
    "prediction": {
        "markers": ("prediction", "预言"),
        "tables": ("statistics", "prediction_market", "prediction_bet"),
        "mixin": "PredictionRepository",
    },
    "auction": {
        "markers": ("auction", "竞拍"),
        "tables": ("statistics", "auctions", "auction_bids"),
        "mixin": "AuctionRepository",
    },
}


def _matches(value: Any, markers: tuple[str, ...]) -> bool:
    text = str(value)
    return any(marker in text for marker in markers)


_MODULE_FOR = {spec["mixin"]: domain for domain, spec in DOMAINS.items()}


def _mixin_members(mixin: str) -> list[str]:
    """该 mixin（含其组合的子主题 mixin）定义的成员名，按字母序。"""
    import importlib

    module = importlib.import_module(f"app.domains.{_MODULE_FOR[mixin]}.repository")
    cls = getattr(module, mixin)
    # 组合式 repository：成员分散在若干个 ``_XxxRepositoryPart`` mixin 上
    names: set[str] = set()
    for base in cls.__mro__:
        if base.__module__.startswith(f"app.domains.{_MODULE_FOR[mixin]}."):
            names.update(vars(base))
    return sorted(name for name in names if not name.startswith("__"))


def _module_functions(domain: str) -> list[str]:
    """repository 包暴露的模块级公开函数（luckywheel 的账本 helper 就在这里）。"""
    import ast

    root = (
        Path(__file__).resolve().parents[2] / "src/app/domains" / domain / "repository"
    )
    paths = sorted(root.glob("*.py")) if root.is_dir() else [root.with_suffix(".py")]
    names: set[str] = set()
    for path in paths:
        if not path.is_file():
            continue
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not (
                node.name.startswith("_")
            ):
                names.add(node.name)
    return sorted(names)


def _named_tasks() -> list[dict[str, Any]]:
    """具名任务注册表（含映射到 identity 的条目），冻结后搬迁不得改 id。"""
    from app import schedule

    return [
        {"task_id": task_id, "mapped": bool(schedule.TASKS.get(task_id))}
        for task_id in sorted(schedule.TASKS)
    ]


def build_activity_snapshot() -> dict[str, Any]:
    snapshot = build_snapshot()
    sections: dict[str, Any] = {}
    for domain, spec in DOMAINS.items():
        markers = spec["markers"]
        routes = [
            route
            for route in snapshot["openapi"]["routes"]
            if _matches(route["path"], markers) or _matches(route["name"], markers)
        ]
        paths = {
            path: value
            for path, value in snapshot["openapi"]["openapi"]["paths"].items()
            if _matches(path, markers)
        }
        jobs = [
            job
            for job in snapshot["scheduler"]["jobs"]
            if _matches(job["func"], markers)
            or _matches(job["kwargs"].get("id"), markers)
            or _matches(job["kwargs"].get("name"), markers)
        ]
        facade_methods = sorted(
            method
            for method in snapshot["facade"]["public_methods"]
            if _matches(method, markers)
        )
        tables = [
            table
            for table in snapshot["metadata"]["tables"]
            if table["name"] in spec["tables"]
        ]
        imports = [
            {key: value for key, value in item.items() if key != "line"}
            for item in snapshot["references"]["imports"]
            if _matches(item.get("module"), markers)
            or _matches(item.get("target"), markers)
        ]
        strings = [
            {key: value for key, value in item.items() if key != "line"}
            for item in snapshot["references"]["strings"]
            if _matches(item.get("value"), markers)
        ]
        sections[domain] = {
            "routes": routes,
            "openapi_paths": paths,
            "scheduler_jobs": jobs,
            "facade_methods": facade_methods,
            "metadata_tables": tables,
            "repository_members": _mixin_members(spec["mixin"]),
            "repository_functions": _module_functions(domain),
            "references": {"imports": imports, "strings": strings},
        }
    return {
        "schema": 1,
        "domains": sections,
        "named_tasks": _named_tasks(),
        "legacy_task_refs": sorted(
            __import__(
                "scripts.migrate_legacy_job_refs", fromlist=["LEGACY_TASK_REFS"]
            ).LEGACY_TASK_REFS
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_dump(build_activity_snapshot()), encoding="utf-8")


if __name__ == "__main__":
    main()
