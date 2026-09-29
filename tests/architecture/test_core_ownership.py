"""Executable ownership and dependency guards for core-boundary migration."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "tests/architecture/core_ownership.toml"
CORE = ROOT / "src/app/core"


def _manifest() -> dict:
    with MANIFEST.open("rb") as stream:
        return tomllib.load(stream)


def _module_name(path: Path) -> str:
    return "app." + ".".join(
        path.relative_to(ROOT / "src/app").with_suffix("").parts
    ).replace(".__init__", "")


def _imports(source: str) -> list[str]:
    tree = ast.parse(source)
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def _validate_module_manifest(modules: set[str], manifest: dict) -> None:
    declared = set(manifest["modules"])
    assert modules == declared, {
        "missing": sorted(modules - declared),
        "stale": sorted(declared - modules),
    }
    for entry in manifest["modules"].values():
        assert entry["decision"]
        assert entry["target"]
        assert isinstance(entry["public_symbols"], list)


def _validate_forbidden_symbols(source: str, forbidden: set[str]) -> set[str]:
    tree = ast.parse(source)
    assigned: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            assigned.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assigned.add(node.name)
    return assigned & forbidden


def test_core_manifest_covers_live_modules_bidirectionally() -> None:
    manifest = _manifest()
    modules = {
        _module_name(path) for path in CORE.glob("*.py") if path.name != "__init__.py"
    }
    _validate_module_manifest(modules, manifest)


def test_manifest_rejects_unregistered_modules_and_symbols() -> None:
    manifest = _manifest()
    with pytest.raises(AssertionError):
        _validate_module_manifest(
            set(manifest["modules"]) | {"app.core.unreviewed"}, manifest
        )
    forbidden = set(manifest["modules"]["app.core.cache"]["forbidden_symbols"])
    assert (
        _validate_forbidden_symbols(
            "from app.core.cache import RedisCache\nfoo_cache = RedisCache()\n",
            forbidden,
        )
        == set()
    )
    assert _validate_forbidden_symbols(
        "from app.core.cache import RedisCache\nuser_credits_cache = RedisCache()\n",
        forbidden,
    ) == {"user_credits_cache"}


def test_core_modules_do_not_import_higher_layers() -> None:
    policy = _manifest()["policy"]
    forbidden = tuple(policy["core_must_not_import_prefixes"])
    violations = []
    for path in sorted(CORE.glob("*.py")):
        for imported in _imports(path.read_text(encoding="utf-8")):
            if imported.startswith(forbidden):
                violations.append((path.relative_to(ROOT).as_posix(), imported))
    assert violations == []


def test_synthetic_transport_and_integration_violations_are_located() -> None:
    policy = _manifest()["policy"]
    transport_bad = _imports("from app.domains.identity import service\n")
    integration_bad = _imports("from app.transport.http import auth\n")
    assert any(
        imported.startswith("app.domains")
        for imported in transport_bad
        if any(
            imported.startswith(prefix)
            for prefix in policy["transport_must_not_import_prefixes"]
        )
    )
    assert any(
        imported.startswith("app.transport")
        for imported in integration_bad
        if any(
            imported.startswith(prefix)
            for prefix in policy["integration_must_not_import_prefixes"]
        )
    )


def test_core_package_does_not_reexport_modules() -> None:
    init = ROOT / "src/app/core/__init__.py"
    tree = ast.parse(init.read_text(encoding="utf-8"))
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in tree.body)
