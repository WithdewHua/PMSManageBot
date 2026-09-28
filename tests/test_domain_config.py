"""Core DomainConfig storage and cache contracts."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from app.core import kv
from app.core.db import get_session
from app.core.domain_config import DomainConfig, FieldRows, JsonDocument


class DemoConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    limit: StrictInt = Field(10, ge=0)
    label: str = "default"


def test_json_document_get_seeds_missing_row_and_update_invalidates_cache(
    session_env,
) -> None:
    config = DomainConfig(
        "demo",
        DemoConfig,
        JsonDocument("config.demo", "document"),
    )

    first = config.get()
    assert first == DemoConfig()
    with get_session() as session:
        assert kv.get_tx(session, "config.demo", "document") is not None

    updated = config.update(limit=7, enabled=True)
    assert updated.limit == 7
    assert updated.enabled is True
    assert config.get().limit == 7


def test_field_rows_update_only_changes_one_row(session_env) -> None:
    config = DomainConfig(
        "demo-fields",
        DemoConfig,
        FieldRows("config.demo_fields"),
    )

    assert config.get() == DemoConfig()
    config.update(limit=23)

    with get_session() as session:
        assert kv.get_tx(session, "config.demo_fields", "limit") == "23"
        assert kv.get_tx(session, "config.demo_fields", "enabled") == "false"
    assert config.get().limit == 23
    assert config.get().label == "default"


def test_invalid_numeric_bool_is_rejected(session_env) -> None:
    config = DomainConfig(
        "demo-invalid",
        DemoConfig,
        FieldRows("config.demo_invalid"),
    )
    with pytest.raises(ValidationError):
        config.update(limit=True)


def test_corrupt_json_uses_default_without_rewriting_original(session_env) -> None:
    with get_session() as session:
        kv.upsert_tx(session, "config.corrupt", "document", "not-json")

    config = DomainConfig(
        "corrupt",
        DemoConfig,
        JsonDocument("config.corrupt", "document"),
    )
    assert config.get() == DemoConfig()
    with get_session() as session:
        assert kv.get_tx(session, "config.corrupt", "document") == "not-json"


def test_cache_ttl_allows_external_change_after_expiry(session_env) -> None:
    config = DomainConfig(
        "ttl",
        DemoConfig,
        JsonDocument("config.ttl", "document"),
        ttl_seconds=0,
    )
    assert config.get().label == "default"
    with get_session() as session:
        kv.upsert_tx(
            session,
            "config.ttl",
            "document",
            json.dumps({"enabled": False, "limit": 10, "label": "external"}),
        )
    assert config.get().label == "external"


def test_read_errors_propagate_instead_of_seeding_defaults(
    session_env, monkeypatch
) -> None:
    config = DomainConfig(
        "broken",
        DemoConfig,
        JsonDocument("config.broken", "document"),
    )

    def broken_read(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(config.storage, "ensure_tx", broken_read)
    with pytest.raises(RuntimeError, match="database unavailable"):
        config.get()
    with get_session() as session:
        assert kv.get_tx(session, "config.broken", "document") is None


def test_seed_report_only_counts_new_field_rows(session_env) -> None:
    config = DomainConfig(
        "seed-report",
        DemoConfig,
        FieldRows("config.seed_report"),
    )
    report = config.seed()
    assert report.inserted == 3
    assert config.seed().inserted == 0
