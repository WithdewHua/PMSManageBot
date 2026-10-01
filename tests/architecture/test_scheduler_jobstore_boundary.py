"""Scheduler has no direct database engine or ORM access."""

import ast
import tomllib

from tests.architecture.helpers import PROJECT_ROOT

CONTRACT_NAME = "Database engine import scope"


def _allowed_importers(text: str) -> set[str]:
    contracts = tomllib.loads(text)["tool"]["importlinter"]["contracts"]
    return next(
        set(contract["allowed_importers"])
        for contract in contracts
        if contract["name"] == CONTRACT_NAME
    )


def test_scheduler_does_not_import_database_engine() -> None:
    current = (PROJECT_ROOT / "pyproject.toml").read_text()
    allowed = _allowed_importers(current)
    assert "app.core.scheduler" not in allowed
    assert "app.core.*" not in allowed


def test_scheduler_has_no_database_or_orm_imports() -> None:
    source = PROJECT_ROOT / "src/app/core/scheduler.py"
    tree = ast.parse(source.read_text())
    assert not any(
        (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (node.module.startswith("sqlalchemy") or node.module == "app.core.db")
        )
        or (
            isinstance(node, ast.Import)
            and any(
                alias.name.startswith("sqlalchemy") or alias.name == "app.core.db"
                for alias in node.names
            )
        )
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    )
    core_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "app.core"
    ]
    for ci in core_imports:
        for alias in ci.names:
            assert alias.name != "db"
