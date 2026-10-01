"""The B3 jobstore migration gets one narrowly scoped infrastructure DB edge."""

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


def test_scheduler_is_the_only_new_database_engine_importer() -> None:
    current = (PROJECT_ROOT / "pyproject.toml").read_text()
    importers = _allowed_importers(current)
    assert "app.core.scheduler" in importers
    assert "app.core.*" not in importers


def test_scheduler_accesses_only_the_jobstore_transaction_helper() -> None:
    source = PROJECT_ROOT / "src/app/core/scheduler.py"
    tree = ast.parse(source.read_text())
    assert not any(
        (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith("sqlalchemy")
        )
        or (
            isinstance(node, ast.Import)
            and any(alias.name.startswith("sqlalchemy") for alias in node.names)
        )
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    )
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "app.core"
    ]
    assert len(imports) == 1
    assert [(alias.name, alias.asname) for alias in imports[0].names] == [
        ("db", "core_db")
    ]
    rewrites = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "rewrite_job_references"
    ]
    assert len(rewrites) == 1
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "core_db"
        and node.func.attr == "rewrite_scheduler_rows"
        for node in ast.walk(rewrites[0])
    )
