"""Freeze the line-domain behavior surface before promotion."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from scripts.refactor.line_snapshot import build_line_snapshot

ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests/refactor/fixtures/line_surface.json"
MAPPING = ROOT / "scripts/refactor/mapping.toml"


def _dump(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def test_line_surface_is_repeatable_and_frozen() -> None:
    first = build_line_snapshot()
    second = build_line_snapshot()
    assert _dump(first) == _dump(second)
    assert first == json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_line_surface_contains_all_public_entry_points() -> None:
    snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
    paths = {route["path"] for route in snapshot["routes"]}
    assert "/api/user/lines/emby/available" in paths
    assert "/api/user/lines/plex/available" in paths
    assert "/api/user/custom-lines/submit" in paths
    assert "/api/premium/unlock" in paths
    assert "/api/user/download-permission/unlock/{service}" in paths
    assert snapshot["scheduler_jobs"]
    assert snapshot["redis_literals"]
    assert snapshot["redis_expressions"]
    assert snapshot["notification_literals"]


def test_lines_and_traffic_mixin_members_are_mapped() -> None:
    items = tomllib.loads(MAPPING.read_text(encoding="utf-8"))["items"]
    mapped = {
        (item.get("class"), item["id"].rsplit(".", 1)[-1])
        for item in items
        if item.get("id", "").startswith("app.databases.db:DatabaseORM.")
    }
    snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for class_name, methods in snapshot["legacy_mixin_members"].items():
        for method in methods:
            assert (class_name, method) in mapped, (class_name, method)


def test_custom_line_sql_inventory_has_reviewed_mapping_entries() -> None:
    items = tomllib.loads(MAPPING.read_text(encoding="utf-8"))["items"]
    mapped = {
        item["id"]
        for item in items
        if item.get("id", "").startswith("custom_lines.sql:")
    }
    inventory = json.loads(
        (ROOT / "tests/refactor/fixtures/custom_lines_sql.json").read_text(
            encoding="utf-8"
        )
    )
    assert inventory
    for key in inventory:
        assert key in mapped, key
