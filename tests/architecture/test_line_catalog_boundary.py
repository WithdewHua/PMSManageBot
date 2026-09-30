"""Keep line-catalog storage behind the lines domain interface."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
SRC = ROOT / "src/app"


def _violations(source: str, path: str) -> list[str]:
    tree = ast.parse(source, filename=path)
    errors: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "settings"
            and node.attr in {"STREAM_BACKEND", "PREMIUM_STREAM_BACKEND"}
        ):
            errors.append(f"catalog settings read: {path}:{node.lineno}")
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in {"line_tag", "free_premium_line"}
        ):
            errors.append(f"catalog KV key: {path}:{node.lineno}")
    return errors


def test_non_lines_modules_do_not_read_line_catalog_storage() -> None:
    errors: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC).as_posix()
        if relative.startswith("domains/lines/"):
            continue
        errors.extend(_violations(path.read_text(encoding="utf-8"), relative))
    assert errors == []


def test_boundary_detector_rejects_catalog_reads() -> None:
    assert _violations("settings.STREAM_BACKEND", "example.py")
    assert _violations('core_kv.get("line_tag", "demo")', "example.py")
