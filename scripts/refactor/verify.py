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


def _normalized(
    item: Item,
    node: ast.stmt,
    *,
    target_class: str = "",
    allow_import_reorder: bool = False,
) -> str:
    """Normalize import paths, relocation self-references, and known path anchors."""
    import copy

    node = copy.deepcopy(node)
    if isinstance(node, ast.ClassDef):
        node.body = [ast.Pass()]  # Every class member is compared separately.

    class Normalizer(ast.NodeTransformer):
        def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST | None:
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

        def visit_Import(self, node: ast.Import) -> ast.AST | None:
            for alias in node.names:
                if alias.name.startswith("app."):
                    alias.name = "__IMPORT_PATH__"
            return node

        def visit_Call(self, node: ast.Call) -> ast.AST:
            self.generic_visit(node)
            persisted = {
                "app.webapp.routers.activities.blackjack:_schedule_blackjack_timeout": (
                    "_settle_blackjack_hand_on_timeout",
                    "app.webapp.routers.activities.blackjack:_settle_blackjack_hand_on_timeout",
                ),
                "app.webapp.routers.activities.treasure:schedule_auto_reopen_treasure_issue": (
                    "_auto_create_next_treasure_issue_from",
                    "app.webapp.routers.activities.treasure:_auto_create_next_treasure_issue_from",
                ),
            }
            if (
                item.id in persisted
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_async_job"
            ):
                original_name, original_path = persisted[item.id]
                for keyword in node.keywords:
                    if keyword.arg != "func":
                        continue
                    if (
                        isinstance(keyword.value, ast.Name)
                        and keyword.value.id == original_name
                    ):
                        keyword.value = ast.Constant(value="__B1_PERSISTED_TASK__")
                    elif (
                        isinstance(keyword.value, ast.Constant)
                        and keyword.value.value == original_path
                    ):
                        keyword.value.value = "__B1_PERSISTED_TASK__"

            if (
                item.id
                in {
                    "app.webapp.schemas.user:CustomLineListResponse.lines",
                    "app.webapp.schemas.user:LineScheduleListResponse.schedules",
                }
                and isinstance(node.func, ast.Name)
                and node.func.id == "Field"
                and not node.args
                and len(node.keywords) == 1
                and node.keywords[0].arg == "default"
                and isinstance(node.keywords[0].value, ast.List)
                and not node.keywords[0].value.elts
            ):
                return ast.List(elts=[], ctx=ast.Load())
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
    if allow_import_reorder:

        class SortLocalImports(ast.NodeTransformer):
            def generic_visit(self, node: ast.AST) -> ast.AST:
                super().generic_visit(node)
                for field, statements in ast.iter_fields(node):
                    if field not in {"body", "orelse", "finalbody"} or not isinstance(
                        statements, list
                    ):
                        continue
                    start = 0
                    while start < len(statements):
                        if not isinstance(
                            statements[start], (ast.Import, ast.ImportFrom)
                        ):
                            start += 1
                            continue
                        end = start + 1
                        while end < len(statements) and isinstance(
                            statements[end], (ast.Import, ast.ImportFrom)
                        ):
                            end += 1
                        group = statements[start:end]
                        relocated = [
                            import_node
                            for import_node in group
                            if isinstance(import_node, ast.ImportFrom)
                            and import_node.module == "__IMPORT_PATH__"
                        ]
                        if relocated:
                            group = [
                                import_node
                                for import_node in group
                                if import_node not in relocated
                            ]
                            group.append(
                                ast.ImportFrom(
                                    module="__IMPORT_PATH__",
                                    names=sorted(
                                        (
                                            alias
                                            for import_node in relocated
                                            for alias in import_node.names
                                        ),
                                        key=lambda alias: (
                                            alias.name,
                                            alias.asname or "",
                                        ),
                                    ),
                                    level=0,
                                )
                            )
                        group.sort(
                            key=lambda value: ast.dump(value, include_attributes=False)
                        )
                        statements[start:end] = group
                        start += len(group)
                return node

        node = SortLocalImports().visit(node)
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
    current_items = inventory(
        (current_root / "src/app").rglob("*.py"), root=current_root
    )
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
    current_ids = {item.id for item in current_items}
    for key in sorted(entries.keys() - base_ids):
        # B2/B3 can add imports or package docstrings to still-active modules.
        # Require each current-only inventory item to be explicitly reviewed.
        if key not in current_ids or entries[key].get("source_state") != "current":
            errors.append(f"stale or unreviewed current-only mapping: {key}")
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
            if item.id in current_ids and item.module.startswith(
                ("app.webapp", "app.handlers")
            ):
                errors.append(f"retained B2 unit marked deleted: {item.id}")
            continue
        if action == "assemble":
            approved = (
                item.id == "app.databases.db:DatabaseORM"
                or item.id
                in {
                    "app.main:set_bot_commands",
                    "app.main:start_api_server",
                    "app.webapp:setup_static_files",
                }
                or item.kind
                in {"import", "package_import", "statement", "docstring", "export"}
                and item.module
                in {
                    "app.main",
                    "app.webapp",
                    "app.webapp.routers",
                    "app.webapp.schemas",
                    "app.webapp.schemas.blackjack_tournament",
                    "app.handlers",
                }
                or item.id == "app.webapp.schemas.blackjack_tournament:@import:2"
                and entry.get("target") == "app.domains.blackjack.schemas"
                and any(
                    candidate.name == "BlackjackHandResponse"
                    and candidate.kind == "class"
                    for candidate in destination("app.domains.blackjack.schemas")[0]
                )
                or item.name == "__all__"
                and item.module
                in {"app.handlers.status", "app.handlers.user", "app.webapp.routers"}
                or item.name == "router"
                and item.module
                in {"app.webapp.routers.user", "app.webapp.routers.admin"}
            )
            target = entry.get("target")
            if not approved or not entry.get("reason", "").strip():
                errors.append(f"unreviewed assembly unit: {item.id}")
            elif not isinstance(target, str) or not _module_paths(current_root, target):
                errors.append(f"missing assembly destination: {item.id} -> {target}")
            continue
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
        allow_import_reorder = entry.get("normalize_local_import_order") is True
        if allow_import_reorder and item.id not in {
            "app.webapp.routers.admin:admin_delete_custom_line",
            "app.webapp.routers.admin:admin_offline_custom_line",
            "app.webapp.routers.admin:admin_set_custom_line_tags",
            "app.webapp.routers.admin:admin_update_custom_line",
            "app.webapp.routers.admin:approve_custom_line",
        }:
            errors.append(f"unreviewed local import normalization: {item.id}")
            continue
        if item.kind in {"import", "package_import"}:
            bindings = _bindings(source_node)
            relocated = entry.get("redistributed_to", [])
            if not isinstance(relocated, list) or any(
                not isinstance(other, str) or not other.startswith("app.")
                for other in relocated
            ):
                errors.append(f"invalid import redistribution: {item.id}")
                continue
            if relocated and not entry.get("reason", "").startswith(
                "B2 reviewed import redistribution:"
            ):
                errors.append(f"unreviewed import redistribution: {item.id}")
            imported = set()
            for importing_module in [module, *relocated]:
                imported_items, importing_nodes = destination(importing_module)
                imported.update(
                    binding
                    for imported_item in imported_items
                    if imported_item.kind in {"import", "package_import"}
                    for binding in _bindings(importing_nodes[imported_item.id])
                )
            if bindings - imported and "*" not in bindings:
                errors.append(
                    f"missing import bindings: {item.id} -> {module}: {sorted(bindings - imported)}"
                )
            continue
        if item.kind in {"statement", "docstring"}:
            anonymous[(module, target_class, item.kind)][
                _normalized(
                    item,
                    source_node,
                    target_class=target_class,
                    allow_import_reorder=allow_import_reorder,
                )
            ] += 1
            continue
        if not matches:
            errors.append(
                f"missing moved {item.kind}: {item.id} -> {module}{'.' + target_class if target_class else ''}"
            )
        elif not any(
            _normalized(
                item,
                source_node,
                target_class=target_class,
                allow_import_reorder=allow_import_reorder,
            )
            == _normalized(
                item,
                target_nodes[match.id],
                target_class=target_class,
                allow_import_reorder=allow_import_reorder,
            )
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
