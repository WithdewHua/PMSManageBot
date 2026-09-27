"""Move gift-pack pure computations from the repository mixins into ``rules.py``.

design D4: reward registry/labels/summaries, condition parsing, lifecycle and
``phase_ref``, remaining count, audience size, the implicit binding requirement
and the post-start edit validation are pure — they take plain dicts and model
snapshots and return plain values.  They move verbatim: the script copies the
exact source AST, drops ``@staticmethod``/``self``, and refuses to continue when
a moved body still refers to a helper that stayed behind.

Run without ``--write`` to print the plan and the reference report.
"""

from __future__ import annotations

import argparse
import ast
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PACKAGE_DIR = PROJECT_ROOT / "src/app/domains/gift_pack"
REPOSITORY_DIR = PACKAGE_DIR / "repository"
RULES = PACKAGE_DIR / "rules.py"

#: 顺序即 rules.py 中的定义顺序（常量在前，函数随后）。
MOVES: dict[str, tuple[str, ...]] = {
    "repository/__init__.py": (
        "_format_gift_pack_number",
        "GIFT_PACK_REWARD_TYPES",
        "gift_pack_rewards_require_binding",
    ),
    "repository/conditions.py": (
        "_gift_pack_local_date",
        "_is_premium_active",
        "_legacy_gift_pack_requirements",
        "_gift_pack_conditions_with_binding",
        "_resolve_gift_pack_conditions",
        "_gift_pack_condition_label",
        "_gift_pack_condition_summary",
        "_gift_pack_audience_size",
        "_evaluate_gift_pack_audience",
        "_evaluate_conditions",
        "_evaluate_gift_pack_condition",
    ),
    "repository/packs.py": (
        "_gift_pack_reward_label",
        "_gift_pack_phase_ref",
        "_gift_pack_lifecycle",
        "_gift_pack_remaining",
        "_validate_post_start_edit",
    ),
}

#: 搬移时按需改写的引用（rules 自带一份指标名单，不再依赖 repository 的 ClassVar）。
SUBSTITUTIONS: dict[str, str] = {
    "_GiftPackRepositoryConditions._GIFT_PACK_COUNT_METHODS": "_GIFT_PACK_METRICS",
    "_GIFT_PACK_COUNT_METHODS": "_GIFT_PACK_METRICS",
}

#: 需要人工改写的调用（取数改为由 repository 预取后传入 metrics）。
ALLOWED_REWRITES = {"_gift_pack_metric_value"}

#: 搬移后仍然引用这些“留在 repository”的名字时报告（需要人工改写或一并搬移）。
STAYS_BEHIND = {
    "_GiftPackRepositoryConditions._GIFT_PACK_COUNT_METHODS",
    "_GiftPackRepositoryConditions._gift_pack_metric_value",
    "_gift_pack_metric_value",
    "_evaluate_conditions",
    "_evaluate_gift_pack_condition",
}

HEADER = '''"""礼包领域的纯计算：奖励登记表与文案、条件解析、生命周期与余量、字段校验。

这里不读数据库、不开 session、不发通知、不导入其他领域：输入是普通 dict 和模型
快照，输出是普通值（design D4）。需要取数的部分由 repository 依据
``required_metrics`` 决定取哪些指标，再把结果交给 ``evaluate``。
"""

#: 需要向各领域计数器取数的条件类型（次数的具体查询由 repository 负责）。
_GIFT_PACK_METRICS = (
    "wheel_spins",
    "blackjack_hands",
    "treasure_issues",
    "prediction_bets",
    "auction_participations",
    "tournament_entries",
    "invitees",
    "watched_hours",
)
'''


class RulesExtractionError(RuntimeError):
    """The declared move and the sources disagree."""


@dataclass(frozen=True)
class Extracted:
    name: str
    source: Path
    node: ast.stmt
    body: str


def _moved_names() -> set[str]:
    return {name for names in MOVES.values() for name in names}


def _find_member(tree: ast.Module, name: str) -> ast.stmt | None:
    def match(node: ast.AST) -> bool:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return node.name == name
        if isinstance(node, ast.Assign):
            return any(
                isinstance(target, ast.Name) and target.id == name
                for target in node.targets
            )
        if isinstance(node, ast.AnnAssign):
            return isinstance(node.target, ast.Name) and node.target.id == name
        return False

    for node in tree.body:
        if match(node):
            return node
        if isinstance(node, ast.ClassDef):
            for member in node.body:
                if match(member):
                    return member
    return None


