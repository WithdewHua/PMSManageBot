"""Compare a relocated worktree with a Git base without modifying either tree."""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.refactor.inventory import Item, inventory
from scripts.refactor.snapshot import _dump


class VerificationError(ValueError):
    """The current tree violates an equivalence invariant."""


def _canonical_ast(source: str) -> str:
    tree = ast.parse(source)

    class Normalizer(ast.NodeTransformer):
        def visit_Import(self, node: ast.Import) -> ast.AST | None:
            return None

        def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST | None:
            return None

        def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
            node = self.generic_visit(node)
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "DatabaseORM"
            ):
                return ast.copy_location(
                    ast.Constant(value=f"__SELF_REF__.{node.attr}"), node
                )
            return node

        def visit_Call(self, node: ast.Call) -> ast.AST:
            node = self.generic_visit(node)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"add_async_job", "add_sync_job"}
            ):
                return ast.copy_location(ast.Constant(value="__SCHEDULER_CALL__"), node)
            return node

    normalized = Normalizer().visit(tree)
    ast.fix_missing_locations(normalized)
    return ast.dump(normalized, annotate_fields=True, include_attributes=False)


def _item_key(item: Item) -> tuple[str, str, str]:
    local_name = item.name.rsplit(".", 1)[-1]
    return item.kind, local_name, _canonical_ast(item.ast)


def inventory_fingerprint(root: Path) -> Counter[tuple[str, str, str]]:
    paths = sorted((root / "src").rglob("*.py"))
    items = inventory(paths, root=root)
    sources: dict[str, list[str]] = {}
    result: Counter[tuple[str, str, str]] = Counter()
    import textwrap

    for item in items:
        lines = sources.setdefault(
            item.path, (root / item.path).read_text(encoding="utf-8").splitlines()
        )
        source = textwrap.dedent("\n".join(lines[item.start_line - 1 : item.end_line]))
        result[(item.kind, item.name.rsplit(".", 1)[-1], _canonical_ast(source))] += 1
    return result


def compare_inventory(base_root: Path, current_root: Path) -> list[str]:
    """Return AST differences after the three D11 source rewrites are removed."""
    base = inventory_fingerprint(base_root)
    current = inventory_fingerprint(current_root)
    differences: list[str] = []
    for key in sorted(set(base) | set(current)):
        if base[key] != current[key]:
            differences.append(
                f"{key[0]} {key[1]}: base={base[key]} current={current[key]}"
            )
    return differences


def _route_identity(route: dict[str, Any]) -> tuple[Any, ...]:
    return (
        route.get("path"),
        tuple(route.get("methods", [])),
        route.get("name"),
        route.get("endpoint"),
        json.dumps(route.get("response_model"), sort_keys=True, ensure_ascii=False),
    )


def _segments(path: str) -> list[str]:
    return [segment for segment in path.split("/") if segment]


def routes_overlap(first: dict[str, Any], second: dict[str, Any]) -> bool:
    if not set(first.get("methods", [])) & set(second.get("methods", [])):
        return False
    left, right = (
        _segments(first.get("path") or ""),
        _segments(second.get("path") or ""),
    )
    if len(left) != len(right):
        return False
    return all(
        a == b or a.startswith("{") or b.startswith("{")
        for a, b in zip(left, right, strict=True)
    )


def compare_routes(
    base: list[dict[str, Any]], current: list[dict[str, Any]]
) -> list[str]:
    """Allow only route permutations whose paths cannot match the same request."""
    errors: list[str] = []
    if Counter(_route_identity(route) for route in base) != Counter(
        _route_identity(route) for route in current
    ):
        return ["route set changed"]
    current_positions = {
        _route_identity(route): index for index, route in enumerate(current)
    }
    for left_index, left in enumerate(base):
        for right_index in range(left_index + 1, len(base)):
            right = base[right_index]
            left_identity, right_identity = (
                _route_identity(left),
                _route_identity(right),
            )
            if current_positions[left_identity] <= current_positions[right_identity]:
                continue
            if routes_overlap(left, right):
                errors.append(
                    f"overlapping routes reordered: {left.get('path')} and {right.get('path')}"
                )
    return errors


