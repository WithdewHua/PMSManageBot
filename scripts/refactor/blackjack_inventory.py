"""Inventory blackjack facade/model/error/side-effect boundaries."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "app"
OUTPUT = ROOT / "scripts" / "refactor" / "blackjack_inventory.json"


def _path_text(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _role(path: str, kind: str) -> str:
    if kind in {
        "value_error_raise",
        "value_error_handler",
        "domain_error_raise",
    }:
        return "blackjack.errors"
    if kind == "side_effect":
        return "blackjack.service"
    if kind == "model_import":
        return "blackjack.repository"
    if kind == "facade_call":
        if "/jobs/" in path:
            return "blackjack.service"
        if "/router/" in path:
            return "blackjack.service"
        return "blackjack.service"
    return "blackjack.service"


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        if isinstance(node.func.value, ast.Name):
            return f"{node.func.value.id}.{node.func.attr}"
        if isinstance(node.func.value, ast.Attribute):
            return f"{ast.unparse(node.func.value)}.{node.func.attr}"
    return None


def inventory(root: Path = SOURCE) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    side_effect_names = {
        "add_async_job",
        "add_sync_job",
        "schedule_named_task",
        "send_message",
        "send_message_by_url",
        "notify_tournament_started",
        "_broadcast_group",
        "_send_many",
    }
    for path in sorted(root.rglob("*.py")):
        relative = _path_text(path)
        module = ".".join(path.relative_to(ROOT / "src").with_suffix("").parts)
        if module.endswith(".__init__"):
            module = module.removesuffix(".__init__")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except SyntaxError:
            continue
        in_blackjack = "/blackjack/" in f"/{relative}/"
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and (
                    node.module.startswith("app.domains.blackjack")
                    or node.module in {"app.databases", "app.databases.db"}
                    or (in_blackjack and node.module.endswith(".models"))
                )
            ):
                kind = (
                    "model_import"
                    if node.module.startswith("app.domains.blackjack.models")
                    else "facade_import"
                )
                entries.append(
                    {
                        "kind": kind,
                        "path": relative,
                        "line": node.lineno,
                        "symbol": node.module,
                        "target_role": _role(relative, kind),
                    }
                )
            if isinstance(node, ast.Call):
                name = _call_name(node)
                if not name:
                    continue
                is_db_call = name.startswith("db.") and (
                    in_blackjack or "blackjack" in name
                )
                if is_db_call:
                    entries.append(
                        {
                            "kind": "facade_call",
                            "path": relative,
                            "line": node.lineno,
                            "symbol": name,
                            "target_role": _role(relative, "facade_call"),
                        }
                    )
                if name.startswith("blackjack_service."):
                    entries.append(
                        {
                            "kind": "service_call",
                            "path": relative,
                            "line": node.lineno,
                            "symbol": name,
                            "target_role": "blackjack.service",
                        }
                    )
                if in_blackjack and (
                    name.split(".")[-1] in side_effect_names
                    or name == "background_tasks.add_task"
                    or any(token in name.lower() for token in ("notify", "schedule"))
                ):
                    entries.append(
                        {
                            "kind": "side_effect",
                            "path": relative,
                            "line": node.lineno,
                            "symbol": name,
                            "target_role": _role(relative, "side_effect"),
                        }
                    )
            if (
                in_blackjack
                and isinstance(node, ast.Raise)
                and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name)
                and node.exc.func.id in {"ValueError", "blackjack_error"}
            ):
                kind = (
                    "domain_error_raise"
                    if node.exc.func.id == "blackjack_error"
                    else "value_error_raise"
                )
                entries.append(
                    {
                        "kind": kind,
                        "path": relative,
                        "line": node.lineno,
                        "symbol": ast.unparse(node.exc),
                        "target_role": _role(relative, "value_error_raise"),
                    }
                )
            if (
                in_blackjack
                and isinstance(node, ast.ExceptHandler)
                and isinstance(node.type, ast.Name)
                and node.type.id == "ValueError"
            ):
                entries.append(
                    {
                        "kind": "value_error_handler",
                        "path": relative,
                        "line": node.lineno,
                        "symbol": "except ValueError",
                        "target_role": _role(relative, "value_error_handler"),
                    }
                )
    entries.sort(
        key=lambda item: (item["path"], item["line"], item["kind"], item["symbol"])
    )
    return {"schema_version": 1, "entries": entries, "total": len(entries)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = inventory()
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"total": result["total"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
