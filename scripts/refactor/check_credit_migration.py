"""Check completeness of the atomic-credit migration mapping."""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path
from typing import Any

from scripts.refactor.credit_inventory import build_report

LEGACY_KINDS = {
    "absolute-facade-call",
    "attribute-assignment",
    "attribute-augmented-assignment",
    "sql-values-write",
}


def entry_id(entry: dict[str, Any]) -> str:
    return "|".join(
        str(entry[key]) for key in ("path", "line", "column", "kind", "target")
    )


def load_mapping(path: Path) -> list[dict[str, Any]]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise TypeError("credit mapping must contain [[entries]]")
    return entries


def check_report(
    report: dict[str, Any], mapping: list[dict[str, Any]], *, strict: bool = False
) -> list[str]:
    errors: list[str] = []
    inventory = report.get("entries", [])
    inventory_ids = [entry_id(entry) for entry in inventory]
    mapping_ids = [str(entry.get("id", "")) for entry in mapping]

    for duplicate in sorted(
        {item for item in mapping_ids if mapping_ids.count(item) > 1}
    ):
        errors.append(f"duplicate credit mapping: {duplicate}")
    for missing in sorted(set(inventory_ids) - set(mapping_ids)):
        errors.append(f"missing credit mapping: {missing}")
    for stale in sorted(set(mapping_ids) - set(inventory_ids)):
        errors.append(f"stale credit mapping: {stale}")

    by_id = {entry_id(entry): entry for entry in inventory}
    for mapped in mapping:
        source = by_id.get(str(mapped.get("id", "")))
        if source is None:
            continue
        for field in ("replacement", "transaction_owner", "cache_keys", "status"):
            if field not in mapped:
                errors.append(f"mapping {mapped.get('id')} missing {field}")
        if strict and source["kind"] in LEGACY_KINDS:
            if mapped.get("status") != "migrated":
                errors.append(f"unmigrated credit mutation: {mapped.get('id')}")
            if not mapped.get("replacement"):
                errors.append(f"missing replacement for: {mapped.get('id')}")

    return errors


def check(root: Path, mapping_path: Path, *, strict: bool = False) -> list[str]:
    report = build_report(root)
    mapping = load_mapping(mapping_path)
    return check_report(report, mapping, strict=strict)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--mapping",
        type=Path,
        default=Path("scripts/refactor/credit_migration.toml"),
    )
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    errors = check(args.root.resolve(), args.mapping, strict=args.strict)
    print(
        json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False, indent=2)
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
