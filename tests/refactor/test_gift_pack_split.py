"""The gift pack repository split must match its reviewed sub-topic plan.

``scripts/refactor/verify.py`` matches moved members inside a repository package,
so it cannot tell which sub-topic module an individual member landed in. This
test pins that layout to the ``planned_target`` values registered in
``scripts/refactor/mapping.toml``.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]
PACKAGE_DIR = ROOT / "src/app/domains/gift_pack/repository"
PACKAGE = "app.domains.gift_pack.repository"
FACADE = "GiftPackRepository"
MAPPING = ROOT / "scripts/refactor/mapping.toml"


def _mapping() -> dict:
    with MAPPING.open("rb") as stream:
        return tomllib.load(stream)


def _planned_members() -> dict[str, str]:
    planned: dict[str, str] = {}
    for entry in _mapping()["items"]:
        target = entry.get("planned_target")
        if isinstance(target, str) and target.startswith(f"{PACKAGE}."):
            planned[str(entry["id"]).rsplit(".", 1)[-1]] = target.rsplit(".", 1)[-1]
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
    assert len(planned) == 55
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
    assert sorted(set(planned) - defined) == []


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
    assert set(_planned_members()) <= exposed
    assert not [
        path.name for path in PACKAGE_DIR.glob("part_*.py") if path.name[5].isdigit()
    ]
