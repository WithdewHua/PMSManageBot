from __future__ import annotations

from app.core import kv
from app.core.db import get_session
from scripts.export_business_config import export_lines


def test_export_business_config_is_read_only_and_uses_legacy_keys(session_env) -> None:
    with get_session() as session:
        kv.upsert_tx(session, "config.accounts", "plex_register", "true")
        kv.upsert_tx(session, "config.media_access", "nsfw_libs", '["Private","Kids"]')

    before = len(export_lines())
    lines = export_lines()

    assert "PLEX_REGISTER=true" in lines
    assert "NSFW_LIBS=Private,Kids" in lines
    assert len(export_lines()) == before
