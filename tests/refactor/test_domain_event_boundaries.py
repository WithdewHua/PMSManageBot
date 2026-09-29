from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_subscribe_is_only_called_by_application_assembly() -> None:
    violations: list[Path] = []
    for path in (ROOT / "src/app").rglob("*.py"):
        if path == ROOT / "src/app/core/events.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "subscribe"
                and path != ROOT / "src/app/subscriptions.py"
            ):
                violations.append(path)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "subscribe"
                and path != ROOT / "src/app/subscriptions.py"
            ):
                violations.append(path)
    assert violations == []


def test_domain_event_module_has_no_domain_imports() -> None:
    path = ROOT / "src/app/core/events.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(
                not alias.name.startswith("app.domains.") for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("app.domains.")
