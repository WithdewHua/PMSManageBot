"""Produce a deterministic runtime and static behavior snapshot.

The command is intentionally read-only. It imports the legacy application only
for in-memory inspection: no scheduler is started and no database session is
opened. Use ``python -m scripts.refactor.snapshot --output snapshot.json``.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import importlib.util
import json
import re
from contextlib import ExitStack
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, type):
        return f"{value.__module__}.{value.__qualname__}"
    if callable(value):
        return f"{value.__module__}:{value.__qualname__}"
    if isinstance(value, dict):
        return {str(key): _json_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _route_snapshot(app: Any) -> dict[str, Any]:
    routes: list[dict[str, Any]] = []
    for order, route in enumerate(app.routes):
        methods = sorted(getattr(route, "methods", set()) or set())
        endpoint = getattr(route, "endpoint", None)
        response_model = getattr(route, "response_model", None)
        routes.append(
            {
                "order": order,
                "path": getattr(route, "path", None),
                "methods": methods,
                "name": getattr(route, "name", None),
                # Domain relocation changes module-qualified symbols but not
                # the callable behavior represented by the route.
                "endpoint": getattr(endpoint, "__name__", None),
                "response_model": getattr(response_model, "__name__", None),
            }
        )
    return {"openapi": app.openapi(), "routes": routes}


def _column_default(column: Any) -> Any:
    default = column.default or column.server_default
    if default is None:
        return None
    value = getattr(default, "arg", None)
    if callable(value):
        return f"{value.__module__}:{value.__qualname__}"
    return _json_value(value)


def _metadata_snapshot() -> dict[str, Any]:
    try:
        from app.model_registry import metadata
    except ModuleNotFoundError:
        from app.models.models import Base

        metadata = Base.metadata

    tables: list[dict[str, Any]] = []
    for table in sorted(metadata.tables.values(), key=lambda item: item.name):
        columns = []
        for column in table.columns:
            columns.append(
                {
                    "name": column.name,
                    "type": str(column.type),
                    "nullable": column.nullable,
                    "primary_key": column.primary_key,
                    "default": _column_default(column),
                    "autoincrement": _json_value(column.autoincrement),
                }
            )
        indexes = [
            {
                "name": index.name,
                "unique": index.unique,
                "columns": [column.name for column in index.columns],
                "expressions": [str(expression) for expression in index.expressions],
            }
            for index in sorted(table.indexes, key=lambda item: item.name or "")
        ]
        constraints = []
        for constraint in table.constraints:
            constraints.append(
                {
                    "type": type(constraint).__name__,
                    "name": constraint.name,
                    "columns": sorted(
                        column.name for column in getattr(constraint, "columns", [])
                    ),
                    "sqltext": str(getattr(constraint, "sqltext", "")),
                }
            )
        constraints.sort(key=_dump)
        tables.append(
            {
                "name": table.name,
                "columns": columns,
                "indexes": indexes,
                "constraints": constraints,
            }
        )
    return {"tables": tables}


def _normalize_job_value(value: Any, base_time: datetime) -> Any:
    if isinstance(value, datetime):
        return {"relative_seconds": round((value - base_time).total_seconds())}
    if isinstance(value, (date, Path)):
        return _json_value(value)
    if isinstance(value, dict):
        return {
            str(key): _normalize_job_value(item, base_time)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_normalize_job_value(item, base_time) for item in value]
    return _json_value(value)


class _RecordingScheduler:
    jobs: list[dict[str, Any]]

    def __init__(self) -> None:
        self.jobs = []

    def add_async_job(self, func: Any, *args: Any, **kwargs: Any) -> None:
        self._record("async", func, args, kwargs)

    def add_sync_job(self, func: Any, *args: Any, **kwargs: Any) -> None:
        self._record("sync", func, args, kwargs)

    def enable_named_persistent_tasks(self) -> None:
        return None

    def _record(
        self, executor: str, func: Any, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None:
        self.jobs.append(
            {
                "executor": executor,
                "func": f"{func.__module__}:{func.__qualname__}",
                "args": list(args),
                "kwargs": kwargs,
            }
        )


def _scheduler_snapshot(root: Path = ROOT) -> dict[str, Any]:
    from app import main

    try:
        from app import schedule
    except ImportError:
        schedule = None

    try:
        from app.core.config import settings
    except ModuleNotFoundError:
        from app.config import settings

    recorder = _RecordingScheduler()
    before = datetime(2020, 1, 1, tzinfo=settings.TZ)

    class FrozenDateTime:
        @staticmethod
        def now(tz: Any = None) -> datetime:
            return (
                before.astimezone(tz) if tz is not None else before.replace(tzinfo=None)
            )

    # Startup also restores jobs from live DB state. Record the hooks but never
    # call them: a snapshot must neither require nor mutate a database.
    with ExitStack() as stack:
        stack.enter_context(patch.object(main, "Scheduler", return_value=recorder))
        if schedule is not None:
            stack.enter_context(patch.object(schedule, "datetime", FrozenDateTime))
            stack.enter_context(
                patch.object(schedule, "ON_STARTUP", [lambda: None, lambda: None])
            )
        else:
            stack.enter_context(
                patch.object(
                    main,
                    "datetime",
                    type(
                        "FrozenModule",
                        (),
                        {"datetime": FrozenDateTime, "timedelta": timedelta},
                    ),
                )
            )
            stack.enter_context(
                patch("app.webapp.routers.activities.auction.restore_auction_schedules")
            )
            stack.enter_context(
                patch(
                    "app.webapp.routers.activities.blackjack.restore_blackjack_timeouts"
                )
            )
        main.add_init_scheduler_job()
    jobs = []
    for job in recorder.jobs:
        item = dict(job)
        item["args"] = _normalize_job_value(item["args"], before)
        item["kwargs"] = _normalize_job_value(item["kwargs"], before)
        jobs.append(item)
    return {
        "jobs": jobs,
        "restoration_hooks": [
            "restore_auction_schedules",
            "restore_blackjack_timeouts",
        ],
    }


async def _commands() -> list[dict[str, str]]:
    from app import main

    class Bot:
        def __init__(self) -> None:
            self.commands: list[Any] = []

        async def set_my_commands(self, commands: list[Any]) -> None:
            self.commands = commands

    class Application:
        def __init__(self) -> None:
            self.bot = Bot()

    application = Application()
    await main.set_bot_commands(application)
    return [
        {"command": item.command, "description": item.description}
        for item in application.bot.commands
    ]


def _bot_snapshot() -> dict[str, Any]:
    try:
        from app.bot.app import HANDLERS

        handlers = list(HANDLERS)
    except ModuleNotFoundError:
        from app.handlers import rank, start, status, user

        handlers = [
            handler
            for module in (rank, start, status, user)
            for name, handler in vars(module).items()
            if name.endswith("_handler")
        ]

    serialized = []
    for handler in handlers:
        callback = getattr(handler, "callback", None)
        callback_name = getattr(callback, "__name__", None)
        serialized.append(
            {
                # Module paths are intentionally omitted: B2 changes only the
                # registration location, not the command callback behavior.
                "name": f"{callback_name}_handler" if callback_name else None,
                "type": type(handler).__name__,
                "callback": callback_name,
                "commands": sorted(getattr(handler, "commands", set()) or set()),
            }
        )
    return {"handlers": serialized, "commands": asyncio.run(_commands())}


def _facade_snapshot() -> dict[str, Any]:
    from app.databases import db

    return {
        "public_methods": sorted(
            name
            for name in dir(db)
            if not name.startswith("_") and callable(getattr(db, name))
        )
    }


def _module_name(path: Path, root: Path) -> str:
    relative = path.relative_to(root / "src").with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_module(module: str, root: Path) -> bool:
    if not module:
        return False
    path = root / "src" / Path(*module.split("."))
    return path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()


def _resolve_import(module: str, root: Path) -> bool:
    if _resolve_module(module, root):
        return True
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _resolve_reference(value: str, root: Path) -> bool:
    module = value.split(":", 1)[0]
    parts = module.split(".")
    return any(
        _resolve_module(".".join(parts[:index]), root)
        for index in range(len(parts), 0, -1)
    )


def _static_reference_snapshot(root: Path) -> dict[str, Any]:
    modules = {
        _module_name(path, root): path for path in sorted((root / "src").rglob("*.py"))
    }
    imports: list[dict[str, Any]] = []
    strings: list[dict[str, Any]] = []
    recognized = {"setattr", "patch", "import_module", "run", "add_job"}
    for module, path in sorted(modules.items()):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        function_nodes = (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        function_ranges = {
            (node.lineno, getattr(node, "end_lineno", node.lineno))
            for node in function_nodes
        }

        def scope(line: int, ranges: set[tuple[int, int]] = function_ranges) -> str:
            return (
                "function"
                if any(start <= line <= end for start, end in ranges)
                else "module"
            )

        package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(
                        {
                            "module": module,
                            "line": node.lineno,
                            "scope": scope(node.lineno),
                            "kind": "import",
                            "target": alias.name,
                            "resolved": _resolve_import(alias.name, root),
                        }
                    )
            elif isinstance(node, ast.ImportFrom):
                target = node.module or ""
                if node.level:
                    prefix = package.split(".")[
                        : len(package.split(".")) - node.level + 1
                    ]
                    target = ".".join([*prefix, *target.split(".")]).rstrip(".")
                for alias in node.names:
                    imports.append(
                        {
                            "module": module,
                            "line": node.lineno,
                            "scope": scope(node.lineno),
                            "kind": "from",
                            "target": f"{target}.{alias.name}"
                            if target
                            else alias.name,
                            "module_target": target,
                            "resolved": _resolve_import(target, root),
                        }
                    )
            elif isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else ""
                if name not in recognized:
                    continue
                arguments: list[ast.AST] = []
                if node.args and name in {
                    "import_module",
                    "patch",
                    "setattr",
                    "run",
                    "add_job",
                }:
                    arguments.append(node.args[0])
                if name == "add_job":
                    arguments.extend(
                        keyword.value
                        for keyword in node.keywords
                        if keyword.arg == "func"
                    )
                for argument in arguments:
                    if not isinstance(argument, ast.Constant) or not isinstance(
                        argument.value, str
                    ):
                        continue
                    strings.append(
                        {
                            "module": module,
                            "line": node.lineno,
                            "scope": scope(node.lineno),
                            "kind": name,
                            "value": argument.value,
                            "resolved": bool(
                                re.match(
                                    r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*(?::[A-Za-z_]\w*)?$",
                                    argument.value,
                                )
                                and _resolve_reference(argument.value, root)
                            ),
                        }
                    )
    return {"imports": imports, "strings": strings}


def build_snapshot(root: Path = ROOT) -> dict[str, Any]:
    """Build a JSON-serializable snapshot without writing application state."""
    root = root.resolve()
    try:
        from app.api.app import app
    except ModuleNotFoundError:
        from app.webapp import app

    return {
        "schema": 1,
        "openapi": _route_snapshot(app),
        "metadata": _metadata_snapshot(),
        "scheduler": _scheduler_snapshot(root),
        "bot": _bot_snapshot(),
        "facade": _facade_snapshot(),
        "references": _static_reference_snapshot(root),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = _dump(build_snapshot())
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
