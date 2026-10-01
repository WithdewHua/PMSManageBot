"""Repositories must not perform Telegram profile/cache/network I/O."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
assert (ROOT / "src/app").is_dir()
REPOSITORY_ROOTS = [ROOT / "src/app/domains"]


def test_repository_tree_has_no_telegram_dependencies() -> None:
    violations = []
    paths = list((ROOT / "src/app/domains").rglob("repository.py"))
    paths.extend((ROOT / "src/app/domains").rglob("repository/**/*.py"))
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.Import):
                module = next((alias.name for alias in node.names), None)
            elif isinstance(node, ast.ImportFrom):
                module = node.module
            if module and (
                "telegram" in module or module.startswith(("app.core.cache", "redis"))
            ):
                violations.append((path.relative_to(ROOT).as_posix(), module))
    assert violations == []


def test_repository_outputs_keep_stable_ids_for_profile_enrichment() -> None:
    sources = []
    paths = list((ROOT / "src/app/domains").rglob("repository.py"))
    paths.extend((ROOT / "src/app/domains").rglob("repository/**/*.py"))
    for path in paths:
        sources.append(path.read_text(encoding="utf-8"))
    combined = "\n".join(sources)
    assert "get_user_name_from_tg_id" not in combined
    assert "load_tg_user_info_cache" not in combined
