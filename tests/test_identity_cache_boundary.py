"""Verify identity compatibility layer and post-commit cache safety (Rule #267)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from app.domains.identity.compat import IdentityRepository

from app.core.db import get_session
from app.domains.identity import repository as identity_repository
from app.domains.identity.models import PlexUser

ROOT = Path(__file__).resolve().parents[1]
assert (ROOT / "src/app").is_dir()


def test_identity_compatibility_layer_has_no_sql_imports() -> None:
    tree = ast.parse(
        (ROOT / "src/app/domains/identity/compat.py").read_text(encoding="utf-8")
    )
    imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    imports.extend(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    )
    assert all(
        not name.startswith(
            ("sqlalchemy", "app.core.db", "app.domains.identity.models")
        )
        for name in imports
    )


def test_compatibility_layer_preserves_legacy_tuple_shape(session_env) -> None:
    with get_session() as session:
        session.add(PlexUser(plex_id=7, plex_email="User@Example.com"))

    result = IdentityRepository().get_plex_info_by_plex_email("user@example.com")
    assert result is not None
    assert result[0] == 7
    assert result[3] == "User@Example.com"


def test_identity_cache_write_is_post_commit_only(session_env, monkeypatch) -> None:
    """Identity mutations must register cache writes post-commit only (Rule #267)."""
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
