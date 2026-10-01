"""Negative tests and architecture boundaries for domain configuration access (Rules #239, #240)."""

from __future__ import annotations

import ast
from pathlib import Path

from tests.architecture.checks import scan_config_access

ROOT = Path(__file__).resolve().parents[2]
assert (ROOT / "src/app").is_dir()


def _imports(tree: ast.AST) -> set[str]:
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            for alias in node.names:
                imported.add(f"{node.module}.{alias.name}")
    return imported


def test_domain_rules_modules_do_not_import_config_or_domain_config() -> None:
    """Domain rules must receive configuration via arguments, never importing config (Rule #239)."""
    violations: list[tuple[str, str]] = []
    for path in sorted((ROOT / "src/app/domains").rglob("rules.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for mod in _imports(tree):
            if (
                mod.startswith("app.core.domain_config")
                or (mod.startswith("app.domains.") and mod.endswith(".config"))
                or "DomainConfig" in mod
            ):
                violations.append((path.relative_to(ROOT).as_posix(), mod))
    assert violations == [], (
        f"Rules modules must not import domain configs: {violations}"
    )


def test_integration_modules_do_not_import_domain_config() -> None:
    """Integrations must receive configuration via arguments, never importing domain config (Rule #239)."""
    violations: list[tuple[str, str]] = []
    for path in sorted((ROOT / "src/app/integrations").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for mod in _imports(tree):
            if mod.startswith("app.core.domain_config") or "DomainConfig" in mod:
                violations.append((path.relative_to(ROOT).as_posix(), mod))
    assert violations == [], f"Integrations must not import DomainConfig: {violations}"


def test_scanner_flags_rules_accessing_domain_config(tmp_path: Path) -> None:
    """scan_config_access must reject a rules module reading domain config."""
    app_dir = tmp_path / "src/app"
    rules_dir = app_dir / "domains/sample"
    rules_dir.mkdir(parents=True)
    (rules_dir / "rules.py").write_text(
        "from app.domains.sample import config\n\ndef compute():\n    return config.get().value\n",
        encoding="utf-8",
    )
    violations = scan_config_access(tmp_path)
    assert any(
        v["source_domain"] == "sample"
        and v["source_role"] == "rules"
        and v["operation"] == "get"
        for v in violations
    )


def test_scanner_flags_integrations_accessing_domain_config(tmp_path: Path) -> None:
    """scan_config_access must reject an integrations module reading domain config."""
    app_dir = tmp_path / "src/app"
    integrations_dir = app_dir / "integrations"
    integrations_dir.mkdir(parents=True)
    (integrations_dir / "external_api.py").write_text(
        "from app.domains.sample import config\n\ndef fetch():\n    return config.get().api_url\n",
        encoding="utf-8",
    )
    violations = scan_config_access(tmp_path)
    assert any(
        v["source_role"] == "integrations"
        and v["target_domain"] == "sample"
        and v["operation"] == "get"
        for v in violations
    )


def test_scanner_flags_cross_domain_config_writes(tmp_path: Path) -> None:
    """scan_config_access must reject a foreign domain writing configuration."""
    app_dir = tmp_path / "src/app"
    foreign_dir = app_dir / "domains/foreign"
    foreign_dir.mkdir(parents=True)
    (foreign_dir / "service.py").write_text(
        "from app.domains.target import config\n\ndef mutate():\n    config.update({'foo': 1})\n",
        encoding="utf-8",
    )
    violations = scan_config_access(tmp_path)
    assert any(
        v["source_domain"] == "foreign"
        and v["target_domain"] == "target"
        and v["operation"] == "update"
        for v in violations
    )
