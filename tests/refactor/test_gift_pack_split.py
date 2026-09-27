"""The gift pack repository split must match its reviewed sub-topic plan.

``scripts/refactor/verify.py`` matches moved members inside a repository package,
so it cannot tell which sub-topic module an individual member landed in. This
test pins that layout to the ``planned_target`` values registered in
``scripts/refactor/mapping.toml``.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]
PACKAGE_DIR = ROOT / "src/app/domains/gift_pack/repository"
RULES_MODULE = ROOT / "src/app/domains/gift_pack/rules.py"
PACKAGE = "app.domains.gift_pack.repository"
FACADE = "GiftPackRepository"
MAPPING = ROOT / "scripts/refactor/mapping.toml"


def _mapping() -> dict:
    with MAPPING.open("rb") as stream:
        return tomllib.load(stream)


def _planned_members() -> dict[str, str]:
    """纯计算成员（4.1 起）落在 rules，其余仍按子主题落在 repository 包。"""
    planned: dict[str, str] = {}
    for entry in _mapping()["items"]:
        target = entry.get("planned_target")
        if not isinstance(target, str):
            continue
        name = re.split(r"[.:]", str(entry["id"]))[-1]
        if target == "app.domains.gift_pack.rules":
            planned[name] = "rules"
        elif target.startswith(f"{PACKAGE}."):
            planned[name] = target.rsplit(".", 1)[-1]
    return planned


def _member_names(node: ast.ClassDef) -> list[str]:
    names: list[str] = []
    for member in node.body:
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(member.name)
        elif isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name):
            names.append(member.target.id)
    return names


def _classes() -> dict[str, tuple[Path, list[str]]]:
    """Mixin class name -> (module path, member names) for the package."""
    found: dict[str, tuple[Path, list[str]]] = {}
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name != FACADE:
                found[node.name] = (path, _member_names(node))
    return found


def test_declared_mixins_match_the_package_classes() -> None:
    declared = set(_mapping()["repository_mixins"][PACKAGE])
    assert declared == set(_classes())


def test_planned_members_live_in_their_reviewed_module() -> None:
    planned = _planned_members()
    # 55 个成员来自 part_1–part_3 与门面的机械拆分：
    # 3.4 把解锁列常量按列归属搬去 lines / media_access（-1）；
    # 4.1 把 18 个纯计算搬去 rules，并新增一条 rules 侧的登记（+19）。
    assert len(planned) == 56
    assert sum(1 for target in planned.values() if target == "rules") == 19
    assert sum(1 for target in planned.values() if target != "rules") == 37
    misplaced: list[str] = []
    for path, members in _classes().values():
        for member in members:
            target = planned.get(member)
            if target is None:
                continue
            if target != path.stem:
                misplaced.append(f"{member}: {path.name} != {target}.py")
    assert misplaced == []
    defined = {member for _, members in _classes().values() for member in members}
    in_package = {name for name, target in planned.items() if target != "rules"}
    assert sorted(in_package - defined) == []


def _rules_members() -> set[str]:
    tree = ast.parse(RULES_MODULE.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Assign):
            names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
    return names


def test_planned_rules_members_live_in_rules_module() -> None:
    """登记到 rules 的纯计算必须真的只出现在 rules 里。"""
    planned = {name for name, target in _planned_members().items() if target == "rules"}
    # _gift_pack_metric_value 被 repository 的 _gift_pack_metrics 取代，不再单独存在
    planned |= {"_evaluate_gift_pack_condition"}
    assert planned
    assert planned - _rules_members() == set()
    assert not planned & {
        name for _, members in _classes().values() for name in members
    }


def test_facade_class_composes_the_mixins_and_keeps_every_member() -> None:
    tree = ast.parse((PACKAGE_DIR / "__init__.py").read_text(encoding="utf-8"))
    facade = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == FACADE
    )
    mixins = [base.id for base in facade.bases if isinstance(base, ast.Name)]
    assert mixins == list(_mapping()["repository_mixins"][PACKAGE])
    exposed = {
        name
        for mixin, (_, members) in _classes().items()
        if mixin in mixins
        for name in members
    }
    assert {
        name for name, target in _planned_members().items() if target != "rules"
    } <= exposed
    assert not [
        path.name for path in PACKAGE_DIR.glob("part_*.py") if path.name[5].isdigit()
    ]
