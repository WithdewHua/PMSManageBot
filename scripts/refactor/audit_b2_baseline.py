"""Audit B2 architecture debt against the frozen B1 source, before sealing it.

Only previously existing calls/imports mechanically relocated from B1 may be
added to the architecture baseline. This does not write or regenerate baselines.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import tempfile
import tomllib
from collections import defaultdict
from pathlib import Path
from typing import Any

from scripts.refactor.inventory import Item, inventory
from scripts.refactor.verify import _nodes, _normalized
from tests.architecture.checks import scan_all
from tests.architecture.helpers import owner_for_domain

ROOT = Path(__file__).resolve().parents[2]
B2_BASE = ROOT / "scripts/refactor/B2_BASE"
# Immutable B1 parent of this B2 relocation; changing B2_BASE alone must not
# move the source-of-truth for inherited debt.
FROZEN_B2_PARENT = "a0d3af510257ca80c277574d91ece353cc04e502"


def _units(root: Path) -> tuple[dict[str, Item], dict[str, ast.stmt]]:
    items = inventory((root / "src/app").rglob("*.py"), root=root)
    return {item.id: item for item in items}, _nodes(root, items)


def _mapping(root: Path) -> dict[str, dict[str, Any]]:
    with (root / "scripts/refactor/mapping.toml").open("rb") as stream:
        entries = tomllib.load(stream)["items"]
    return {entry["id"]: entry for entry in entries}


def _enclosing_unit(record: dict[str, Any], items: dict[str, Item]) -> Item | None:
    matches = [
        item
        for item in items.values()
        if item.path == record["path"]
        and item.start_line <= record["line"] <= item.end_line
        and item.kind in {"function", "method", "import", "package_import"}
    ]
    return (
        min(matches, key=lambda item: item.end_line - item.start_line)
        if matches
        else None
    )


def _sources_for_target(
    destination: Item,
    base_items: dict[str, Item],
    mapping: dict[str, dict[str, Any]],
) -> list[Item]:
    result = [
        base_items[source_id]
        for source_id, entry in mapping.items()
        if source_id in base_items
        and entry.get("action") not in {"delete", "assemble"}
        and entry.get("target") == destination.module
        and base_items[source_id].kind == destination.kind
        and base_items[source_id].name.rsplit(".", 1)[-1]
        == destination.name.rsplit(".", 1)[-1]
    ]
    if destination.id in base_items:
        result.append(base_items[destination.id])
    return result


def _call_at_line(node: ast.stmt, line: int) -> list[ast.Call]:
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and child.lineno == line
    ]


def _import_names(node: ast.stmt) -> set[str]:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {alias.asname or alias.name.split(".")[0] for alias in node.names}
    return set()


def _import_origin_matches(
    source: ast.stmt,
    symbol: str,
    target_module: str,
    mapping: dict[str, dict[str, Any]],
) -> bool:
    """Prove a changed import path via the imported definition's own mapping."""
    if not isinstance(source, (ast.Import, ast.ImportFrom)):
        return False
    matching_aliases = [
        alias
        for alias in source.names
        if alias.asname == symbol or alias.name == symbol
    ]
    if not matching_aliases:
        return False
    original_module = source.module if isinstance(source, ast.ImportFrom) else None
    if original_module == target_module or any(
        isinstance(source, ast.Import)
        and alias.name == target_module
        or original_module is not None
        and f"{original_module}.{alias.name}" == target_module
        for alias in matching_aliases
    ):
        return True
    return any(
        entry.get("target") == target_module
        and entry.get("action") != "delete"
        and original_module is not None
        and (
            entry["id"].split(":", 1)[0] == original_module
            or entry["id"].split(":", 1)[0].startswith(f"{original_module}.")
        )
        and entry["id"].rsplit(":", 1)[-1] == alias.name
        for alias in matching_aliases
        for entry in mapping.values()
    )


