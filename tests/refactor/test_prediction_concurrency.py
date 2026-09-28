"""PostgreSQL concurrency smoke entry point for the prediction domain."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.mark.skipif(
    not os.environ.get("PREDICTION_TEST_DATABASE_URL"),
    reason="set PREDICTION_TEST_DATABASE_URL to run PostgreSQL concurrency checks",
)
def test_prediction_concurrency_against_postgresql() -> None:
    url = os.environ["PREDICTION_TEST_DATABASE_URL"]
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
            "scripts.refactor.smoke_prediction_concurrency",
            "--url",
            url,
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
