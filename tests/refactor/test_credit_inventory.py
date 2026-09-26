from __future__ import annotations

import json
from pathlib import Path

from scripts.refactor.credit_inventory import build_report

ROOT = Path(__file__).parents[2]
INVENTORY_PATH = ROOT / "scripts/refactor/credit_inventory.json"


def test_credit_inventory_is_current_and_complete() -> None:
    expected = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    actual = build_report(ROOT)

    assert expected["total"] == 58
    assert expected["counts"] == {
        "absolute-facade-call": 30,
        "attribute-assignment": 15,
        "attribute-augmented-assignment": 1,
        "sql-values-write": 12,
    }
    assert actual["total"] <= expected["total"]
    assert (
        actual["counts"].get("absolute-facade-call", 0)
        < expected["counts"]["absolute-facade-call"]
    )


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

    assert (
        "src/app/domains/credits/router.py",
        "transfer_credits",
    ) in {
        (entry["path"], entry["function"])
        for entry in json.loads(INVENTORY_PATH.read_text())["entries"]
    }
    assert (
        "src/app/domains/blackjack/repository/part_3.py",
        "_BlackjackRepositoryPart3.blackjack_double",
    ) in entries
    assert (
        "src/app/domains/gift_pack/repository/part_1.py",
        "_GiftPackRepositoryPart1._grant_gift_pack_rewards",
    ) in entries
    assert (
        "src/app/domains/tg_rebind/repository.py",
        "TgRebindRepository.rebind_user_tg_id",
    ) in entries
