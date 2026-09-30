"""Tests for line_catalog database model constraints."""

from __future__ import annotations

import time

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.db import get_session
from app.domains.lines.models import LineCatalog


def test_line_catalog_valid_creation(session_env) -> None:
    now = int(time.time())
    with get_session() as session:
        normal_line = LineCatalog(
            name="line1",
            kind="normal",
            position=0,
            tags="[]",
            free_open=0,
            created_at=now,
            updated_at=now,
        )
        premium_line = LineCatalog(
            name="prem1",
            kind="premium",
            position=0,
            tags='["4K", "VIP"]',
            free_open=1,
            created_at=now,
            updated_at=now,
        )
        session.add(normal_line)
        session.add(premium_line)


def test_line_catalog_rejects_illegal_kind(session_env) -> None:
    now = int(time.time())
    with pytest.raises(IntegrityError), get_session() as session:
        session.add(
            LineCatalog(
                name="invalid_kind",
                kind="vip",
                position=0,
                tags="[]",
                free_open=0,
                created_at=now,
                updated_at=now,
            )
        )


def test_line_catalog_rejects_normal_line_free_open(session_env) -> None:
    now = int(time.time())
    with pytest.raises(IntegrityError), get_session() as session:
        session.add(
            LineCatalog(
                name="normal_free",
                kind="normal",
                position=0,
                tags="[]",
                free_open=1,
                created_at=now,
                updated_at=now,
            )
        )


def test_line_catalog_rejects_duplicate_name(session_env) -> None:
    now = int(time.time())
    with get_session() as session:
        session.add(
            LineCatalog(
                name="duplicate_name",
                kind="normal",
                position=0,
                tags="[]",
                free_open=0,
                created_at=now,
                updated_at=now,
            )
        )
    with pytest.raises(IntegrityError), get_session() as session:
        session.add(
            LineCatalog(
                name="duplicate_name",
                kind="premium",
                position=1,
                tags="[]",
                free_open=0,
                created_at=now,
                updated_at=now,
            )
        )


def test_line_catalog_rejects_duplicate_kind_position(session_env) -> None:
    now = int(time.time())
    with get_session() as session:
        session.add(
            LineCatalog(
                name="line_a",
                kind="normal",
                position=0,
                tags="[]",
                free_open=0,
                created_at=now,
                updated_at=now,
            )
        )
    with pytest.raises(IntegrityError), get_session() as session:
        session.add(
            LineCatalog(
                name="line_b",
                kind="normal",
                position=0,
                tags="[]",
                free_open=0,
                created_at=now,
                updated_at=now,
            )
        )


def test_line_catalog_rejects_negative_position(session_env) -> None:
    now = int(time.time())
    with pytest.raises(IntegrityError), get_session() as session:
        session.add(
            LineCatalog(
                name="neg_pos",
                kind="normal",
                position=-1,
                tags="[]",
                free_open=0,
                created_at=now,
                updated_at=now,
            )
        )
