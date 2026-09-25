"""Compare a relocated worktree with a Git base without modifying either tree."""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scripts.refactor.inventory import Item, inventory
from scripts.refactor.snapshot import _dump


class VerificationError(ValueError):
    """The current tree violates an equivalence invariant."""


# D4 permits exactly these four DatabaseORM self references.
_SELF_REFERENCES = {
    "_badge_to_dict",
    "_gift_pack_condition_label",
    "_resolve_gift_pack_conditions",
    "_GIFT_PACK_COUNT_METHODS",
}
_PREMIUM_LAZY = {
    "check_premium_expiry",
    "check_premium_expiring_soon",
    "apply_download_unlock_to_media",
    "get_and_send_premium_statistics",
}


def _module_paths(root: Path, module: str) -> list[Path]:
    relative = Path("src", *module.split("."))
    file = root / relative.with_suffix(".py")
    package = root / relative / "__init__.py"
    if file.is_file():
        return [file]
    if package.is_file():
        return [package, *sorted(package.parent.glob("part_*.py"))]
    return []


def _nodes(root: Path, items: list[Item]) -> dict[str, ast.stmt]:
    """Recover nodes: Item.ast is an AST dump, not parseable Python source."""
    cache: dict[str, dict[str, ast.stmt]] = {}
    result: dict[str, ast.stmt] = {}
    for item in items:
        if item.path not in cache:
            tree = ast.parse((root / item.path).read_text(encoding="utf-8"))
            cache[item.path] = {
                ast.dump(node, include_attributes=False): node
                for node in ast.walk(tree)
                if isinstance(node, ast.stmt)
            }
        result[item.id] = cache[item.path][item.ast]
    return result


