"""Identity cache writes happen only after a successful transaction commit."""

from __future__ import annotations

import pytest

from app.core.db import get_session
from app.domains.identity import repository as identity_repository


def test_identity_cache_write_is_post_commit_only(session_env, monkeypatch) -> None:
    writes: list[str] = []
    monkeypatch.setattr(
        "app.domains.identity.repository.user_info_cache.put",
        lambda key, value: writes.append(key),
    )

    with pytest.raises(RuntimeError), get_session() as session:
        identity_repository.add_plex_user_tx(
            session, plex_id=11, plex_username="rollback-user"
        )
        raise RuntimeError("rollback")
    assert writes == []

    identity_repository.add_plex_user(plex_id=12, plex_username="commit-user")
    assert writes == ["plex:commit-user"]
