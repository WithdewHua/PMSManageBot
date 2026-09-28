"""PostgreSQL concurrency smoke entry point for luckywheel."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.mark.skipif(
    not os.environ.get("LUCKYWHEEL_TEST_DATABASE_URL"),
    reason="set LUCKYWHEEL_TEST_DATABASE_URL to run PostgreSQL concurrency checks",
)
def test_luckywheel_concurrency_against_postgresql() -> None:
    url = os.environ["LUCKYWHEEL_TEST_DATABASE_URL"]
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": str(ROOT / "src"),
        "DATABASE_URL": url,
        "DATABASE_TYPE": "postgresql",
        "TZ": os.environ.get("TZ", "Asia/Shanghai"),
    }
    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.refactor.smoke_luckywheel_concurrency",
            "--url",
            url,
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
