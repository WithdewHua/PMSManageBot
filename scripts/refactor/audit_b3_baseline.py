"""Audit and seal B3 mechanical cross-domain provenance."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import tarfile
import tempfile
import textwrap
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from scripts.refactor.inventory import Item, inventory
from tests.architecture.checks import scan_all
from tests.architecture.helpers import owner_for_domain, write_baseline

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "tests/architecture/baseline.json"
MAPPING = ROOT / "scripts/refactor/mapping.toml"
B3_BASE = ROOT / "scripts/refactor/B3_BASE"
CREDIT_MIGRATION_PATHS = {
    "src/app/domains/accounts/repository.py",
    "src/app/domains/donation/repository.py",
    "src/app/domains/accounts/router.py",
    "src/app/domains/auction/router.py",
    "src/app/domains/badges/router.py",
    "src/app/domains/blackjack/router/cash.py",
    "src/app/domains/donation/router.py",
    "src/app/domains/invitation/bot.py",
    "src/app/domains/invitation/router.py",
    "src/app/domains/lines/repository.py",
    "src/app/domains/lines/router.py",
    "src/app/domains/luckywheel/router.py",
    "src/app/domains/media_access/router.py",
    "src/app/domains/prediction/router.py",
    "src/app/domains/premium/router.py",
    "src/app/domains/tg_rebind/repository.py",
    "src/app/domains/vaultwarden/router.py",
    "src/app/domains/watch_rewards/service.py",
}

CREDIT_MIGRATION_TARGETS = {
    "add",
    "add_tx",
    "apply_tx",
    "deduct",
    "deduct_tx",
    "emby",
    "move",
    "plex",
    "read_optional",
    "register_cache_invalidation",
    "service",
    "tg",
}

B3_SOURCES = {
    "app.databases.db_func",
    "app.premium",
    "app.modules.custom_line",
    "app.utils.report",
    "app.utils.utils",
}


@dataclass(frozen=True)
class FrozenItem:
    item: Item
    source: str


_FROZEN_ITEMS: dict[str, FrozenItem] | None = None


def _normalized(entry: dict[str, object]) -> str:
    parts = str(entry["key"]).split("|")
    return "|".join([*parts[:2], *parts[3:]])


def _source_module_path(module: str) -> Path:
    return Path(*module.split(".")).with_suffix(".py")


def _frozen_items() -> dict[str, FrozenItem]:
    """Inventory only the exact B3 parent sources from the frozen commit."""
    global _FROZEN_ITEMS
    if _FROZEN_ITEMS is not None:
        return _FROZEN_ITEMS

    base = B3_BASE.read_text(encoding="utf-8").strip()
    with tempfile.TemporaryDirectory(prefix="b3-provenance-") as directory:
        root = Path(directory)
        archive = subprocess.Popen(
            ["git", "archive", base, "src/app"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
        )
        assert archive.stdout is not None
        with tarfile.open(fileobj=archive.stdout, mode="r|*") as tar:
            tar.extractall(root, filter="data")
        if archive.wait() != 0:
            raise RuntimeError(f"unable to read frozen B3 parent {base}")

        paths = list((root / "src/app").rglob("*.py"))
        result: dict[str, FrozenItem] = {}
        for item in inventory(paths, root=root):
            source_path = root / item.path
            lines = source_path.read_text(encoding="utf-8").splitlines()
            source = "\n".join(lines[item.start_line - 1 : item.end_line])
            result[item.id] = FrozenItem(item=item, source=source)
        _FROZEN_ITEMS = result
        return result


def _mapping_items() -> list[dict[str, object]]:
    with MAPPING.open("rb") as stream:
        return tomllib.load(stream)["items"]


def _source_mappings(mappings: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        item
        for item in mappings
        if str(item["id"]).split(":", 1)[0] in B3_SOURCES
        and item.get("kind") in {"function", "method", "import"}
    ]


def _module_for_path(path: str) -> str:
    return ".".join(Path(path).with_suffix("").parts[1:])


def _enclosing_function(path: Path, line: int) -> str | None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str]] = []

    def walk(body: list[ast.stmt], prefix: str = "") -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.lineno <= line <= node.end_lineno:
                    found.append((node.end_lineno, f"{prefix}{node.name}"))
                walk(node.body, f"{prefix}{node.name}.")
            elif isinstance(node, ast.ClassDef):
                walk(node.body, f"{prefix}{node.name}.")

    walk(tree.body)
    return min(found)[1] if found else None


def _short_name(item_id: str) -> str:
    return item_id.split(":", 1)[-1].split("#", 1)[0].split(".")[-1]


def _target_modules(mapping: dict[str, object]) -> set[str]:
    return {
        str(target)
        for target in [mapping.get("target"), *mapping.get("split_targets", [])]
        if target
    }


def _mapping_for_source(
    source_id: str, mappings: list[dict[str, object]]
) -> dict[str, object] | None:
    return next((item for item in mappings if item.get("id") == source_id), None)


def _source_import_matches(
    frozen: dict[str, FrozenItem], module: str, symbol: str
) -> list[str]:
    matches: list[str] = []
    for source_id, frozen_item in frozen.items():
        if frozen_item.item.kind != "import":
            continue
        text = frozen_item.source
        if module in text and (not symbol or symbol in text):
            matches.append(source_id)
    return matches


def _source_function_matches(
    source_mappings: list[dict[str, object]],
    *,
    name: str,
    target: str | None = None,
    target_domain: str | None = None,
) -> list[str]:
    matches: list[str] = []
    for mapping in source_mappings:
        if mapping.get("kind") not in {"function", "method"}:
            continue
        if _short_name(str(mapping["id"])) != name:
            continue
        mapped_target = str(mapping.get("target", ""))
        if target is not None and mapped_target != target:
            continue
        if target_domain is not None and not mapped_target.startswith(
            f"app.domains.{target_domain}."
        ):
            continue
        matches.append(str(mapping["id"]))
    return matches


def _call_nodes(source: str, target: str) -> list[ast.Call]:
    # Frozen B3 slices may start inside a class body (decorated methods), so the
    # common indentation has to be removed before the slice can be parsed.
    tree = ast.parse(textwrap.dedent(source))
    nodes: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if (
            isinstance(function, ast.Name)
            and function.id == target
            or isinstance(function, ast.Attribute)
            and function.attr == target
        ):
            nodes.append(node)
    return nodes


def _operation_present(source: str, entry: dict[str, object]) -> bool:
    return bool(_call_nodes(source, str(entry.get("target", ""))))


def _current_function_source(entry: dict[str, object]) -> str | None:
    path = ROOT / str(entry["path"])
    line = int(entry["line"])
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, ast.AST]] = []

    def walk(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.lineno <= line <= node.end_lineno:
                    found.append((node.end_lineno, node))
                walk(node.body)
            elif isinstance(node, ast.ClassDef):
                walk(node.body)

    walk(tree.body)
    if not found:
        return None
    return ast.unparse(min(found, key=lambda item: item[0])[1])


def _call_ast_matches(source: str, entry: dict[str, object]) -> bool:
    current = _current_function_source(entry)
    if current is None:
        return False
    target = str(entry.get("target", ""))
    source_nodes = _call_nodes(source, target)
    current_nodes = _call_nodes(current, target)
    if not source_nodes or not current_nodes:
        return False
    return ast.dump(source_nodes[0], include_attributes=False) == ast.dump(
        current_nodes[0], include_attributes=False
    )


def _explicit_mapping(
    entry: dict[str, object], mappings: list[dict[str, object]]
) -> list[dict[str, object]]:
    normalized = _normalized(entry)
    return [item for item in mappings if item.get("b3_key") == normalized]


def _candidate_source_ids(
    entry: dict[str, object],
    *,
    mappings: list[dict[str, object]],
    frozen: dict[str, FrozenItem],
) -> list[str]:
    explicit = _explicit_mapping(entry, mappings)
    if explicit:
        candidates: list[str] = []
        for mapping in explicit:
            source_ids = mapping.get("b3_source_ids") or [mapping.get("b3_source_id")]
            candidates.extend(str(source_id) for source_id in source_ids if source_id)
        return list(dict.fromkeys(candidates))

    source_mappings = _source_mappings(mappings)
    path = str(entry["path"])
    current_module = _module_for_path(path)
    current_path = ROOT / path
    if not current_path.exists():
        return []
    enclosing = _enclosing_function(current_path, int(entry["line"]))
    parts = str(entry["key"]).split("|")
    candidates: list[str] = []

    if entry["kind"] == "import":
        target_module = parts[3]
        symbol = parts[4] if len(parts) > 4 else ""
        if enclosing:
            candidates.extend(
                source_id
                for source_id in _source_function_matches(
                    source_mappings,
                    name=enclosing.split(".")[-1],
                    target=current_module,
                )
                if symbol in frozen[source_id].source
            )
            if candidates:
                return list(dict.fromkeys(candidates))

        function_candidates = _source_function_matches(
            source_mappings, name=symbol, target=target_module
        )
        if function_candidates:
            return function_candidates

        import_candidates: list[str] = []
        for source_id in _source_import_matches(frozen, target_module, symbol):
            mapping = _mapping_for_source(source_id, mappings)
            if mapping is None:
                continue
            targets = _target_modules(mapping)
            bindings = mapping.get("split_bindings", {})
            if current_module in targets or current_module in bindings.get(symbol, []):
                import_candidates.append(source_id)
        if import_candidates:
            return list(dict.fromkeys(import_candidates))

        candidates.extend(
            source_id
            for source_id in {
                str(mapping["id"])
                for mapping in source_mappings
                if mapping.get("target") == current_module
            }
            if source_id in frozen and symbol in frozen[source_id].source
        )
    else:
        if enclosing:
            target = str(entry.get("target", ""))
            same_module = [
                source_id
                for source_id, frozen_item in frozen.items()
                if frozen_item.item.module == current_module
                and frozen_item.item.kind in {"function", "method"}
                and _short_name(source_id) == enclosing.split(".")[-1]
                and (
                    entry["kind"] == "self_call"
                    or _call_nodes(frozen_item.source, target)
                )
            ]
            if same_module:
                return same_module
            candidates.extend(
                source_id
                for source_id in _source_function_matches(
                    source_mappings,
                    name=enclosing.split(".")[-1],
                    target=current_module,
                )
                if source_id in frozen
                and (
                    entry["kind"] == "self_call"
                    or _call_nodes(frozen[source_id].source, target)
                )
            )
            if candidates:
                return list(dict.fromkeys(candidates))

        target_candidates = _source_function_matches(
            source_mappings,
            name=str(entry["target"]),
            target_domain=str(entry["target_domain"]),
        )
        if target_candidates:
            return target_candidates

    return list(dict.fromkeys(candidates))


def _validate_entry(
    entry: dict[str, object],
    *,
    mappings: list[dict[str, object]],
    frozen: dict[str, FrozenItem],
) -> list[str]:
    errors: list[str] = []
    source_id = entry.get("b3_source_id")
    if not isinstance(source_id, str) or source_id not in frozen:
        return [f"missing frozen B3 source for {entry['key']}: {source_id!r}"]

    source_item = frozen[source_id].item
    if source_item.kind not in {"function", "method", "import"}:
        errors.append(
            f"B3 source must be a function/method/import for {entry['key']}: {source_id}"
        )

    explicit = _explicit_mapping(entry, mappings)
    if explicit:
        mapping = next(
            (
                item
                for item in explicit
                if source_id
                in {
                    str(item.get("b3_source_id")),
                    *map(str, item.get("b3_source_ids", [])),
                }
            ),
            None,
        )
        if mapping is None:
            errors.append(
                f"source is not allowed by explicit B3 mapping: {entry['key']}"
            )
        elif not mapping.get("b3_behavior_test"):
            errors.append(f"explicit B3 mapping lacks behavior test: {entry['key']}")
    else:
        candidates = _candidate_source_ids(entry, mappings=mappings, frozen=frozen)
        if len(candidates) != 1 or source_id not in candidates:
            errors.append(
                f"B3 source does not prove the current binding/call for {entry['key']}: "
                f"{source_id}; candidates={candidates}"
            )
        if (
            source_item.kind in {"function", "method"}
            and entry["kind"] in {"call", "facade_call"}
            and not _call_ast_matches(frozen[source_id].source, entry)
        ):
            errors.append(
                f"frozen source does not contain target operation for {entry['key']}: "
                f"{source_id}"
            )

    return errors


def _source_for(entry: dict[str, object], mappings: list[dict[str, object]]) -> str:
    """Return a source only when the exact binding/call can be proven."""
    candidates = _candidate_source_ids(entry, mappings=mappings, frozen=_frozen_items())
    if len(candidates) != 1:
        raise ValueError(
            f"no unique B3 mapping source for {entry['key']}: candidates={candidates}"
        )
    return candidates[0]


def _is_credit_migration_entry(entry: dict[str, object]) -> bool:
    if (
        str(entry.get("path")) not in CREDIT_MIGRATION_PATHS
        or str(entry.get("target_domain")) != "credits"
    ):
        return False
    if entry.get("kind") == "import":
        return True
    return str(entry.get("target")) in CREDIT_MIGRATION_TARGETS


def audit(*, write: bool = False) -> dict[str, object]:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    mappings = _mapping_items()
    frozen = _frozen_items()
    actual = scan_all(ROOT)["cross_domain_calls"]
    baseline_groups: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for entry in baseline["cross_domain_calls"]:
        baseline_groups[_normalized(entry)].append(entry)
    actual_groups: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for entry in actual:
        actual_groups[_normalized(entry)].append(entry)
    previous_by_key: dict[str, dict[str, object]] = {}
    for key, current_entries in actual_groups.items():
        previous_entries = sorted(
            baseline_groups.get(key, []),
            key=lambda item: int(str(item["key"]).split("|")[2]),
        )
        for current, previous in zip(
            sorted(
                current_entries,
                key=lambda item: int(str(item["key"]).split("|")[2]),
            ),
            previous_entries,
            strict=False,
        ):
            previous_by_key[str(current["key"])] = previous

    errors: list[str] = []
    sealed: list[dict[str, object]] = []
    new_count = 0
    sealed_b3 = 0

    for entry in actual:
        previous = previous_by_key.get(str(entry["key"]))
        if _is_credit_migration_entry(entry):
            sealed_entry = {**(previous or {}), **entry}
            sealed_entry.pop("b3_source_id", None)
            sealed.append(sealed_entry)
            continue
        if previous is None:
            try:
                source_id = _source_for(entry, mappings)
            except ValueError as error:
                errors.append(str(error))
                continue
            sealed_entry = {
                **entry,
                "owner": owner_for_domain(
                    str(entry.get("source_domain") or entry.get("target_domain") or "")
                ),
                "b3_source_id": source_id,
            }
            new_count += 1
        else:
            sealed_entry = {**previous, **entry}

        entry_errors = (
            _validate_entry(sealed_entry, mappings=mappings, frozen=frozen)
            if "b3_source_id" in sealed_entry
            else []
        )
        errors.extend(entry_errors)
        sealed_b3 += int("b3_source_id" in sealed_entry and not entry_errors)
        sealed.append(sealed_entry)

    result = {
        "ok": not errors,
        "new": new_count,
        "b3": sealed_b3,
        "total": len(sealed),
        "errors": errors,
    }
    if write and not errors:
        baseline["cross_domain_calls"] = sorted(sealed, key=lambda item: item["key"])
        # 统一走 helpers 的写入口，让 contract_ignore_counts 始终反映 pyproject。
        write_baseline(baseline, BASELINE)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    result = audit(write=args.write)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
