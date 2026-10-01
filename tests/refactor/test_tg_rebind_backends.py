"""The reassignment fixture can build both SQLite FK modes and optional PostgreSQL."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

import app.core.db as db_mod
import app.domains.credits.repository as credits_repo
import app.domains.identity.repository as identity_repo
from tests.refactor.tg_rebind_backends import rebind_backend, validate_pg_test_url


@pytest.mark.parametrize("backend_name", ["sqlite-off", "sqlite-on"])
def test_rebind_fixture_builds_sqlite_backends(backend_name: str) -> None:
    with rebind_backend(backend_name) as backend, backend.sessions() as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1


@pytest.mark.skipif(
    not os.environ.get("TG_REBIND_POSTGRES_URL"),
    reason="set TG_REBIND_POSTGRES_URL to exercise one-shot PostgreSQL fixture",
)
def test_rebind_fixture_builds_postgres() -> None:
    with rebind_backend("postgres") as backend, backend.sessions() as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1


def test_postgres_safety_validation() -> None:
    # Valid local URL
    validate_pg_test_url("postgresql://postgres:secret@localhost:5432/pms_test_rebind")
    validate_pg_test_url("postgresql://postgres:secret@127.0.0.1:5432/pms_test_rebind")

    # Non-local host rejected
    with pytest.raises(ValueError, match="host must be localhost"):
        validate_pg_test_url(
            "postgresql://postgres:secret@remote.db.com:5432/pms_test_rebind"
        )

    # Missing pms_test_ prefix rejected
    with pytest.raises(ValueError, match="database must start with 'pms_test_'"):
        validate_pg_test_url(
            "postgresql://postgres:secret@localhost:5432/production_pms"
        )

    # Invalid port rejected
    with pytest.raises(ValueError):
        validate_pg_test_url(
            "postgresql://postgres:secret@localhost:invalid_port/pms_test_db"
        )


def test_backend_patches_db_session_and_fake_caches() -> None:
    orig_engine = db_mod.engine
    orig_session_local = db_mod.SessionLocal

    with rebind_backend("sqlite-off") as backend:
        assert db_mod.engine is backend.engine
        assert db_mod.SessionLocal is backend.sessions

        # Verify fake cache callbacks are active
        identity_repo.write_user_info_cache()
        assert backend.cache_tracker.user_info_refreshed == 1

        credits_repo.invalidate_user_credits(["tg:101"])
        assert backend.cache_tracker.credits_invalidated == ["tg:101"]

    # Globals restored on exit
    assert db_mod.engine is orig_engine
    assert db_mod.SessionLocal is orig_session_local
