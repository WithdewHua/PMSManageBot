"""PostgreSQL metadata checker fixtures that do not require a live server."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.verify import check_metadata_pg
from scripts.verify.check_metadata_pg import (
    MetadataCheckError,
    _json_safe,
    check_metadata,
    validate_postgres_url,
)


def test_metadata_checker_requires_postgresql() -> None:
    with pytest.raises(MetadataCheckError, match="PostgreSQL URL"):
        validate_postgres_url("sqlite:///tmp/metadata.db")


def test_metadata_checker_rejects_non_local_hosts() -> None:
    with pytest.raises(MetadataCheckError, match="local PostgreSQL instance"):
        validate_postgres_url(
            "postgresql+psycopg2://user:pass@remote.domain.com/pms_check"
        )
    with pytest.raises(MetadataCheckError, match="local PostgreSQL instance"):
        validate_postgres_url("postgresql+psycopg2://user:pass@192.168.1.50/test_db")


def test_metadata_checker_accepts_local_hosts() -> None:
    validate_postgres_url("postgresql+psycopg2://user:pass@localhost/pms_check")
    validate_postgres_url("postgresql+psycopg2://user:pass@127.0.0.1/test_db")
    validate_postgres_url("postgresql+psycopg2://user:pass@[::1]/disposable_db")


def test_metadata_checker_rejects_non_disposable_database_names() -> None:
    for db in ("pmsmanagebot", "production", "postgres", "live_db", ""):
        url = f"postgresql+psycopg2://user:pass@localhost/{db}"
        with pytest.raises(MetadataCheckError, match="disposable database name"):
            validate_postgres_url(url)


def test_metadata_checker_accepts_disposable_database_names() -> None:
    for db in (
        "pms_check",
        "pms_test",
        "check_metadata",
        "test_metadata",
        "disposable_db",
        "temp_metadata",
        "tmp_check",
    ):
        validate_postgres_url(f"postgresql+psycopg2://user:pass@localhost/{db}")


def test_metadata_differences_are_json_safe() -> None:
    value = {"add_table": ("example", {"column": object()})}
    safe = _json_safe(value)
    assert safe["add_table"][0] == "example"
    assert safe["add_table"][1]["column"].startswith("<object object")


def test_check_metadata_cleans_up_when_create_baseline_fails(monkeypatch) -> None:
    cleanup_called = False

    def fake_subprocess_run(cmd, *args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        return res

    def fake_create_baseline(tool_root, base_root, url):
        raise MetadataCheckError("simulated baseline creation failure")

    def fake_cleanup_baseline(tool_root, base_root, url):
        nonlocal cleanup_called
        cleanup_called = True

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(check_metadata_pg, "_create_baseline", fake_create_baseline)
    monkeypatch.setattr(check_metadata_pg, "_cleanup_baseline", fake_cleanup_baseline)

    with pytest.raises(MetadataCheckError, match="simulated baseline creation failure"):
        check_metadata(
            "HEAD", "postgresql+psycopg2://user:pass@localhost/pms_check", Path.cwd()
        )

    assert cleanup_called is True
