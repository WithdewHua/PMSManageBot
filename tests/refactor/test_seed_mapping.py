"""Regression coverage for deterministic first-pass placement rules."""

from __future__ import annotations

from pathlib import Path

from scripts.refactor.inventory import inventory
from scripts.refactor.seed_mapping import (
    _route_domain,
    _route_paths,
    _sections,
    merge_mapping,
    seed,
    write_mapping,
)


def test_unknown_database_section_terminates_previous_inference(tmp_path: Path) -> None:
    source = tmp_path / "db.py"
    source.write_text(
        """    # ========== Wheel Operations ==========
    def wheel(self):
        pass
    # ========================================
    # unrelated new subsystem
    # ========================================
    def unrelated(self):
        pass
""",
        encoding="utf-8",
    )
    numbers, labels = _sections(source)
    assert numbers == [1, 4]
    assert labels == ["Wheel Operations", "unrelated new subsystem"]


def test_router_path_overrides_ambiguous_function_name(tmp_path: Path) -> None:
    source = tmp_path / "admin.py"
    source.write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n"
        "@router.post('/donation')\nasync def submit_record():\n    pass\n",
        encoding="utf-8",
    )
    assert _route_paths(source)["submit_record"] == "/donation"
    assert _route_domain("/donation") == "donation"
    assert _route_domain("/unknown") is None


def test_mapping_draft_does_not_confuse_blackjack_with_lines(tmp_path: Path) -> None:
    source = tmp_path / "src/app/databases/db.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "class DatabaseORM:\n"
        "    # ===== Blackjack (21 点) Operations =====\n"
        "    def get_blackjack_config_dict(self):\n"
        "        pass\n"
        "    # ===== Line Management Operations =====\n"
        "    def check_line_schedule_unlock(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    records = seed(inventory([source], root=tmp_path), root=tmp_path)
    lookup = {record["id"]: record for record in records}
    assert lookup["app.databases.db:DatabaseORM.get_blackjack_config_dict"][
        "target"
    ] == ("app.domains.blackjack.repository")
    assert (
        lookup["app.databases.db:DatabaseORM.check_line_schedule_unlock"]["target"]
        == "app.domains.lines.repository"
    )
    output = tmp_path / "mapping.toml"
    write_mapping(records, output)
    first_run = output.read_bytes()
    write_mapping(records, output)
    assert output.read_bytes() == first_run


def test_merge_preserves_reviewed_target_and_rejects_disappeared_ids(
    tmp_path: Path,
) -> None:
    import pytest

    existing = tmp_path / "mapping.toml"
    write_mapping(
        [
            {
                "id": "app.example:one",
                "target": "app.domains.accounts.service",
                "kind": "function",
                "reason": "reviewed by maintainer",
            }
        ],
        existing,
    )
    fresh = [
        {
            "id": "app.example:one",
            "target": "TODO",
            "kind": "function",
            "reason": "guess",
        },
        {
            "id": "app.example:two",
            "target": "TODO",
            "kind": "function",
            "reason": "new",
        },
    ]
    merged = merge_mapping(fresh, existing)
    assert merged[0]["target"] == "app.domains.accounts.service"
    assert merged[0]["reason"] == "reviewed by maintainer"
    assert merged[1] == fresh[1]
    with pytest.raises(ValueError, match="stale IDs"):
        merge_mapping(fresh[1:], existing)


def test_reviewed_model_targets_do_not_leak_into_other_modules() -> None:
    import tomllib

    mapping = tomllib.loads(Path("scripts/refactor/mapping.toml").read_text())
    items = {entry["id"]: entry for entry in mapping["items"]}
    assert (
        items["app.modules.custom_line:check_expired_custom_lines"]["target"] == "TODO"
    )
    assert items["app.utils.report:send_weekly_report"]["target"] == "TODO"
    assert items["app.models:__all__"]["target"] == "TODO"
