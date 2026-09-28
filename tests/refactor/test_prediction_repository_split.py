"""The prediction repository split must match its reviewed sub-topic plan.

``scripts/refactor/verify.py`` matches moved members anywhere in a repository
package, so it cannot tell which sub-topic module an individual member landed
in. This test pins that layout to ``scripts/refactor/split_plans.toml`` and to
the ``planned_target`` values registered in ``scripts/refactor/mapping.toml``.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]
PLAN_NAME = "prediction_repository"
MAPPING = ROOT / "scripts/refactor/mapping.toml"


def _plan() -> dict:
    with (ROOT / "scripts/refactor/split_plans.toml").open("rb") as stream:
        return tomllib.load(stream)[PLAN_NAME]


def _directory(plan: dict) -> Path:
    return ROOT / "src" / Path(*plan["package"].split("."))


def _members() -> dict[str, str]:
    """Member name -> module stem, for every class of the split package."""
    found: dict[str, str] = {}
    for path in sorted(_directory(_plan()).glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found[member.name] = path.stem
                elif isinstance(member, ast.AnnAssign) and isinstance(
                    member.target, ast.Name
                ):
                    found[member.target.id] = path.stem
                elif isinstance(member, ast.Assign):
                    for target in member.targets:
                        if isinstance(target, ast.Name):
                            found[target.id] = path.stem
    return found


def test_declared_mixins_match_the_package_classes() -> None:
    plan = _plan()
    with MAPPING.open("rb") as stream:
        declared = tomllib.load(stream)["repository_mixins"][plan["package"]]
    assert declared == [plan["facade"], *plan["mixins"].values()]


def test_planned_members_live_in_their_reviewed_module() -> None:
    plan = _plan()
    members = _members()
    expected = {
        symbol: "__init__" if target == "facade" else target
        for symbol, target in plan["targets"].items()
    }
    misplaced = {
        symbol: (members.get(symbol), target)
        for symbol, target in expected.items()
        if members.get(symbol) != target
    }
    assert misplaced == {}
    assert len(expected) == 17


def test_registered_planned_targets_agree_with_the_plan() -> None:
    plan = _plan()
    package = plan["package"]
    with MAPPING.open("rb") as stream:
        items = tomllib.load(stream)["items"]
    registered = {
        str(entry["id"]).rsplit(".", 1)[-1]: entry["planned_target"]
        for entry in items
        if str(entry.get("planned_target", "")).startswith(package)
    }
    assert len(registered) == 17
    for symbol, target in registered.items():
        expected = (
            package
            if plan["targets"][symbol] == "facade"
            else f"{package}.{plan['targets'][symbol]}"
        )
        assert target == expected, symbol


def test_facade_composes_the_mixins_in_plan_order() -> None:
    plan = _plan()
    tree = ast.parse((_directory(plan) / "__init__.py").read_text(encoding="utf-8"))
    facade = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == plan["facade"]
    )
    bases = [base.id for base in facade.bases if isinstance(base, ast.Name)]
    assert bases == list(plan["mixins"].values())


def test_module_level_wrapper_stays_in_the_package_api() -> None:
    """`count_bets_tx` 从 part_1 搬进 analytics，公开导入路径不变。"""
    plan = _plan()
    analytics = ast.parse(
        (_directory(plan) / "analytics.py").read_text(encoding="utf-8")
    )
    defined = {
        node.name
        for node in analytics.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "count_bets_tx" in defined

    init_tree = ast.parse(
        (_directory(plan) / "__init__.py").read_text(encoding="utf-8")
    )
    reexported = [
        alias.asname
        for node in init_tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "analytics"
        for alias in node.names
    ]
    assert "count_bets_tx" in reexported


def test_no_numbered_modules_remain() -> None:
    numbered = [
        path.name
        for path in _directory(_plan()).glob("part_*.py")
        if path.stem.split("_")[-1].isdigit()
    ]
    assert numbered == []
