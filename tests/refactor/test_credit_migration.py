from __future__ import annotations

import json
from pathlib import Path

from scripts.refactor.check_credit_migration import check, check_report, load_mapping

ROOT = Path(__file__).parents[2]
MAPPING = ROOT / "scripts/refactor/credit_migration.toml"


def test_credit_mapping_covers_the_frozen_inventory() -> None:
    errors = check(ROOT, MAPPING)
    assert errors == []
    frozen = json.loads((ROOT / "scripts/refactor/credit_inventory.json").read_text())
    assert len(load_mapping(MAPPING)) == frozen["total"]


def test_strict_mode_rejects_unmigrated_writers() -> None:
    errors = check(ROOT, MAPPING, strict=True)
    assert errors
    assert any("unmigrated credit mutation" in error for error in errors)


def test_strict_mode_requires_a_replacement_for_each_legacy_writer() -> None:
    report = {
        "entries": [
            {
                "path": "src/app/example.py",
                "line": 1,
                "column": 0,
                "kind": "absolute-facade-call",
                "target": "DatabaseORM.update_user_credits",
            }
        ]
    }
    mapping = [
        {
            "id": "src/app/example.py|1|0|absolute-facade-call|DatabaseORM.update_user_credits",
            "replacement": "",
            "transaction_owner": "repository",
            "cache_keys": ["derived-from-account-reference"],
            "status": "migrated",
        }
    ]

    errors = check_report(report, mapping, strict=True)
    assert errors == [
        "missing replacement for: src/app/example.py|1|0|absolute-facade-call|DatabaseORM.update_user_credits"
    ]


def test_mapping_file_is_reviewable_toml() -> None:
    raw = MAPPING.read_text(encoding="utf-8")
    assert 'status = "pending-review"' in raw
    assert (
        json.loads((ROOT / "scripts/refactor/credit_inventory.json").read_text())[
            "total"
        ]
        > 0
    )
