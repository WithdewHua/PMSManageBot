"""Read-model repositories aggregate data but cannot mutate domain state."""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRITE_OPERATIONS = {
    "update",
    "insert",
    "delete",
    "add",
    "add_all",
    "merge",
    "flush",
    "commit",
    "bulk_save_objects",
    "bulk_insert_mappings",
    "bulk_update_mappings",
}


def write_violations(source: str) -> list[str]:
    tree = ast.parse(source)
    models = set()
    model_modules = set()
    writes = set(WRITE_OPERATIONS)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and ".models" in node.module:
                models.update(item.asname or item.name for item in node.names)
            if node.module and node.module.startswith("app.domains"):
                model_modules.update(
                    item.asname or item.name
                    for item in node.names
                    if item.name == "models"
                )
            if node.module and node.module.startswith("sqlalchemy"):
                writes.update(
                    item.asname or item.name
                    for item in node.names
                    if item.name in WRITE_OPERATIONS
                )
        if isinstance(node, ast.Import):
            model_modules.update(
                item.asname or item.name
                for item in node.names
                if ".models" in item.name
            )
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Attribute) and function.attr == "execute":
                for argument in node.args:
                    for value in ast.walk(argument):
                        if (
                            isinstance(value, ast.Constant)
                            and isinstance(value.value, str)
                            and re.match(
                                r"\s*(UPDATE|INSERT|DELETE|REPLACE|ALTER|CREATE|DROP|TRUNCATE)\b",
                                value.value,
                                re.IGNORECASE,
                            )
                        ):
                            violations.append(f"line {node.lineno}: raw SQL mutation")
            if isinstance(function, ast.Name) and function.id in (models | writes):
                violations.append(f"line {node.lineno}: {function.id}")
            elif isinstance(function, ast.Attribute) and (
                function.attr in WRITE_OPERATIONS
                or ast.unparse(function.value) in model_modules
            ):
                violations.append(f"line {node.lineno}: {ast.unparse(function)}")
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Attribute) for target in targets):
                violations.append(f"line {node.lineno}: attribute mutation")
    return violations


@pytest.mark.parametrize("domain", ["rankings", "reports", "profile"])
def test_read_model_repositories_are_readonly(domain):
    root = ROOT / "src/app/domains" / domain
    files = list(root.glob("repository.py")) + list((root / "repository").rglob("*.py"))
    assert files, f"{domain} must have a repository"
    for path in files:
        assert not write_violations(path.read_text()), str(path)


@pytest.mark.parametrize(
    "source",
    [
        "session.execute(update(Table).values(amount=2))",
        "from sqlalchemy import update as change\nchange(Table)",
        "from app.domains.identity.models import Statistics as Row\nRow(tg_id=1)",
        "from app.domains.identity import models as identity\nidentity.Statistics(tg_id=1)",
        'session.execute(text("UPDATE statistics SET credits=0"))',
        "session.add(row)",
        "row.credits += 1",
    ],
)
def test_detector_rejects_writes(source):
    assert write_violations(source)


def test_detector_accepts_aggregations():
    assert not write_violations(
        "from app.domains.identity.models import Statistics\n"
        "result = session.execute(select(Statistics.tg_id, func.sum(Statistics.credits))).all()"
    )