def compare_snapshots(base: dict[str, Any], current: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for section in ("openapi", "metadata", "scheduler", "bot"):
        if section == "openapi":
            if base[section].get("openapi") != current[section].get("openapi"):
                errors.append("OpenAPI document changed")
            errors.extend(
                compare_routes(
                    base[section].get("routes", []), current[section].get("routes", [])
                )
            )
        elif base.get(section) != current.get(section):
            errors.append(f"{section} snapshot changed")
    base_methods = set(base.get("facade", {}).get("public_methods", []))
    current_methods = set(current.get("facade", {}).get("public_methods", []))
    if base_methods != current_methods:
        errors.append("db facade public methods changed")
    for label, snapshot in (("base", base), ("current", current)):
        references = snapshot.get("references", {})
        if any(
            not item.get("resolved", False) for item in references.get("imports", [])
        ):
            errors.append(f"unresolved import in {label} reference snapshot")
        if any(
            not item.get("resolved", False) for item in references.get("strings", [])
        ):
            errors.append(f"unresolved string reference in {label} reference snapshot")
    errors.extend(compare_inventory_snapshots(base, current))
    return errors


def compare_inventory_snapshots(
    base: dict[str, Any], current: dict[str, Any]
) -> list[str]:
    """Compare serialized inventory fingerprints when supplied by callers."""
    if "inventory" not in base or "inventory" not in current:
        return []
    if Counter(base["inventory"]) != Counter(current["inventory"]):
        return ["inventory AST changed"]
    return []


def _run_snapshot(tool_root: Path, target_root: Path) -> dict[str, Any]:
    output = target_root / ".pms-behavior-snapshot.json"
    import_errors = target_root / ".pms-module-import-errors.json"
    env = os.environ.copy()
    env["DATA_DIR"] = str(tool_root / "data")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(tool_root), str(target_root / "src"), env.get("PYTHONPATH", "")]
    )
    code = f"""
import importlib
import json
from pathlib import Path
from scripts.refactor.snapshot import build_snapshot, _dump, _module_name
root = Path({str(target_root)!r})
snapshot = build_snapshot(root)
errors = []
for path in sorted((root / 'src/app').rglob('*.py')):
    module = _module_name(path, root)
    try:
        importlib.import_module(module)
    except Exception as error:
        errors.append({{'module': module, 'error': f'{{type(error).__name__}}: {{error}}'}})
Path({str(output)!r}).write_text(_dump(snapshot), encoding='utf-8')
Path({str(import_errors)!r}).write_text(json.dumps(errors, sort_keys=True), encoding='utf-8')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        # Keep configuration resolution anchored to the checked-out working
        # tree so a temporary Git worktree does not silently use different
        # data/.env defaults.
        cwd=tool_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise VerificationError(
            f"snapshot failed for {target_root}: {result.stderr[-2000:]}"
        )
    module_errors = json.loads(import_errors.read_text(encoding="utf-8"))
    if module_errors:
        raise VerificationError(f"module import failures: {module_errors}")
    return json.loads(output.read_text(encoding="utf-8"))


def verify(base_ref: str, repository: Path) -> list[str]:
    repository = repository.resolve()
    tool_root = repository
    with tempfile.TemporaryDirectory(prefix="pms-verify-") as temporary:
        base_root = Path(temporary) / "base"
        result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(base_root), base_ref],
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise VerificationError(result.stderr.strip())
        try:
            base_snapshot = _run_snapshot(tool_root, base_root)
            current_snapshot = _run_snapshot(tool_root, repository)
            errors = compare_snapshots(base_snapshot, current_snapshot)
            errors.extend(compare_inventory(base_root, repository))
            return errors
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(base_root)],
                cwd=repository,
                capture_output=True,
                check=False,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base", required=True, help="Git ref used as the behavior baseline"
    )
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    args = parser.parse_args()
    errors = verify(args.base, args.repository)
    report = {"ok": not errors, "errors": errors}
    print(_dump(report), end="")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