def _normalized(item: Item, node: ast.stmt, *, target_class: str = "") -> str:
    """Normalize only import paths, D4 self references, B1 lazy db and config path."""
    import copy

    node = copy.deepcopy(node)
    if isinstance(node, ast.ClassDef):
        node.body = [ast.Pass()]  # Every class member is compared separately.

    class Normalizer(ast.NodeTransformer):
        def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST:
            if node.module in {"app", "app.domains.blackjack"}:
                for alias in node.names:
                    if (node.module, alias.name) in {
                        ("app", "blackjack_engine"),
                        ("app.domains.blackjack", "rules"),
                    } and alias.asname == "engine":
                        alias.name = "__BLACKJACK_RULES__"
            if node.module and (node.module == "app" or node.module.startswith("app.")):
                node.module = "__IMPORT_PATH__"
            return node

        def visit_Import(self, node: ast.Import) -> ast.AST:
            for alias in node.names:
                if alias.name.startswith("app."):
                    alias.name = "__IMPORT_PATH__"
            return node

        def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
            self.generic_visit(node)
            if (
                item.module == "app.databases.db"
                and item.name.startswith("DatabaseORM.")
                and node.attr in _SELF_REFERENCES
                and isinstance(node.value, ast.Name)
                and node.value.id in {"DatabaseORM", target_class}
            ):
                node.value.id = "__RELOCATED_DB_CLASS__"
            return node

        def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
            self.generic_visit(node)
            if (
                item.id == "app.config:Settings.DATA_PATH"
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "parents"
                and isinstance(node.value.value, ast.Call)
                and isinstance(node.value.value.func, ast.Name)
                and node.value.value.func.id == "Path"
                and len(node.value.value.args) == 1
                and isinstance(node.value.value.args[0], ast.Name)
                and node.value.value.args[0].id == "__file__"
                and isinstance(node.slice, ast.Constant)
                and node.slice.value in (2, 3)
            ):
                node.slice.value = "__SAME_DATA_ROOT__"
            return node

    node = Normalizer().visit(node)
    if (
        item.module == "app.premium"
        and item.name in _PREMIUM_LAZY
        and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        node.body = [
            stmt
            for stmt in node.body
            if not (
                isinstance(stmt, ast.ImportFrom)
                and stmt.module == "__IMPORT_PATH__"
                and [(alias.name, alias.asname) for alias in stmt.names]
                == [("db", None)]
            )
        ]
    return ast.dump(node, include_attributes=False)


def _bindings(node: ast.stmt) -> set[str]:
    if isinstance(node, ast.ImportFrom):
        return {alias.asname or alias.name for alias in node.names}
    if isinstance(node, ast.Import):
        return {alias.asname or alias.name.split(".")[0] for alias in node.names}
    return set()


def compare_inventory(
    base_root: Path, current_root: Path, mapping_file: Path | None = None
) -> list[str]:
    """Compare each inventoried base unit at its mapping-reviewed destination."""
    base_items = inventory((base_root / "src/app").rglob("*.py"), root=base_root)
    if mapping_file is None:
        candidate = current_root / "scripts/refactor/mapping.toml"
        mapping_file = candidate if candidate.is_file() else None
    entries: dict[str, dict[str, Any]] = {}
    if mapping_file is not None:
        with mapping_file.open("rb") as stream:
            for entry in tomllib.load(stream).get("items", []):
                if entry["id"] in entries:
                    raise VerificationError(f"duplicate mapping ID: {entry['id']}")
                entries[entry["id"]] = entry
    errors: list[str] = []
    base_ids = {item.id for item in base_items}
    errors.extend(f"stale mapping: {key}" for key in sorted(entries.keys() - base_ids))
    source_nodes = _nodes(base_root, base_items)
    target_cache: dict[str, tuple[list[Item], dict[str, ast.stmt]]] = {}

    def destination(module: str) -> tuple[list[Item], dict[str, ast.stmt]]:
        if module not in target_cache:
            paths = _module_paths(current_root, module)
            items = inventory(paths, root=current_root) if paths else []
            target_cache[module] = items, _nodes(current_root, items)
        return target_cache[module]

    anonymous: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    for item in base_items:
        entry = entries.get(item.id)
        if entries and entry is None:
            errors.append(f"unmapped source unit: {item.id}")
            continue
        entry = entry or {"target": item.module}
        action = entry.get("action")
        if action == "delete":
            if not entry.get("reason", "").strip():
                errors.append(f"deletion without reason: {item.id}")
            continue
        if action == "assemble":
            continue  # Facade container only; its children must still match.
        module = entry.get("target")
        if module == "TODO":
            module = item.module  # Unmoved B2/B3 items still must match.
        if not isinstance(module, str) or not module.startswith("app."):
            errors.append(f"invalid destination: {item.id}: {module}")
            continue
        target_items, target_nodes = destination(module)
        if (
            not target_items
            and module != item.module
            and _module_paths(current_root, item.module)
        ):
            # Future B2/B3 destination absent: original unit must still match.
            module = item.module
            target_items, target_nodes = destination(module)
        if not target_items:
            errors.append(f"missing destination module: {item.id} -> {module}")
            continue
        target_class = entry.get("class", "")
        if item.parent_id and not target_class:
            target_class = item.name.rsplit(".", 1)[0]
        parents = {target_class}
        if target_class and module.endswith(".repository"):
            parents |= {
                candidate.name
                for candidate in target_items
                if candidate.kind == "class"
                and "/part_" in candidate.path
                and "RepositoryPart" in candidate.name
            }
        matches = [
            candidate
            for candidate in target_items
            if candidate.kind == item.kind
            and candidate.name.rsplit(".", 1)[-1] == item.name.rsplit(".", 1)[-1]
            and (not item.parent_id or candidate.name.rsplit(".", 1)[0] in parents)
        ]
        source_node = source_nodes[item.id]
        if item.kind in {"import", "package_import"}:
            # Imports may be consolidated or distributed; check bound names.
            bindings = _bindings(source_node)
            imported = set().union(
                *(
                    _bindings(target_nodes[x.id])
                    for x in target_items
                    if x.kind in {"import", "package_import"}
                )
            )
            if bindings - imported and "*" not in bindings:
                errors.append(
                    f"missing import bindings: {item.id} -> {module}: {sorted(bindings - imported)}"
                )
            continue
        if item.kind in {"statement", "docstring"}:
            anonymous[(module, target_class, item.kind)][
                _normalized(item, source_node, target_class=target_class)
            ] += 1
            continue
        if not matches:
            errors.append(
                f"missing moved {item.kind}: {item.id} -> {module}{'.' + target_class if target_class else ''}"
            )
        elif not any(
            _normalized(item, source_node, target_class=target_class)
            == _normalized(item, target_nodes[match.id], target_class=target_class)
            for match in matches
        ):
            errors.append(
                f"AST changed: {item.id} -> {module}{'.' + target_class if target_class else ''}"
            )
    for (module, parent, kind), expected in anonymous.items():
        items, nodes = destination(module)
        observed = Counter(
            _normalized(item, nodes[item.id], target_class=parent)
            for item in items
            if item.kind == kind
            and (item.name.rsplit(".", 1)[0] if item.parent_id else "") == parent
        )
        for syntax, count in expected.items():
            if observed[syntax] < count:
                errors.append(
                    f"missing or changed {kind}: {module}{'.' + parent if parent else ''} ({count} expected, {observed[syntax]} found): {syntax[:100]}"
                )
    return errors


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
    """Collect evidence into a temporary directory, never into either checkout."""
    with tempfile.TemporaryDirectory(prefix="pms-snapshot-") as temporary:
        output = Path(temporary) / "snapshot.json"
        import_errors = Path(temporary) / "module-import-errors.json"
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
