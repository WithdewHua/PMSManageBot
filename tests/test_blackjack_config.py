from __future__ import annotations

import json

from app.core import kv
from app.core.db import get_session
from app.domains.blackjack import repository as blackjack_repository
from app.domains.blackjack.config import BLACKJACK_CONFIG, DEFAULT_BLACKJACK_CONFIG


def test_saved_blackjack_document_preserves_legacy_dictionary_values(
    session_env,
) -> None:
    saved = {
        **DEFAULT_BLACKJACK_CONFIG,
        "enabled": True,
        "bet_options": [7, 21],
        "tournament_defaults": {"buy_in_credits": 99, "payout_structure": [60, 40]},
        "legacy_extra": "preserved",
    }
    with get_session() as session:
        kv.upsert_tx(session, "blackjack", "config", json.dumps(saved))

    BLACKJACK_CONFIG.invalidate()
    assert blackjack_repository.get_blackjack_config_dict() == saved


def test_corrupt_blackjack_document_falls_back_without_overwriting(session_env) -> None:
    with get_session() as session:
        kv.upsert_tx(session, "blackjack", "config", "not-json")

    BLACKJACK_CONFIG.invalidate()
    assert blackjack_repository.get_blackjack_config_dict() == DEFAULT_BLACKJACK_CONFIG
    with get_session() as session:
        assert kv.get_tx(session, "blackjack", "config") == "not-json"
