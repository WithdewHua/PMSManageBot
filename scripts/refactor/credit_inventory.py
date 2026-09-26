"""Inventory all credit balance mutation sites in the live application tree.

This is intentionally a source audit rather than a semantic proof. It records
candidate writes and absolute-value facade calls so each item can be reviewed
before the atomic-credit migration changes it.
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CREDIT_ATTRIBUTES = {"credits", "emby_credits"}
NON_PERSISTED_OUTPUTS = {"user_info"}


@dataclass(frozen=True)
class Mutation:
    path: str
    line: int
    column: int
    kind: str
    target: str
    function: str
    transaction_owner: str
    expression_kind: str
    cache_keys: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "kind": self.kind,
            "target": self.target,
            "function": self.function,
            "transaction_owner": self.transaction_owner,
            "expression_kind": self.expression_kind,
            "cache_keys": list(self.cache_keys),
            "review_status": "pending-migration",
        }


def _attribute_target(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and node.attr in CREDIT_ATTRIBUTES:
        if isinstance(node.value, ast.Name):
            if node.value.id in NON_PERSISTED_OUTPUTS:
                return None
            return f"{node.value.id}.{node.attr}"
        return node.attr
    return None


def _contains_credit_attribute(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Attribute) and child.attr in CREDIT_ATTRIBUTES
        for child in ast.walk(node)
    )


def _expression_kind(value: ast.AST, target: str | None = None) -> str:
    if _contains_credit_attribute(value):
        return "delta-expression"
    if (
        target
        and isinstance(value, ast.Call)
        and getattr(value.func, "id", None) == "round"
        and _contains_credit_attribute(value)
    ):
        return "delta-expression"
    if isinstance(value, ast.BinOp):
        return "computed-absolute"
    return "absolute"


def _function_name(stack: list[str]) -> str:
    return ".".join(stack) if stack else "<module>"


def _transaction_owner(path: Path, stack: list[str]) -> str:
    if "/repository/" in path.as_posix() or path.name == "repository.py":
        return "repository"
    if stack and (stack[-1].endswith("_tx") or stack[-1] == "transfer"):
        return "transaction-candidate"
    return "caller-owned-or-unknown"


def _cache_keys(kind: str, target: str) -> tuple[str, ...]:
    if target.endswith(".emby_credits") or target == "emby_credits":
        return ("emby:<username>",)
    if target.endswith(".credits") and target.split(".", 1)[0] in {
        "stats",
        "winner_stats",
        "new_stat",
    }:
        return ("plex:<username>", "emby:<username>")
    if target == "DatabaseORM.update_user_credits":
        return ("derived-from-account-reference",)
    if kind == "sql-values-write":
        return ("review-required",)
    return ("review-required",)


def collect_inventory(root: Path) -> list[dict[str, Any]]:
    source_root = root / "src" / "app"
    mutations: list[Mutation] = []
    for path in sorted(source_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue

        class Visitor(ast.NodeVisitor):
            def __init__(self, source_path: Path) -> None:
                self.stack: list[str] = []
                self.mutations = mutations
                self.path = source_path

            def _visit_function(
                self, node: ast.FunctionDef | ast.AsyncFunctionDef
            ) -> None:
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self._visit_function(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self._visit_function(node)

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()

            def _record(
                self,
                node: ast.AST,
                kind: str,
                target: str,
                value: ast.AST,
            ) -> None:
                self.mutations.append(
                    Mutation(
                        path=self.path.relative_to(root).as_posix(),
                        line=getattr(node, "lineno", 0),
                        column=getattr(node, "col_offset", 0),
                        kind=kind,
                        target=target,
                        function=_function_name(self.stack),
                        transaction_owner=_transaction_owner(self.path, self.stack),
                        expression_kind=_expression_kind(value, target),
                        cache_keys=_cache_keys(kind, target),
                    )
                )

            def visit_Assign(self, node: ast.Assign) -> None:
                for target_node in node.targets:
                    target = _attribute_target(target_node)
                    if target:
                        self._record(node, "attribute-assignment", target, node.value)
                self.generic_visit(node)

            def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
                target = _attribute_target(node.target)
                if target and node.value:
                    self._record(node, "attribute-assignment", target, node.value)
                self.generic_visit(node)

            def visit_AugAssign(self, node: ast.AugAssign) -> None:
                target = _attribute_target(node.target)
                if target:
                    self._record(
                        node, "attribute-augmented-assignment", target, node.value
                    )
                self.generic_visit(node)

            def visit_Call(self, node: ast.Call) -> None:
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == "update_user_credits":
                        value = (
                            node.keywords[0].value
                            if node.keywords
                            else ast.Constant(value=None)
                        )
                        self._record(
                            node,
                            "absolute-facade-call",
                            "DatabaseORM.update_user_credits",
                            value,
                        )
                    elif node.func.attr == "values":
                        for keyword in node.keywords:
                            if keyword.arg in CREDIT_ATTRIBUTES:
                                self._record(
                                    node,
                                    "sql-values-write",
                                    keyword.arg,
                                    keyword.value,
                                )
                self.generic_visit(node)

        Visitor(path).visit(tree)

    mutations.sort(key=lambda item: (item.path, item.line, item.column, item.kind))
    return [mutation.as_dict() for mutation in mutations]


def build_report(root: Path) -> dict[str, Any]:
    entries = collect_inventory(root)
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["kind"]] = counts.get(entry["kind"], 0) + 1
    return {
        "schema_version": 1,
        "source_root": "src/app",
        "counts": counts,
        "total": len(entries),
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    report = build_report(args.root.resolve())
    payload: dict[str, Any] = report
    if args.summary:
        payload = {key: report[key] for key in ("schema_version", "counts", "total")}
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
