"""Mechanically split the gift pack repository package into sub-topic mixins.

design D1: move only, never change behaviour. Every class member listed in
``scripts/refactor/mapping.toml`` (``planned_target``) lands, verbatim, in the
mixin module named there; ``repository/__init__.py`` keeps composing them, so
callers see the same ``GiftPackRepository`` facade.

Run without ``--write`` to print the plan. The move is verified afterwards by
``scripts/refactor/verify.py`` (per-unit AST comparison) and
``scripts/refactor/rewrite_baseline_keys.py`` (baseline keys).
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

PACKAGE = "app.domains.gift_pack.repository"
PACKAGE_DIR = PROJECT_ROOT / "src/app/domains/gift_pack/repository"
FACADE = "GiftPackRepository"
SOURCE_FILES = ("part_1.py", "part_2.py", "part_3.py", "__init__.py")

MIXINS: dict[str, str] = {
    "conditions": "_GiftPackRepositoryConditions",
    "rewards": "_GiftPackRepositoryRewards",
    "packs": "_GiftPackRepositoryPacks",
    "claims": "_GiftPackRepositoryClaims",
    "notices": "_GiftPackRepositoryNotices",
}
TOPICS: dict[str, str] = {
    "conditions": "用户上下文、条件与受众的取数和求值",
    "rewards": "奖励发放",
    "packs": "定义的增删改、引用校验、管理端列表、统计与领取记录",
    "claims": "用户列表、开屏提醒与领取",
    "notices": "开始私信的认领、过期扫描与标记",
}
# 门面类自身的三个类限定自引用：搬移后按既有的 self 引用归一化规则改写。
CLASS_REFERENCE_REWRITES: dict[str, dict[str, str]] = {
    "_gift_pack_condition_summary": {
        "GiftPackRepository._gift_pack_condition_label": (
            f"{MIXINS['conditions']}._gift_pack_condition_label"
        )
    },
    "_validate_post_start_edit": {
        "GiftPackRepository._GIFT_PACK_COUNT_METHODS": (
            f"{MIXINS['conditions']}._GIFT_PACK_COUNT_METHODS"
        )
    },
    "_gift_pack_referencing_packs": {
        "GiftPackRepository._resolve_gift_pack_conditions": (
            f"{MIXINS['conditions']}._resolve_gift_pack_conditions"
        )
    },
}
# 跨 mixin 的类引用需要在目标模块里显式导入。
EXTRA_IMPORTS: dict[str, tuple[str, ...]] = {
    "packs": (f"from .conditions import {MIXINS['conditions']}",),
}


class SplitError(RuntimeError):
    """The reviewed plan and the sources disagree."""


@dataclass(frozen=True)
class Member:
    symbol: str
    target: str
    source: str
    start_line: int
    end_line: int
    kind: str


def load_plan(mapping_path: Path) -> dict[str, str]:
    """Read the reviewed symbol to sub-topic destination map."""
    plan: dict[str, str] = {}
    for entry in tomllib.loads(mapping_path.read_text(encoding="utf-8")).get(
        "items", []
    ):
        target = entry.get("planned_target")
        if not isinstance(target, str) or not target.startswith(f"{PACKAGE}."):
            continue
        stem = target[len(PACKAGE) + 1 :]
        if stem not in MIXINS:
            raise SplitError(f"未知的子主题目标: {target}")
        symbol = str(entry["id"]).rsplit(".", 1)[-1]
        if symbol in plan and plan[symbol] != stem:
            raise SplitError(f"符号被登记到多个子主题: {symbol}")
        plan[symbol] = stem
    if not plan:
        raise SplitError("mapping.toml 里没有礼包 repository 的 planned_target")
    return plan


def collect_members(plan: dict[str, str]) -> list[Member]:
    """Collect every class member of the sources with its reviewed destination."""
    members: list[Member] = []
    seen: set[str] = set()
    for name in SOURCE_FILES:
        path = PACKAGE_DIR / name
        if not path.is_file():
            raise SplitError(f"缺少源文件: {path}")
        for item in inventory([path], root=PROJECT_ROOT):
            if not item.parent_id or item.kind not in {"method", "attribute"}:
                continue
            symbol = item.name.rsplit(".", 1)[-1]
            if symbol in seen:
                raise SplitError(f"重复的成员: {symbol}")
            target = plan.get(symbol)
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
                    kind=item.kind,
                )
            )
    missing = sorted(set(plan) - seen)
    if missing:
        raise SplitError(f"登记的成员在源码里找不到: {missing}")
    return members


def _source_lines(name: str) -> list[str]:
    return (PACKAGE_DIR / name).read_text(encoding="utf-8").splitlines()


def _member_text(member: Member) -> list[str]:
    """Copy a class member verbatim (its span already includes indentation)."""
    lines = _source_lines(member.source)
    return lines[member.start_line - 1 : member.end_line]


def _imports_for(sources: set[str]) -> list[str]:
    """Union of the top-level import statements of the contributing sources."""
    imports: list[str] = []
    seen: set[str] = set()
    for name in SOURCE_FILES:
        if name not in sources:
            continue
        tree = ast.parse("\n".join(_source_lines(name)))
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
    return imports


def _package_bindings() -> set[str]:
    """Module-level names defined by the facade package itself."""
    tree = ast.parse("\n".join(_source_lines("__init__.py")))
    bindings: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bindings.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bindings.add(node.target.id)
    bindings.discard(FACADE)
    return bindings


def _package_imports(members: list[Member]) -> list[str]:
    """Import the facade-level helpers the moved members still call by name."""
    used: set[str] = set()
    for member in members:
        text = "\n".join(_apply_rewrites(member, _member_text(member)))
        tree = ast.parse(textwrap.dedent("\n".join(text.splitlines())))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used.add(node.id)
            elif (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and isinstance(node.value.ctx, ast.Load)
            ):
                used.add(node.value.id)
    needed = sorted(used & _package_bindings())
    return [f"from . import {', '.join(needed)}"] if needed else []


def _apply_rewrites(member: Member, text: list[str]) -> list[str]:
    rewrites = CLASS_REFERENCE_REWRITES.get(member.symbol, {})
    for old, new in rewrites.items():
        text = [line.replace(old, new) for line in text]
    return text


def render_mixin(stem: str, members: list[Member]) -> str:
    """Render one mixin module with its class members copied verbatim."""
    sources = {member.source for member in members}
    imports = [
        *_imports_for(sources),
        *_package_imports(members),
        *EXTRA_IMPORTS.get(stem, ()),
    ]
    body: list[str] = []
    for index, member in enumerate(members):
        if index:
            body.append("")
        body.extend(_apply_rewrites(member, _member_text(member)))
    lines = [
        f'"""礼包 repository：{TOPICS[stem]}（由 part_1–part_3 与门面机械拆分）。"""',
        "",
        *sorted(
            set(imports),
            key=lambda statement: (statement.startswith("from ."), statement),
        ),
        "",
        "",
        f"class {MIXINS[stem]}:",
        *body,
        "",
    ]
    return "\n".join(lines)


def render_package(members: list[Member]) -> str:
    """Render the facade package: module helpers plus the composed class."""
    original = _source_lines("__init__.py")
    tree = ast.parse("\n".join(original))
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == FACADE
    )
    # 门面方法搬走后，只剩模块级 helper 还在用这些导入；不用的删掉，
    # 继续用的原样保留（ruff 不会在 __init__.py 里自动删导入）。
    used: set[str] = set()
    for node in tree.body:
        if node is class_node:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                used.add(child.id)
            elif (
                isinstance(child, ast.Attribute)
                and isinstance(child.value, ast.Name)
                and isinstance(child.value.ctx, ast.Load)
            ):
                used.add(child.value.id)
    dropped: set[int] = set()
    for node in tree.body:
        if node is class_node or not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        bindings = {alias.asname or alias.name.split(".")[0] for alias in node.names}
        if not isinstance(node, ast.ImportFrom):
            bindings = {alias.asname or alias.name for alias in node.names}
        if (
            isinstance(node, ast.ImportFrom)
            and (node.module or "").startswith("part_")
            or not (bindings & used)
        ):
            dropped.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    kept = [
        line
        for index, line in enumerate(original, start=1)
        if index < class_node.lineno and index not in dropped
    ]
    header = "\n".join(kept).rstrip("\n")
    docstring = ""
    if (
        class_node.body
        and isinstance(class_node.body[0], ast.Expr)
        and isinstance(class_node.body[0].value, ast.Constant)
        and isinstance(class_node.body[0].value.value, str)
    ):
        docstring = f'    """{class_node.body[0].value.value}"""'
    imports = [
        f"from .{stem} import {class_name}" for stem, class_name in MIXINS.items()
    ]
    bases = ",\n".join(f"    {class_name}" for class_name in MIXINS.values())
    body = docstring or '    """礼包数据访问门面，按子主题组合五个 mixin。"""'
    return (
        f"{header}\n\n\n"
        + "\n".join(imports)
        + f"\n\n\nclass {FACADE}(\n{bases},\n):\n{body}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mapping", type=Path, default=PROJECT_ROOT / "scripts/refactor/mapping.toml"
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    plan = load_plan(args.mapping)
    members = collect_members(plan)
    for stem in MIXINS:
        if (PACKAGE_DIR / f"{stem}.py").exists():
            raise SplitError(f"目标文件已存在: {stem}.py")

    grouped: dict[str, list[Member]] = {stem: [] for stem in MIXINS}
    for member in members:
        grouped[member.target].append(member)
    for stem, items in grouped.items():
        items.sort(key=lambda item: (SOURCE_FILES.index(item.source), item.start_line))

    staged = {
        PACKAGE_DIR / f"{stem}.py": render_mixin(stem, items)
        for stem, items in grouped.items()
    }
    staged[PACKAGE_DIR / "__init__.py"] = render_package(members)

    summary = {
        "members": {
            stem: [item.symbol for item in items] for stem, items in grouped.items()
        },
        "writes": sorted(str(path.relative_to(PROJECT_ROOT)) for path in staged),
        "deletes": [f"{PACKAGE_DIR.name}/part_{index}.py" for index in (1, 2, 3)],
        "written": bool(args.write),
    }
    print(json.dumps(summary, ensure_ascii=False))
    if not args.write:
        return 0

    for path, text in staged.items():
        path.write_text(text, encoding="utf-8")
    for index in (1, 2, 3):
        (PACKAGE_DIR / f"part_{index}.py").unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
