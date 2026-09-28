from __future__ import annotations

import os
import subprocess
import sys

import pytest

DATABASE_URL = os.getenv("BUSINESS_CONFIG_REHEARSAL_DATABASE_URL")


@pytest.mark.skipif(
    not DATABASE_URL,
    reason="BUSINESS_CONFIG_REHEARSAL_DATABASE_URL is required for PostgreSQL rehearsal",
)
def test_business_config_production_rehearsal() -> None:
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
            "scripts/refactor/rehearse_business_config.py",
            "--url",
            DATABASE_URL or "",
        ],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
