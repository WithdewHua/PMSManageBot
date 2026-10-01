"""Disposable database backends used by Telegram ID reassignment tests."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.db as db_mod
import app.domains.credits.repository as credits_repo
import app.domains.identity.repository as identity_repo
from app.model_registry import metadata


@dataclass
class FakeCacheTracker:
    user_info_refreshed: int = 0
    credits_invalidated: list[str] = field(default_factory=list)

    def reset(self) -> None:
        self.user_info_refreshed = 0
        self.credits_invalidated.clear()


@dataclass(frozen=True, slots=True)
class RebindBackend:
    name: str
    engine: Engine
    sessions: sessionmaker[Session]
    cache_tracker: FakeCacheTracker


def validate_pg_test_url(url_str: str) -> None:
    """Ensure PostgreSQL test URL is strictly local and names an isolated test database."""
    url = make_url(url_str)
    host = url.host or ""
    if host not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError(
            f"PG SAFETY VIOLATION: host must be localhost/127.0.0.1/::1, got '{host}'"
        )
    database = url.database or ""
    if not database.startswith("pms_test_"):
        raise ValueError(
            f"PG SAFETY VIOLATION: database must start with 'pms_test_', got '{database}'"
        )
    if url.port is not None:
        try:
            int(url.port)
        except (ValueError, TypeError):
            raise ValueError(f"PG SAFETY VIOLATION: invalid port '{url.port}'")


@contextmanager
def rebind_backend(name: str) -> Iterator[RebindBackend]:
    """Provide a disposable, isolated database backend and patch session/cache globals."""
    cache_tracker = FakeCacheTracker()
    created_schema: str | None = None
    bootstrap_engine: Engine | None = None

    if name == "sqlite-off":
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    elif name == "sqlite-on":
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    elif name == "postgres":
        url_str = os.environ.get("TG_REBIND_POSTGRES_URL")
        if not url_str:
            raise RuntimeError(
                "TG_REBIND_POSTGRES_URL is required for the PostgreSQL backend"
            )
        validate_pg_test_url(url_str)

        bootstrap_engine = create_engine(url_str)
        created_schema = f"rebind_{uuid.uuid4().hex[:12]}"
        with bootstrap_engine.connect() as conn:
            conn.execute(text(f'CREATE SCHEMA "{created_schema}"'))
            conn.commit()

        engine = create_engine(
            url_str,
            connect_args={"options": f"-c search_path={created_schema}"},
        )
    else:
        raise ValueError(f"unknown rebind backend: {name}")

    # Patch core.db and fake cache callbacks
    prev_engine = db_mod.engine
    prev_session_local = db_mod.SessionLocal
    prev_write_user_info = getattr(identity_repo, "write_user_info_cache", None)
    prev_refresh_user_info = getattr(identity_repo, "refresh_user_info_for_tg", None)
    prev_invalidate_credits = getattr(credits_repo, "invalidate_user_credits", None)

    session_factory = sessionmaker(bind=engine, autoflush=False)
    db_mod.engine = engine
    db_mod.SessionLocal = session_factory

    def _fake_write_user_info() -> None:
        cache_tracker.user_info_refreshed += 1

    def _fake_invalidate_credits(keys) -> None:
        cache_tracker.credits_invalidated.extend(keys)

    identity_repo.write_user_info_cache = _fake_write_user_info
    identity_repo.refresh_user_info_for_tg = lambda tg_id: _fake_write_user_info()
    credits_repo.invalidate_user_credits = _fake_invalidate_credits

    try:
        metadata.create_all(engine)
        yield RebindBackend(name, engine, session_factory, cache_tracker)
    finally:
        if name.startswith("sqlite"):
            engine.dispose()
        elif name == "postgres":
            engine.dispose()
            if bootstrap_engine and created_schema:
                with bootstrap_engine.connect() as conn:
                    conn.execute(
                        text(f'DROP SCHEMA IF EXISTS "{created_schema}" CASCADE')
                    )
                    conn.commit()
                bootstrap_engine.dispose()

        # Restore globals
        db_mod.engine = prev_engine
        db_mod.SessionLocal = prev_session_local
        if prev_write_user_info is not None:
            identity_repo.write_user_info_cache = prev_write_user_info
        if prev_refresh_user_info is not None:
            identity_repo.refresh_user_info_for_tg = prev_refresh_user_info
        if prev_invalidate_credits is not None:
            credits_repo.invalidate_user_credits = prev_invalidate_credits