def _segment(node: ast.stmt, text: str) -> str:
    """取节点的原始源码片段（保留注释与格式），去掉 @staticmethod 与缩进。"""
    segment = ast.get_source_segment(text, node)
    if segment is None:
        raise RulesExtractionError(f"无法取源码片段: {getattr(node, 'name', node)}")
    padded = " " * node.col_offset + segment
    lines = textwrap.dedent(padded).splitlines()
    while lines and lines[0].strip() == "@staticmethod":
        lines.pop(0)
    return "\n".join(lines)


def _drop_self_parameter(node: ast.stmt) -> ast.stmt:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        node.decorator_list = [
            decorator
            for decorator in node.decorator_list
            if not (isinstance(decorator, ast.Name) and decorator.id == "staticmethod")
        ]
        args = node.args
        if args.args and args.args[0].arg == "self":
            args.args = args.args[1:]
            if (
                not args.args
                and not args.posonlyargs
                and not args.kwonlyargs
                and args.vararg is None
                and args.kwarg is None
                and not args.kw_defaults
            ):
                args.kwonlyargs = []
    return node


def _references(node: ast.stmt) -> set[str]:
    """搬移后需要人工处理的名字/类限定引用。"""
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
            if child.value.id in {
                "self",
                "GiftPackRepository",
            } or child.value.id.startswith("_GiftPackRepository"):
                names.add(child.attr)
            if child.value.id.startswith("_GiftPackRepository"):
                names.add(f"{child.value.id}.{child.attr}")
        if isinstance(child, ast.Name) and child.id in STAYS_BEHIND:
            names.add(child.id)
    return names


def extract() -> list[Extracted]:
    moved = _moved_names()
    extracted: list[Extracted] = []
    problems: list[str] = []
    for relative, names in MOVES.items():
        path = PACKAGE_DIR / relative
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for name in names:
            node = _find_member(tree, name)
            if node is None:
                problems.append(f"{relative}: 找不到 {name}")
                continue
            node = _drop_self_parameter(node)
            for reference in sorted(_references(node)):
                bare = reference.rsplit(".", 1)[-1]
                if bare in moved or bare in SUBSTITUTIONS or bare in ALLOWED_REWRITES:
                    continue
                problems.append(f"{relative}:{name} 仍引用未搬移的 {reference}")
            extracted.append(
                Extracted(name=name, source=path, node=node, body=_segment(node, text))
            )
    if problems:
        raise RulesExtractionError("\n".join(problems))
    return extracted


def rewrite(extracted: list[Extracted]) -> None:
    body = HEADER + "\n\n" + "\n\n\n".join(item.body for item in extracted) + "\n"
    for source, replacement in SUBSTITUTIONS.items():
        body = body.replace(source, replacement)
    for item in extracted:
        for moved in _moved_names():
            body = body.replace(f"self.{moved}(", f"{moved}(")
            body = body.replace(f"GiftPackRepository.{moved}(", f"{moved}(")
            body = body.replace(f"_GiftPackRepositoryConditions.{moved}(", f"{moved}(")
    RULES.write_text(body, encoding="utf-8")

    for relative, names in MOVES.items():
        path = PACKAGE_DIR / relative
        tree = ast.parse(path.read_text(encoding="utf-8"))
        removed = False
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                keep = [
                    member
                    for member in node.body
                    if getattr(member, "name", None) not in names
                ]
                if len(keep) != len(node.body):
                    removed = True
                    node.body = keep
                    if not keep:
                        node.body = [ast.Pass()]
            elif getattr(node, "name", None) in names:
                removed = True
                tree.body.remove(node)
                node = None  # type: ignore[assignment]
            elif (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id in names
                    for target in node.targets
                )
            ) or (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id in names
            ):
                removed = True
                tree.body.remove(node)
        if removed:
            ast.fix_missing_locations(tree)
            source = ast.unparse(tree)
            path.write_text(source + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    extracted = extract()
    print(f"计划搬移 {len(extracted)} 个纯计算：")
    for item in extracted:
        print(f"  {item.source.name} -> rules.py: {item.name}")
    if args.write:
        rewrite(extracted)
        print(f"已写入 {RULES.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