def _imported_call_has_b1_binding(
    record: dict[str, Any],
    source_module: str,
    base_module_imports: list[ast.stmt],
    current_module_imports: list[ast.stmt],
    base_function: ast.stmt,
    current_function: ast.stmt,
    mapping: dict[str, dict[str, Any]],
) -> bool:
    """A relocated call must still resolve through its original mapped binding."""
    calls = [
        call
        for call in _call_at_line(current_function, record["line"])
        if isinstance(call.func, (ast.Attribute, ast.Name))
        and (call.func.attr if isinstance(call.func, ast.Attribute) else call.func.id)
        == record["target"]
    ]
    if not calls:
        return False
    original_imports = [
        node
        for node in [*base_module_imports, *ast.walk(base_function)]
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    current_imports = [
        node
        for node in [*current_module_imports, *ast.walk(current_function)]
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    for call in calls:
        binding = call.func
        while isinstance(binding, ast.Attribute):
            binding = binding.value
        if not isinstance(binding, ast.Name):
            continue
        local = binding.id
        for imported in current_imports:
            for alias in imported.names:
                if (alias.asname or alias.name.split(".")[0]) != local:
                    continue
                module = (
                    imported.module
                    if isinstance(imported, ast.ImportFrom)
                    else alias.name
                )
                if module is None:
                    continue
                if (
                    isinstance(imported, ast.ImportFrom)
                    and module.count(".") == 2
                    and alias.name
                    in {"service", "schemas", "models", "repository", "rules"}
                ):
                    module = f"{module}.{alias.name}"
                if not module.startswith(f"app.domains.{record['target_domain']}."):
                    continue
                if mapping.get(f"{source_module}:{local}", {}).get("target") == module:
                    return True
                if any(
                    _import_origin_matches(source, local, module, mapping)
                    for source in original_imports
                ):
                    return True
    return False


def audit_added_violations(
    base_root: Path, current_root: Path
) -> tuple[list[str], dict[str, str]]:
    """Return failures and source IDs for every newly visible AST violation."""
    previous = json.loads(
        (base_root / "tests/architecture/baseline.json").read_text(encoding="utf-8")
    )
    before = {row["key"] for row in previous["cross_domain_calls"]}
    current = scan_all(current_root)
    added = [row for row in current["cross_domain_calls"] if row["key"] not in before]
    base_items, base_nodes = _units(base_root)
    now_items, now_nodes = _units(current_root)
    mapping = _mapping(current_root)
    base_module_imports: dict[str, list[ast.stmt]] = defaultdict(list)
    current_module_imports: dict[str, list[ast.stmt]] = defaultdict(list)
    for items, nodes, index in (
        (base_items, base_nodes, base_module_imports),
        (now_items, now_nodes, current_module_imports),
    ):
        for item in items.values():
            if item.kind in {"import", "package_import"}:
                index[item.module].append(nodes[item.id])
    source_modules_by_destination: dict[str, set[str]] = defaultdict(set)
    imports_by_source_module: dict[str, list[Item]] = defaultdict(list)
    for item in base_items.values():
        if item.kind in {"function", "method", "class"}:
            destination = mapping.get(item.id, {}).get("target")
            if isinstance(destination, str):
                source_modules_by_destination[destination].add(item.module)
        elif item.kind in {"import", "package_import"}:
            imports_by_source_module[item.module].append(item)
    errors: list[str] = []
    proofs: dict[str, str] = {}
    for record in added:
        target = _enclosing_unit(record, now_items)
        if target is None:
            errors.append(f"no enclosing current source: {record['key']}")
            continue
        sources = _sources_for_target(target, base_items, mapping)
        if target.kind in {"function", "method"}:
            matching = [
                source
                for source in sources
                if _normalized(
                    source,
                    base_nodes[source.id],
                    allow_import_reorder=mapping.get(source.id, {}).get(
                        "normalize_local_import_order", False
                    ),
                )
                == _normalized(
                    source,
                    now_nodes[target.id],
                    allow_import_reorder=mapping.get(source.id, {}).get(
                        "normalize_local_import_order", False
                    ),
                )
            ]
            if record["kind"] == "import":
                present = any(
                    isinstance(node, (ast.Import, ast.ImportFrom))
                    and node.lineno == record["line"]
                    and record.get("symbol") in _import_names(node)
                    for node in ast.walk(now_nodes[target.id])
                )
            else:
                present = bool(_call_at_line(now_nodes[target.id], record["line"]))
            if len(matching) != 1 or not present:
                errors.append(
                    f"new or changed call/import with no unique B1 source: {record['key']}"
                )
            else:
                proofs[record["key"]] = matching[0].id
            if len(matching) == 1 and present and record["kind"] == "call":
                source = matching[0]
                if not _imported_call_has_b1_binding(
                    record,
                    source.module,
                    base_module_imports[source.module],
                    current_module_imports[target.module],
                    base_nodes[source.id],
                    now_nodes[target.id],
                    mapping,
                ):
                    errors.append(f"changed imported call binding: {record['key']}")
            if len(matching) == 1 and present and record["kind"] == "import":
                old_imports = [
                    node
                    for node in ast.walk(base_nodes[matching[0].id])
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                ]
                if not any(
                    _import_origin_matches(
                        node, record["symbol"], record["target_module"], mapping
                    )
                    for node in old_imports
                ):
                    errors.append(f"unmapped B2 import target: {record['key']}")
            continue
        if target.kind in {"import", "package_import"}:
            symbol = record.get("symbol")
            origin_modules = source_modules_by_destination.get(target.module, set())
            matching = [
                source
                for source_module in origin_modules
                for source in imports_by_source_module[source_module]
                if symbol in _import_names(base_nodes[source.id])
                and _import_origin_matches(
                    base_nodes[source.id], symbol, record["target_module"], mapping
                )
            ]
            if not matching and target.id in base_items:
                prior = base_items[target.id]
                if _import_origin_matches(
                    base_nodes[prior.id], symbol, record["target_module"], mapping
                ):
                    matching = [prior]
            if not matching and symbol:
                # An import can replace a direct call to a function that was
                # previously defined in the same legacy router module.
                matching = [
                    base_items[f"{source_module}:{symbol}"]
                    for source_module in origin_modules
                    if f"{source_module}:{symbol}" in base_items
                    and mapping.get(f"{source_module}:{symbol}", {}).get("target")
                    == record.get("target_module")
                ]
            if not matching:
                errors.append(f"new import with no B1 binding: {record['key']}")
            elif len({source.id for source in matching}) == 1:
                proofs[record["key"]] = matching[0].id
            else:
                errors.append(f"ambiguous B2 import source: {record['key']}")
            continue
        errors.append(f"unsupported debt provenance: {record['key']}")
    old_budget = {row["path"] for row in previous["line_budgets"]}
    for row in current["line_budgets"]:
        if row["path"] not in old_budget:
            errors.append(f"new over-budget file: {row['path']}")
    return errors, proofs


def _edge_aliases(node: ast.stmt, target: str) -> set[str]:
    """Return bound names that directly import the exact protected module."""
    if isinstance(node, ast.ImportFrom) and node.module:
        return {
            alias.asname or alias.name
            for alias in node.names
            if node.module == target or f"{node.module}.{alias.name}" == target
        }
    if isinstance(node, ast.Import):
        return {
            alias.asname or alias.name for alias in node.names if alias.name == target
        }
    return set()


def _import_index(
    items: dict[str, Item], nodes: dict[str, ast.stmt]
) -> dict[str, list[ast.stmt]]:
    index: dict[str, list[ast.stmt]] = defaultdict(list)
    for item in items.values():
        if item.kind not in {"import", "package_import", "function", "method"}:
            continue
        index[item.module].extend(
            node
            for node in ast.walk(nodes[item.id])
            if isinstance(node, (ast.Import, ast.ImportFrom))
        )
    return index


def _edge_has_b1_source(
    importer: str,
    imported: str,
    base_imports: dict[str, list[ast.stmt]],
    current_imports: dict[str, list[ast.stmt]],
    moved_functions: dict[str, list[tuple[Item, Item]]],
    base_nodes: dict[str, ast.stmt],
    current_nodes: dict[str, ast.stmt],
    mapping: dict[str, dict[str, Any]],
) -> bool:
    for current_import in current_imports.get(importer, []):
        for symbol in _edge_aliases(current_import, imported):
            bound_name = symbol.split(".")[0]
            for source, target in moved_functions.get(importer, []):
                source_node, target_node = (
                    base_nodes[source.id],
                    current_nodes[target.id],
                )
                if not all(
                    any(
                        isinstance(node, ast.Name) and node.id == bound_name
                        for node in ast.walk(body)
                    )
                    for body in (source_node, target_node)
                ):
                    continue
                if (
                    mapping.get(f"{source.module}:{symbol}", {}).get("target")
                    == imported
                ):
                    return True
                if any(
                    _import_origin_matches(node, symbol, imported, mapping)
                    for node in base_imports.get(source.module, [])
                ):
                    return True
    return False


def audit_import_contracts(base_root: Path, current_root: Path) -> list[str]:
    """Reject unreviewed ignore edges and facade importers; no count-only audit."""

    def contracts(root: Path) -> dict[str, dict[str, Any]]:
        with (root / "pyproject.toml").open("rb") as stream:
            return {
                c["name"]: c
                for c in tomllib.load(stream)["tool"]["importlinter"]["contracts"]
            }

    before, after = contracts(base_root), contracts(current_root)
    current_toml = (current_root / "pyproject.toml").read_text(encoding="utf-8")

    def has_owner_comment(value: str) -> bool:
        importer = value.split(" -> ", 1)[0]
        parts = importer.split(".")
        if len(parts) < 3 or parts[:2] != ["app", "domains"]:
            return False
        owner = owner_for_domain(parts[2])
        lines = re.findall(
            rf'^\s*"{re.escape(value)}"\s*,[^\n]*$', current_toml, re.MULTILINE
        )
        return bool(lines) and all(
            f"# {owner} (B2 inherited)" in line for line in lines
        )

    base_items, base_nodes = _units(base_root)
    current_items, current_nodes = _units(current_root)
    mapping = _mapping(current_root)
    base_imports = _import_index(base_items, base_nodes)
    current_imports = _import_index(current_items, current_nodes)
    moved_functions: dict[str, list[tuple[Item, Item]]] = defaultdict(list)
    for source in base_items.values():
        if source.kind not in {"function", "method"}:
            continue
        destination = mapping.get(source.id, {}).get("target")
        if isinstance(destination, str):
            target = current_items.get(f"{destination}:{source.name}")
            if target is not None:
                moved_functions[destination].append((source, target))
    errors: list[str] = []
    for name, contract in after.items():
        ignored = contract.get("ignore_imports", [])
        if len(ignored) != len(set(ignored)):
            errors.append(f"duplicate ignore edge: {name}")
        old = set(before.get(name, {}).get("ignore_imports", []))
        for edge in set(ignored) - old:
            if " -> " not in edge:
                errors.append(f"invalid ignore edge: {name}: {edge}")
                continue
            importer, imported = edge.split(" -> ", 1)
            if not has_owner_comment(edge):
                errors.append(f"missing B2 exception owner: {name}: {edge}")
            if not importer.startswith("app.domains.") or not _edge_has_b1_source(
                importer,
                imported,
                base_imports,
                current_imports,
                moved_functions,
                base_nodes,
                current_nodes,
                mapping,
            ):
                errors.append(f"unproven B2 import exception: {name}: {edge}")
    legacy = "Legacy database facade freeze"
    for name, contract in after.items():
        if name == legacy:
            continue
        unexpected = set(contract.get("allowed_importers", [])) - set(
            before.get(name, {}).get("allowed_importers", [])
        )
        errors.extend(
            f"unreviewed B2 allowed importer: {name}: {importer}"
            for importer in sorted(unexpected)
        )
    old_importers = set(before[legacy]["allowed_importers"])
    for importer in set(after[legacy]["allowed_importers"]) - old_importers:
        if not has_owner_comment(importer):
            errors.append(f"missing B2 importer owner: {importer}")
        if not importer.startswith("app.domains.") or not any(
            _edge_has_b1_source(
                importer,
                imported,
                base_imports,
                current_imports,
                moved_functions,
                base_nodes,
                current_nodes,
                mapping,
            )
            for imported in (
                "app.databases.db",
                "app.databases.db_func",
                "app.databases",
            )
        ):
            errors.append(f"unproven B2 facade importer: {importer}")
    return errors


def audit(base_root: Path, current_root: Path) -> list[str]:
    errors, proofs = audit_added_violations(base_root, current_root)
    current_baseline = json.loads(
        (current_root / "tests/architecture/baseline.json").read_text(encoding="utf-8")
    )
    expected_commit = (current_root / "scripts/refactor/B2_BASE").read_text().strip()
    if current_baseline.get("b2_source_commit") != expected_commit or (
        current_root.resolve() == ROOT and expected_commit != FROZEN_B2_PARENT
    ):
        errors.append("B2 baseline source commit missing or changed")
    for row in current_baseline["cross_domain_calls"]:
        if row["key"] in proofs and row.get("b2_source_id") != proofs[row["key"]]:
            errors.append(f"B2 baseline source ID missing or changed: {row['key']}")
    return errors + audit_import_contracts(base_root, current_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=B2_BASE.read_text().strip())
    args = parser.parse_args()
    if args.base != FROZEN_B2_PARENT or B2_BASE.read_text().strip() != FROZEN_B2_PARENT:
        raise ValueError("B2 source must be the frozen B1 parent")
    with tempfile.TemporaryDirectory(prefix="pms-b2-audit-") as temp:
        base = Path(temp) / "base"
        result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(base), args.base],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        try:
            errors = audit(base, ROOT)
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(base)],
                cwd=ROOT,
                capture_output=True,
                check=False,
            )
    print(
        json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False, indent=2)
    )
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
