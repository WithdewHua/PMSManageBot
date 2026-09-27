"""Split repository ``part_<n>`` modules into reviewed sub-topic mixins.

The plan (``scripts/refactor/split_plans.toml``) names the sources, the mixin
modules, their topics and the destination of every member; members already
registered in ``mapping.toml`` must agree with their ``planned_target``.

Move only: member text is copied verbatim, the facade keeps composing the
mixins, and ``__init__.py`` keeps every module-level wrapper. Verify with
``scripts/refactor/verify.py`` and rewrite the baseline keys with
``scripts/refactor/rewrite_baseline_keys.py``.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import textwrap
import tomllib
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.refactor.inventory import inventory

DEFAULT_PLAN = PROJECT_ROOT / "scripts/refactor/split_plans.toml"
DEFAULT_MAPPING = PROJECT_ROOT / "scripts/refactor/mapping.toml"


class SplitError(RuntimeError):
    """The reviewed plan, the mapping and the sources disagree."""


@dataclass(frozen=True)
class Plan:
    name: str
    package: str
    facade: str
    facade_bases: list[str]
    facade_members: list[str]
    sources: list[str]
    mixins: dict[str, str]
    topics: dict[str, str]
    targets: dict[str, str]
    mapping_targets: dict[str, str]

    @property
    def directory(self) -> Path:
        return PROJECT_ROOT / "src" / Path(*self.package.split("."))


@dataclass(frozen=True)
class Member:
    symbol: str
    target: str
    source: str
    start_line: int
    end_line: int


def load_plan(plan_path: Path, name: str | None, mapping_path: Path) -> Plan:
    data = tomllib.loads(plan_path.read_text(encoding="utf-8"))
    names = [name] if name else [key for key in data if not key.startswith("_")]
    if len(names) != 1:
        raise SplitError(f"请用 --name 指定一个拆分计划，可选：{sorted(data)}")
    section = data[names[0]]
    package = section["package"]
    mapping_targets: dict[str, str] = {}
    with mapping_path.open("rb") as stream:
        mapping = tomllib.load(stream)
    declared = mapping.get("repository_mixins", {}).get(package)
    expected_classes = [section["facade"], *section["mixins"].values()]
    if list(declared or []) != expected_classes:
        raise SplitError(
            f'mapping.toml 的 [repository_mixins]"{package}" 必须是 '
            f"{expected_classes}，实际是 {declared}"
        )
    for entry in mapping.get("items", []):
        planned = entry.get("planned_target")
        if isinstance(planned, str) and planned.startswith(f"{package}."):
            mapping_targets[str(entry["id"]).rsplit(".", 1)[-1]] = planned
    plan = Plan(
        name=names[0],
        package=package,
        facade=section["facade"],
        facade_bases=list(section.get("facade_bases", [])),
        facade_members=list(section.get("facade_members", [])),
        sources=list(section["sources"]),
        mixins=dict(section["mixins"]),
        topics=dict(section["topics"]),
        targets=dict(section["targets"]),
        mapping_targets=mapping_targets,
    )
    for symbol, target in plan.targets.items():
        if target != "facade" and target not in plan.mixins:
            raise SplitError(f"{symbol} 的目标不是 mixin 模块：{target}")
    for symbol, planned in plan.mapping_targets.items():
        expected = plan_target(plan, symbol)
        if expected and planned != expected:
            raise SplitError(
                f"{symbol} 与 planned_target 不一致：{planned} != {expected}"
            )
    return plan


def plan_target(plan: Plan, symbol: str) -> str | None:
    module = plan.targets.get(symbol)
    if module is None:
        return None
    return plan.package if module == "facade" else f"{plan.package}.{module}"


def collect_members(plan: Plan) -> list[Member]:
    members: list[Member] = []
    seen: set[str] = set()
    for name in plan.sources:
        path = plan.directory / name
        if not path.is_file():
            raise SplitError(f"缺少源文件: {path}")
        for item in inventory([path], root=PROJECT_ROOT):
            if not item.parent_id or item.kind not in {"method", "attribute"}:
                continue
            symbol = item.name.rsplit(".", 1)[-1]
            if symbol in seen:
                raise SplitError(f"重复的成员: {symbol}")
            target = plan.targets.get(symbol)
            if target is None:
                raise SplitError(f"{name} 的成员没有登记目标: {symbol}")
            seen.add(symbol)
            members.append(
                Member(
                    symbol=symbol,
                    target=target,
                    source=name,
                    start_line=item.start_line,
                    end_line=item.end_line,
                )
            )
    missing = sorted(set(plan.targets) - seen - set(plan.facade_members))
    if missing:
        raise SplitError(f"登记的成员在源码里找不到: {missing}")
    for symbol in plan.facade_members:
        if symbol not in seen:
            raise SplitError(f"留在门面的成员不存在: {symbol}")
    return members


def _source_lines(plan: Plan, name: str) -> list[str]:
    return (plan.directory / name).read_text(encoding="utf-8").splitlines()


def _member_text(plan: Plan, member: Member) -> list[str]:
    """Copy a class member verbatim (its span already includes indentation)."""
    return _source_lines(plan, member.source)[member.start_line - 1 : member.end_line]


def _imports_used_by(plan: Plan, members: list[Member]) -> list[str]:
    """Imports of the contributing sources that the given members reference."""
    used: set[str] = set()
    for member in members:
        tree = ast.parse(textwrap.dedent("\n".join(_member_text(plan, member))))
        used |= {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
    imports: list[str] = []
    for statement in _imports_for(plan, {member.source for member in members}):
        node = ast.parse(statement).body[0]
        if isinstance(node, ast.Import):
            kept = [alias for alias in node.names if alias.name.split(".")[0] in used]
            if not kept:
                continue
            imports.append(ast.unparse(ast.Import(names=kept)))
        elif isinstance(node, ast.ImportFrom):
            kept = [
                alias for alias in node.names if (alias.asname or alias.name) in used
            ]
            if not kept:
                continue
            imports.append(
                ast.unparse(
                    ast.ImportFrom(module=node.module, names=kept, level=node.level)
                )
            )
    return sorted(set(imports), key=lambda text: (text.startswith("from ."), text))


def _imports_for(plan: Plan, sources: set[str]) -> list[str]:
    """Union of the top-level imports of the contributing sources."""
    imports: list[str] = []
    seen: set[str] = set()
    for name in plan.sources:
        if name not in sources:
            continue
        tree = ast.parse("\n".join(_source_lines(plan, name)))
        for node in tree.body:
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "part_"
            ):
                continue
            statement = ast.unparse(node)
            if statement in seen:
                continue
            seen.add(statement)
            imports.append(statement)
    return sorted(set(imports), key=lambda text: (text.startswith("from ."), text))


def render_mixin(plan: Plan, stem: str, members: list[Member]) -> str:
    body: list[str] = []
    for index, member in enumerate(members):
        if index:
            body.append("")
        body.extend(_member_text(plan, member))
    return "\n".join(
        [
            f'"""21 点 repository：{plan.topics[stem]}（由 part_N 机械拆分）。"""',
            "",
            *_imports_used_by(plan, members),
            "",
            "",
            f"class {plan.mixins[stem]}:",
            *body,
            "",
        ]
    )


def _facade_members_text(plan: Plan, members: list[Member]) -> list[str]:
    text: list[str] = []
    for member in members:
        if not text:
            text.append("")
        text.extend(_member_text(plan, member))
    return text


def render_facade(plan: Plan, members: list[Member]) -> str:
    """Render the package: header, composed class and the wrapper API.

    Only the ``from .part_N import …`` lines and the class definition are
    rebuilt; the module-level wrapper functions keep their text.
    """
    original = _source_lines(plan, "__init__.py")
    tree = ast.parse("\n".join(original))
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == plan.facade
    )
    dropped: set[int] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("part_"):
            dropped.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    before = [
        line
        for index, line in enumerate(original, start=1)
        if index < class_node.lineno and index not in dropped
    ]
    after = list(original[(class_node.end_lineno or class_node.lineno) :])
    while before and not before[-1].strip():
        before.pop()
    while after and not after[0].strip():
        after.pop(0)
    retained = [member for member in members if member.symbol in plan.facade_members]
    header = "\n".join(before)
    for statement in _imports_used_by(plan, retained):
        if statement not in header:
            header += "\n" + statement
    docstring = ""
    if (
        class_node.body
        and isinstance(class_node.body[0], ast.Expr)
        and isinstance(class_node.body[0].value, ast.Constant)
        and isinstance(class_node.body[0].value.value, str)
    ):
        docstring = f'    """{class_node.body[0].value.value}"""'
    imports = [f"from .{stem} import {name}" for stem, name in plan.mixins.items()]
    bases = [*plan.facade_bases, *plan.mixins.values()]
    body = [docstring or '    """Private compatibility implementation."""']
    body.extend(_facade_members_text(plan, retained))
    return (
        f"{header}\n\n\n"
        + "\n".join(imports)
        + f"\n\n\nclass {plan.facade}(\n"
        + "".join(f"    {base},\n" for base in bases)
        + "):\n"
        + "\n".join(body)
        + "\n"
        + "\n".join(after)
        + "\n"
    )


def split(plan: Plan, *, write: bool) -> dict[str, object]:
    members = collect_members(plan)
    for stem in plan.mixins:
        if (plan.directory / f"{stem}.py").exists():
            raise SplitError(f"目标文件已存在: {stem}.py")
    grouped: dict[str, list[Member]] = {stem: [] for stem in plan.mixins}
    for member in members:
        if member.target == "facade":
            continue
        grouped[member.target].append(member)
    for items in grouped.values():
        items.sort(key=lambda item: (plan.sources.index(item.source), item.start_line))

    staged: dict[Path, str] = {
        plan.directory / f"{stem}.py": render_mixin(plan, stem, items)
        for stem, items in grouped.items()
    }
    staged[plan.directory / "__init__.py"] = render_facade(plan, members)
    summary: dict[str, object] = {
        "plan": plan.name,
        "members": {
            stem: [item.symbol for item in items] for stem, items in grouped.items()
        },
        "facade_members": plan.facade_members,
        "writes": sorted(str(path.relative_to(PROJECT_ROOT)) for path in staged),
        "deletes": list(plan.sources),
        "written": write,
    }
    if not write:
        return summary
    for path, text in staged.items():
        path.write_text(text, encoding="utf-8")
    for name in plan.sources:
        (plan.directory / name).unlink()
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--name", default=None)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    plan = load_plan(args.plan, args.name, args.mapping)
    print(json.dumps(split(plan, write=args.write), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
