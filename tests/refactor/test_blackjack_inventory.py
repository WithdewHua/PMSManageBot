from __future__ import annotations

import json
from pathlib import Path

from scripts.refactor.blackjack_inventory import inventory

ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "scripts/refactor/blackjack_inventory.json"
ALLOWED_ROLES = {
    "blackjack.errors",
    "blackjack.repository",
    "blackjack.service",
}


def test_blackjack_inventory_is_deterministic_and_reviewed() -> None:
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    first = inventory()
    second = inventory()

    assert first == second == expected
    assert first["total"] > 0
    assert {entry["target_role"] for entry in first["entries"]} <= ALLOWED_ROLES
    assert {entry["kind"] for entry in first["entries"]} >= {
        "facade_call",
        "model_import",
        "value_error_raise",
        "value_error_handler",
        "domain_error_raise",
        "side_effect",
    }


def test_blackjack_inventory_covers_known_facade_and_cycle_edges() -> None:
    entries = json.loads(FIXTURE.read_text(encoding="utf-8"))["entries"]
    keys = {(entry["path"], entry["symbol"]) for entry in entries}

    assert (
        "src/app/domains/blackjack/router/cash.py",
        "db.create_blackjack_hand",
    ) in keys
    assert (
        "src/app/domains/blackjack/repository/part_1.py",
        "app.domains.luckywheel.models",
    ) in keys
    assert (
        "src/app/domains/blackjack/repository/part_4.py",
        "blackjack_error('blackjack disabled')",
    ) in keys
