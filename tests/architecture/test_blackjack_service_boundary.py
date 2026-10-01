"""Interface modules must reach blackjack workflows through `blackjack.service`.

Blackjack's cash/tournament interfaces call `app.domains.blackjack.service`; the
service delegates calculations to `blackjack.rules` and writes to
`app.domains.blackjack.repository`. Interface modules therefore must not import
repository implementation parts, the legacy facade, raw SQLAlchemy, or another
domain's internal modules (jobs / models / repository).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
assert (ROOT / "src/app").is_dir()
BLACKJACK = ROOT / "src/app/domains/blackjack"
assert BLACKJACK.is_dir()

INTERFACE_MODULES = (
    "router/cash.py",
    "router/tournament.py",
    "router/tournament_admin.py",
    "router/__init__.py",
    "jobs/cash.py",
    "jobs/tournament.py",
    "notifications/cash.py",
    "notifications/tournament.py",
    "__init__.py",
)

# 接口层不得触碰的数据层与基础设施：仓储实现、门面、core.db、原始 SQLAlchemy
FORBIDDEN_PREFIXES = (
    "app.domains.blackjack.repository",
    "app.databases",
    "app.core.db",
    "sqlalchemy",
)

# 唯一保留的跨领域内部导入：游戏王勋章检查由 badge_awards 拥有，
# 该领域尚未提供 service，暂按既有基线登记债务（责任变更：promote-reward-domains）。
ITEMIZED_FOREIGN_INTERNAL_IMPORTS = {
    ("app.domains.badge_awards.jobs", "check_and_award_game_king_badge"),
}

# 允许的跨领域导入面：目标领域的 service 或纯类型模块
ALLOWED_FOREIGN_MODULE_PREFIXES = ("app.domains.credits.types",)


def _is_service_import(module: str, name: str) -> bool:
    """`from app.domains.x import service` 与 `from app.domains.x.service import y` 都算面。"""

    return module.endswith(".service") or (
        name == "service"
        and module.startswith("app.domains.")
        and module.count(".") == 2
    )


CASH_WORKFLOWS = (
    "create_blackjack_hand",
    "blackjack_hit",
    "blackjack_stand",
    "blackjack_double",
    "blackjack_surrender",
)


def _imports(path: Path) -> list[tuple[str, str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                found.append((node.module, alias.name, node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, "", node.lineno))
    return found


@pytest.mark.parametrize("relative", INTERFACE_MODULES)
def test_interface_modules_do_not_import_data_layer(relative: str) -> None:
    path = BLACKJACK / relative
    offending = [
        (module, line)
        for module, _, line in _imports(path)
        if module.startswith(FORBIDDEN_PREFIXES)
    ]
    assert offending == [], f"{relative} imports the data layer: {offending}"

    source = path.read_text(encoding="utf-8")
    assert "_repository" not in source, relative
    assert "get_session" not in source, relative


@pytest.mark.parametrize("relative", INTERFACE_MODULES)
def test_interface_modules_only_reach_foreign_domains_through_services(
    relative: str,
) -> None:
    path = BLACKJACK / relative
    violations = []
    for module, name, line in _imports(path):
        if not module.startswith("app.domains.") or module.startswith(
            "app.domains.blackjack"
        ):
            continue
        if module.startswith(ALLOWED_FOREIGN_MODULE_PREFIXES):
            continue
        if _is_service_import(module, name):
            continue
        if (module, name) in ITEMIZED_FOREIGN_INTERNAL_IMPORTS:
            continue
        violations.append((module, name, line))
    assert violations == [], (
        f"{relative} imports foreign domain internals: {violations}; "
        "route the call through the target domain's service instead"
    )


def test_service_exposes_the_cash_workflows_routers_call() -> None:
    from app.domains.blackjack import service as blackjack_service

    for name in CASH_WORKFLOWS:
        assert callable(getattr(blackjack_service, name)), name

    router_source = (BLACKJACK / "router/cash.py").read_text(encoding="utf-8")
    for name in CASH_WORKFLOWS:
        assert f"blackjack_service.{name}(" in router_source, name


def test_service_module_keeps_writes_behind_the_repository() -> None:
    imports = _imports(BLACKJACK / "service.py")
    offending = [
        (module, line)
        for module, _, line in imports
        if module.startswith(("app.databases", "sqlalchemy"))
    ]
    assert offending == []
    assert all(
        not module.startswith("app.domains.blackjack.models")
        for module, _, _ in imports
    )


def test_routers_delegate_calculations_to_rules() -> None:
    """牌局计算来自 rules，而非 router 内联的判定。"""

    for relative in ("router/cash.py", "router/tournament.py"):
        source = (BLACKJACK / relative).read_text(encoding="utf-8")
        assert "blackjack.rules" in source or "rules." in source, relative
