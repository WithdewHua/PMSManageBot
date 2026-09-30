from __future__ import annotations

import os
import subprocess
import sys

import pytest

DATABASE_URL = os.getenv("LINE_CATALOG_TEST_DATABASE_URL") or os.getenv(
    "BUSINESS_CONFIG_TEST_DATABASE_URL"
)


@pytest.mark.skipif(
    not DATABASE_URL,
    reason="LINE_CATALOG_TEST_DATABASE_URL is required for PostgreSQL concurrency smoke",
)
def test_line_catalog_concurrent_add_serialized() -> None:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": "src",
        "DATABASE_URL": DATABASE_URL or "",
        "DATABASE_TYPE": "postgresql",
        "TZ": os.environ.get("TZ", "UTC"),
    }
    result = subprocess.run(
        [
            sys.executable,
            "scripts/refactor/smoke_line_catalog_concurrency.py",
            "--url",
            DATABASE_URL or "",
        ],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
