"""礼包提升基线：表面快照与 repository 成员的审阅目标。

快照由 `scripts/refactor/gift_pack_snapshot.py` 生成：

    PYTHONPATH=src:. .venv/bin/python -m scripts.refactor.gift_pack_snapshot \
      --output tests/refactor/fixtures/gift_pack_surface.json
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from scripts.refactor.gift_pack_snapshot import build_gift_pack_snapshot
from scripts.refactor.snapshot import _dump

ROOT = Path(__file__).parents[2]
FIXTURE = Path(__file__).parent / "fixtures/gift_pack_surface.json"
MAPPING = ROOT / "scripts/refactor/mapping.toml"

SUBTOPIC_MODULES = {
    "app.domains.gift_pack.repository.conditions",
    "app.domains.gift_pack.repository.rewards",
    "app.domains.gift_pack.repository.packs",
    "app.domains.gift_pack.repository.claims",
    "app.domains.gift_pack.repository.notices",
}


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_gift_pack_behavior_surface_matches_frozen_fixture() -> None:
    expected = _fixture()
    first = build_gift_pack_snapshot()
    second = build_gift_pack_snapshot()

    assert _dump(first) == _dump(second)
    assert first == expected
    assert first["routes"]
    assert first["scheduler_jobs"]
    assert first["repository_members"]
    assert first["facade_gift_pack_methods"]
    assert first["metadata_tables"]


def test_gift_pack_baseline_covers_routes_jobs_and_tables() -> None:
    snapshot = _fixture()
    routes = snapshot["routes"]
    assert len(routes) == 11
    assert len([route for route in routes if "/admin" in route["path"]]) == 8
    assert len(snapshot["openapi_paths"]) == 10

    job_ids = {job["kwargs"]["id"] for job in snapshot["scheduler_jobs"]}
    assert job_ids == {"scan_expired_gift_packs", "scan_gift_pack_start_dms"}
    for job in snapshot["scheduler_jobs"]:
        assert job["kwargs"]["trigger"] == "interval"
        assert job["kwargs"]["next_run_time"]["relative_seconds"] > 0

    tables = {table["name"] for table in snapshot["metadata_tables"]}
    assert {"gift_pack", "gift_pack_user_state"} <= tables
    assert len(snapshot["repository_members"]) == 55


def test_every_repository_member_has_a_reviewed_destination() -> None:
    members = set(_fixture()["repository_members"])
    mapping = tomllib.loads(MAPPING.read_text(encoding="utf-8"))
    planned = {
        item["id"].split("DatabaseORM.", 1)[1]: item["planned_target"]
        for item in mapping["items"]
        if item["id"].startswith("app.databases.db:DatabaseORM.")
        and "planned_target" in item
    }

    assert sorted(name for name in members if name not in planned) == []
    assert {planned[name] for name in members} <= SUBTOPIC_MODULES
    assert len({planned[name] for name in members}) == 5
