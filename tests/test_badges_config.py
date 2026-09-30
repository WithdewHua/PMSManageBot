from __future__ import annotations

from app.core import kv
from app.core.db import get_session
from app.core.domain_config import FieldSpec
from app.domains.badges import repository
from app.domains.badges.config import BADGE_CENTER_CONFIG


def test_badge_center_config_keeps_legacy_rows_and_codecs(session_env) -> None:
    assert repository.get_badge_center_config() == (False, None)
    assert repository.set_badge_center_config(True, "temporarily closed") is True
    assert repository.get_badge_center_config() == (True, "temporarily closed")

    with get_session() as session:
        assert kv.get_tx(session, "badge_center", "enabled") == "1"
        assert kv.get_tx(session, "badge_center", "message") == "temporarily closed"


def test_badge_center_two_field_update_rolls_back_together(
    session_env, monkeypatch
) -> None:
    repository.set_badge_center_config(False, "old")
    original = BADGE_CENTER_CONFIG.storage.fields["message"]

    def fail_encode(_value: str | None) -> str:
        raise RuntimeError("message write failed")

    BADGE_CENTER_CONFIG.storage.fields["message"] = FieldSpec(
        key="message",
        encode=fail_encode,
        decode=original.decode,
    )
    try:
        assert repository.set_badge_center_config(True, "new") is False
    finally:
        BADGE_CENTER_CONFIG.storage.fields["message"] = original
        BADGE_CENTER_CONFIG.invalidate()

    assert repository.get_badge_center_config() == (False, "old")
