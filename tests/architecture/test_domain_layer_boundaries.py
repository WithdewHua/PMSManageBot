"""Architecture checks verifying entry points and services do not import models or db."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
assert (ROOT / "src/app").is_dir()


def test_account_and_invitation_entry_points_do_not_import_legacy_facade_or_models() -> (
    None
):
    """Accounts and invitation entry points must not touch data layer directly."""
    roots = (
        ROOT / "src/app/domains/accounts",
        ROOT / "src/app/domains/invitation",
    )
    layers = {"router.py", "admin_router.py", "bot.py", "jobs.py", "service.py"}
    for path in sorted(
        path for root in roots for path in root.rglob("*.py") if path.name in layers
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    not alias.name.startswith(("app.databases", "sqlalchemy"))
                    for alias in node.names
                ), path
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(
                    ("app.databases", "app.domains.identity.models", "sqlalchemy")
                ), path
