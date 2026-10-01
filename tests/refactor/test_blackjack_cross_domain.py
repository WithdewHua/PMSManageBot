from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
DOMAINS = ROOT / "src/app/domains"
ALLOWED_BLACKJACK_TARGETS = {
    "app.domains.blackjack.service",
    "app.domains.blackjack.config",
    "app.domains.blackjack.repository",
}

#: 跨域调用只走 service，或有明确所有权的 `*_tx`（design D2）。
SERVICE_BOUNDARY_CALLERS = {
    "src/app/domains/badge_awards/service.py": "blackjack_service",
    "src/app/domains/rankings/service.py": "blackjack_service",
}
REPOSITORY_TX_CALLERS = {
    "src/app/domains/gift_pack/repository/conditions.py": (
        "blackjack_repository",
        {"cash_hand_metrics_tx", "count_tournament_entries_tx"},
    ),
    "src/app/domains/gift_pack/repository/rewards.py": (
        "blackjack_repository",
        {"credit_tournament_wallet_tx"},
    ),
}


def _domain_python_files() -> list[Path]:
    return [
        path
        for path in sorted(DOMAINS.rglob("*.py"))
        if "/blackjack/" not in f"/{path.relative_to(ROOT).as_posix()}/"
    ]


def _blackjack_imports(relative: str) -> list[ast.ImportFrom]:
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    return [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "app.domains.blackjack"
    ]


def test_cross_domain_callers_use_blackjack_service_boundaries() -> None:
    for relative, binding in SERVICE_BOUNDARY_CALLERS.items():
        imports = _blackjack_imports(relative)
        assert any(
            alias.asname == binding or alias.name == "service"
            for node in imports
            for alias in node.names
        ), relative


def test_blackjack_tx_callers_only_use_registered_helpers() -> None:
    """走 repository 的跨域调用方只能调用登记的 `*_tx`（design D2）。"""
    for relative, (binding, allowed) in REPOSITORY_TX_CALLERS.items():
        imports = _blackjack_imports(relative)
        assert any(
            alias.asname == binding or alias.name == "repository"
            for node in imports
            for alias in node.names
        ), relative
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == binding
        }
        assert called, relative
        assert called <= allowed, (relative, called - allowed)


def test_external_domains_do_not_import_blackjack_models_or_repository_parts() -> None:
    violations: list[tuple[str, int, str]] = []
    for path in _domain_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.module in {
                "app.domains.blackjack.models",
                "app.domains.blackjack.repository",
            } or node.module.startswith("app.domains.blackjack.repository."):
                violations.append(
                    (path.relative_to(ROOT).as_posix(), node.lineno, node.module)
                )
    assert violations == []


def test_external_domains_do_not_call_blackjack_facade_methods() -> None:
    violations: list[tuple[str, int, str]] = []
    for path in _domain_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != "db":
                continue
            if node.func.attr.startswith(("get_blackjack", "get_user_blackjack")):
                violations.append(
                    (path.relative_to(ROOT).as_posix(), node.lineno, node.func.attr)
                )
    assert violations == []


def test_blackjack_analytics_exports_use_explicit_repository_apis() -> None:
    path = ROOT / "src/app/domains/blackjack/repository/analytics.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "app.domains.blackjack.models" in imported_modules
    assert "app.domains.blackjack.config" in imported_modules
    assert "app.domains.blackjack.repository" in imported_modules


def test_database_facade_has_no_blackjack_operations() -> None:
    with pytest.raises(ModuleNotFoundError):
        import app.databases.db  # noqa: F401
