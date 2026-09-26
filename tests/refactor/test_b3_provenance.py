"""B3 provenance sealing must reject untraceable mechanical debt."""

from __future__ import annotations

import json
import tomllib

import pytest

from scripts.refactor.audit_b3_baseline import (
    BASELINE,
    _frozen_items,
    _mapping_items,
    _source_for,
    _validate_entry,
    audit,
)


def test_b3_sealed_entries_have_source_ids() -> None:
    result = audit()
    assert result["ok"] is True
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    entries = baseline["cross_domain_calls"]
    assert len(entries) == result["total"]
    assert len({entry["key"] for entry in entries}) == len(entries)
    new_entries = [entry for entry in entries if "b3_source_id" in entry]
    assert len(new_entries) == result["b3"]
    assert all(entry["b3_source_id"].startswith("app.") for entry in new_entries)


def test_b3_provenance_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="no unique B3 mapping source"):
        _source_for(
            {
                "key": "call|src/app/domains/unknown/service.py|1|x|unknown|missing",
                "path": "src/app/domains/unknown/service.py",
                "target_domain": "unknown",
                "target": "missing",
                "line": 1,
                "kind": "call",
            },
            [],
        )


def test_b3_provenance_rejects_target_domain_fallback() -> None:
    with pytest.raises(ValueError, match="no unique B3 mapping source"):
        _source_for(
            {
                "key": "call|src/app/domains/watch_rewards/service.py|243|imported|identity|isnot",
                "path": "src/app/domains/watch_rewards/service.py",
                "target_domain": "identity",
                "target": "isnot",
                "line": 243,
                "kind": "call",
            },
            [
                {
                    "id": "app.databases.db_func:@import:20",
                    "target": "app.domains.watch_rewards.service",
                    "kind": "import",
                }
            ],
        )


def test_b3_provenance_rejects_same_domain_wrong_source() -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    entry = next(
        item
        for item in baseline["cross_domain_calls"]
        if item.get("b3_source_id")
        and item["key"].startswith("call|src/app/domains/accounts/service.py|")
        and item.get("target") == "update_traffic_username"
    )
    invalid = {**entry, "b3_source_id": "app.databases.db_func:add_all_plex_user"}
    errors = _validate_entry(invalid, mappings=_mapping_items(), frozen=_frozen_items())
    assert errors
    assert "does not prove" in errors[0]


def test_line_role_rebindings_are_itemized() -> None:
    result = audit()
    assert result["ok"] is True
    with open("scripts/refactor/mapping.toml", "rb") as stream:
        mappings = tomllib.load(stream)["items"]
    assert any(
        item.get("b3_key")
        == "import|src/app/domains/custom_lines/jobs.py|app.domains.lines.service|unbind_specified_line_for_all_users"
        for item in mappings
    )
