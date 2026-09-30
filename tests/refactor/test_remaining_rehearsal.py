"""Tests for read-model rehearsal comparison harness (Task 5.1).

Validates comparison mechanics, Decimal serialization parity, isolation guards,
and executes full read-model rehearsal when REMAINING_REHEARSAL_DATABASE_URL is configured.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.encoders import jsonable_encoder

from scripts.refactor.remaining_rehearsal import (
    compare_results,
    install_socket_guard,
    validate_rehearsal_database_url,
)

ROOT = Path(__file__).parents[2]


def test_compare_results_identical_dict(tmp_path: Path) -> None:
    data = {"key1": "value1", "key2": [1, 2, 3], "nested": {"a": True}}
    base_file = tmp_path / "base.json"
    curr_file = tmp_path / "curr.json"
    base_file.write_text(json.dumps(data))
    curr_file.write_text(json.dumps(data))

    report = compare_results(str(base_file), str(curr_file))
    assert report["total"] == 3
    assert report["match_count"] == 3
    assert report["diff_count"] == 0
    assert report["diffs"] == {}


def test_compare_results_detects_differences(tmp_path: Path) -> None:
    base_data = {
        "match": [1, 2],
        "diff_val": {"count": 10},
        "diff_type": {"val": "100"},
    }
    curr_data = {
        "match": [1, 2],
        "diff_val": {"count": 20},
        "diff_type": {"val": 100},
    }
    base_file = tmp_path / "base.json"
    curr_file = tmp_path / "curr.json"
    base_file.write_text(json.dumps(base_data))
    curr_file.write_text(json.dumps(curr_data))

    report = compare_results(str(base_file), str(curr_file))
    assert report["total"] == 3
    assert report["match_count"] == 1
    assert report["diff_count"] == 2
    assert "diff_val" in report["diffs"]
    assert "diff_type" in report["diffs"]


def test_decimal_serialization_parity() -> None:
    """Validate that jsonable_encoder normalizes Decimal to int/float rather than string."""
    data = {
        "traffic_bytes": Decimal(493182695184),
        "credits": Decimal("123.45"),
    }
    # Raw json.dump(default=str) would turn Decimals into strings
    raw_serialized = json.loads(json.dumps(data, default=str))
    assert isinstance(raw_serialized["traffic_bytes"], str)

    # FastAPI jsonable_encoder matches real HTTP response types
    encoded = jsonable_encoder(data)
    assert isinstance(encoded["traffic_bytes"], int)
    assert encoded["traffic_bytes"] == 493182695184
    assert isinstance(encoded["credits"], float)
    assert encoded["credits"] == 123.45


def test_socket_guard_blocks_outbound() -> None:
    """Validate that the actual worker socket guard blocks unauthorized destinations."""
    allowed_port = 32768
    orig_connect = install_socket_guard(allowed_port)
    try:
        s = socket.socket()
        with pytest.raises(RuntimeError, match="OUTBOUND NETWORK BLOCKED"):
            s.connect(("127.0.0.1", 80))
        s.close()
    finally:
        socket.socket.connect = orig_connect


def test_validate_rehearsal_database_url_safety() -> None:
    """Validate safety rules on database URL and read-only enforcement."""
    from sqlalchemy.engine import make_url

    valid_url = "postgresql+psycopg2://postgres:pw@127.0.0.1:32768/pms_test_remaining_compare_db"
    safe = validate_rehearsal_database_url(valid_url, allowed_port=32768)
    assert "default_transaction_read_only=on" in make_url(safe).query.get("options", "")
    # Disallow remote hosts
    with pytest.raises(ValueError, match="Safety violation: rehearsal database host"):
        validate_rehearsal_database_url(
            "postgresql+psycopg2://postgres:pw@192.168.1.50:32768/pms_test_remaining_compare_db"
        )

    # Disallow wrong ports
    with pytest.raises(ValueError, match="Safety violation: rehearsal database port"):
        validate_rehearsal_database_url(
            "postgresql+psycopg2://postgres:pw@127.0.0.1:5432/pms_test_remaining_compare_db",
            allowed_port=32768,
        )

    # Disallow non-rehearsal database names
    with pytest.raises(ValueError, match="Safety violation: rehearsal database name"):
        validate_rehearsal_database_url(
            "postgresql+psycopg2://postgres:pw@127.0.0.1:32768/pms_production_db"
        )


@pytest.mark.skipif(
    not os.environ.get("REMAINING_REHEARSAL_DATABASE_URL"),
    reason="set REMAINING_REHEARSAL_DATABASE_URL to run full read-model rehearsal against production copy",
)
def test_remaining_rehearsal_against_production_copy(tmp_path: Path) -> None:
    url = os.environ["REMAINING_REHEARSAL_DATABASE_URL"]
    baseline_dir = os.environ.get(
        "REMAINING_REHEARSAL_BASELINE_DIR", "/tmp/pms-remaining-baseline-761b0a5"
    )
    if not Path(baseline_dir).exists():
        pytest.skip(f"Baseline directory not found: {baseline_dir}")

    report_out = tmp_path / "rehearsal_report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/refactor/remaining_rehearsal.py"),
            "--baseline-dir",
            baseline_dir,
            "--current-dir",
            str(ROOT),
            "--pg-url",
            url,
            "--work-dir",
            str(tmp_path),
            "--json-out",
            str(report_out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    assert report_out.exists()
    report = json.loads(report_out.read_text())
    assert report["total"] >= 40
    assert report["diff_count"] == 0, f"Found differences: {report['diffs']}"


@pytest.mark.parametrize(
    "query",
    ["host=192.0.2.1", "dbname=production", "service=production", "hostaddr=192.0.2.1"],
)
def test_connection_overrides_cannot_bypass_rehearsal_guard(query):
    url = "postgresql+psycopg2://postgres:pw@127.0.0.1:32768/pms_test_remaining_compare_db"
    with pytest.raises(ValueError, match="connection overrides"):
        validate_rehearsal_database_url(f"{url}?{query}")


def test_readonly_options_cannot_be_overridden():
    from sqlalchemy.engine import make_url

    url = make_url(
        "postgresql+psycopg2://postgres:pw@127.0.0.1:32768/pms_test_remaining_compare_db"
    )
    url = url.set(
        query={
            "options": "-c default_transaction_read_only=on -c default_transaction_read_only=off"
        }
    )
    result = make_url(
        validate_rehearsal_database_url(url.render_as_string(hide_password=False))
    )
    assert result.query["options"] == "-c default_transaction_read_only=on"
