"""Database-backed catalog and invitation settings must not regain .env writers."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_legacy_business_env_writer_is_removed() -> None:
    violations = []
    for path in (ROOT / "src/app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
            elif isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.Name):
                name = node.id
            else:
                continue
            if name == "save_config_to_env_file":
                violations.append((str(path.relative_to(ROOT)), node.lineno))
    assert violations == []


def test_mutable_catalog_and_code_fields_are_not_deployment_settings() -> None:
    from app.core.config import Settings

    assert {"PRIVILEGED_CODES", "STREAM_BACKEND", "PREMIUM_STREAM_BACKEND"}.isdisjoint(
        Settings.model_fields
    )
