from __future__ import annotations

import json
from pathlib import Path

from scripts.refactor.credit_inventory import build_report

ROOT = Path(__file__).parents[2]
INVENTORY_PATH = ROOT / "scripts/refactor/credit_inventory.json"


def test_credit_inventory_is_current_and_complete() -> None:
    expected = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    actual = build_report(ROOT)

    assert expected["total"] == 0
    assert expected["counts"] == {}
    assert actual["total"] == expected["total"]
    assert actual["counts"] == expected["counts"]


def test_credit_inventory_entries_have_review_context() -> None:
    report = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))

    assert report["source_root"] == "src/app"
    assert report["schema_version"] == 1
    for entry in report["entries"]:
        assert entry["path"].startswith("src/app/")
        assert entry["line"] > 0
        assert entry["function"]
        assert entry["transaction_owner"]
        assert entry["expression_kind"]
        assert entry["cache_keys"]
        assert entry["review_status"] == "pending-migration"


def test_high_risk_credit_writers_are_explicitly_inventoried() -> None:
    report = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    entries = {(entry["path"], entry["function"]) for entry in report["entries"]}

    assert not entries
