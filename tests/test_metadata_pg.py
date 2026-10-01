"""PostgreSQL metadata checker fixtures that do not require a live server."""

from __future__ import annotations

import pytest

from scripts.verify.check_metadata_pg import (
    MetadataCheckError,
    _json_safe,
    validate_postgres_url,
)


def test_metadata_checker_requires_postgresql() -> None:
    with pytest.raises(MetadataCheckError, match="PostgreSQL URL"):
        validate_postgres_url("sqlite:///tmp/metadata.db")


def test_metadata_checker_accepts_postgresql_drivers() -> None:
    validate_postgres_url("postgresql+psycopg2://user:pass@localhost/check")
    validate_postgres_url("postgres://user:pass@localhost/check")


def test_metadata_differences_are_json_safe() -> None:
    value = {"add_table": ("example", {"column": object()})}
    safe = _json_safe(value)
    assert safe["add_table"][0] == "example"
    assert safe["add_table"][1]["column"].startswith("<object object")
