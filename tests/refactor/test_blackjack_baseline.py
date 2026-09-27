from __future__ import annotations

import json
from pathlib import Path

from scripts.refactor.blackjack_snapshot import build_blackjack_snapshot
from scripts.refactor.snapshot import _dump

FIXTURE = Path(__file__).parent / "fixtures/blackjack_surface.json"


def test_blackjack_behavior_surface_matches_frozen_fixture() -> None:
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    first = build_blackjack_snapshot()
    second = build_blackjack_snapshot()

    assert _dump(first) == _dump(second)
    assert first == expected
    assert first["routes"]
    assert first["scheduler_jobs"]
    assert first["facade_blackjack_methods"] == []
    assert first["metadata_tables"]


def test_blackjack_baseline_covers_persisted_job_ids() -> None:
    snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
    job_ids = {
        job["kwargs"].get("id")
        for job in snapshot["scheduler_jobs"]
        if job["kwargs"].get("id")
    }
    assert {
        "sweep_expired_blackjack_hands_fallback",
        "notify_blackjack_jackpot_wins",
        "blackjack_tournament_tick",
        "blackjack_tournament_auto_create",
    } <= job_ids
