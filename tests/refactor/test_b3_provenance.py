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


BLACKJACK_SERVICE_REBINDINGS = {
    "call|src/app/domains/badge_awards/jobs.py|207|imported|blackjack|get_blackjack_config_dict": "app.databases.db_func:check_and_award_game_king_badge",
    "call|src/app/domains/badge_awards/jobs.py|220|imported|badges|get_badge_by_type": "app.databases.db_func:check_and_award_game_king_badge",
    "call|src/app/domains/badge_awards/jobs.py|223|imported|badges|create_badge": "app.databases.db_func:check_and_award_game_king_badge",
    "call|src/app/domains/badge_awards/jobs.py|253|imported|blackjack|get_user_blackjack_stats": "app.databases.db_func:check_and_award_game_king_badge",
    "call|src/app/domains/badge_awards/jobs.py|331|imported|blackjack|get_game_king_eligible_tg_ids_tx": "app.databases.db_func:check_and_award_game_king_badge",
    "call|src/app/domains/badge_awards/jobs.py|38|imported|badges|get_badge_by_type": "app.databases.db_func:check_and_award_supreme_contributor_badge",
    "call|src/app/domains/badge_awards/jobs.py|41|imported|badges|create_badge": "app.databases.db_func:check_and_award_supreme_contributor_badge",
    "import|src/app/domains/badge_awards/jobs.py|11|app.domains.blackjack.service|service": "app.databases.db_func:@import:19",
}

# Cross-domain edges whose legacy spelling was replaced by the reviewed blackjack
# service boundary. The edges predate promote-blackjack-domain (their B3 baseline
# entries carried no b3_source_id), so they keep their original owning change.
REVIEWED_BOUNDARY_REPLACEMENTS = {
    "call|src/app/domains/gift_pack/repository/conditions.py|129|imported|blackjack|count_eligible_cash_hands_tx": "promote-gift-pack-domain",
    "call|src/app/domains/gift_pack/repository/conditions.py|184|imported|blackjack|count_tournament_entries_tx": "promote-gift-pack-domain",
    "import|src/app/domains/gift_pack/repository/conditions.py|12|app.domains.blackjack.service|service": "promote-gift-pack-domain",
    "call|src/app/domains/rankings/repository.py|189|imported|blackjack|get_blackjack_skill_ranks": "promote-remaining-domains",
    "call|src/app/domains/rankings/repository.py|193|imported|blackjack|get_blackjack_max_win_rank": "promote-remaining-domains",
    "import|src/app/domains/rankings/repository.py|7|app.domains.blackjack.service|service": "promote-remaining-domains",
    "import|src/app/domains/badge_awards/jobs.py|9|app.domains.badges.service|service": "promote-reward-domains",
}


def test_blackjack_service_rebindings_are_itemized_and_proven() -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    entries = {entry["key"]: entry for entry in baseline["cross_domain_calls"]}

    with open("scripts/refactor/mapping.toml", "rb") as stream:
        mappings = tomllib.load(stream)["items"]

    for key, source_id in BLACKJACK_SERVICE_REBINDINGS.items():
        bindings = [
            item for item in mappings if item.get("b3_key") == _normalized_key(key)
        ]
        assert bindings, key
        assert all(item.get("b3_behavior_test") for item in bindings), key
        assert entries[key]["b3_source_id"] == source_id

    for key, owner in REVIEWED_BOUNDARY_REPLACEMENTS.items():
        assert entries[key]["owner"] == owner
        assert "b3_source_id" not in entries[key]


def _normalized_key(key: str) -> str:
    parts = key.split("|")
    return "|".join([*parts[:2], *parts[3:]])
