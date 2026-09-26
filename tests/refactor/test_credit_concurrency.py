from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.mark.skipif(
    not os.environ.get("CREDITS_TEST_DATABASE_URL"),
    reason="set CREDITS_TEST_DATABASE_URL to run PostgreSQL concurrency checks",
)
def test_credit_concurrency_against_postgresql() -> None:
    url = os.environ["CREDITS_TEST_DATABASE_URL"]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["DATABASE_URL"] = url
    env["DATABASE_TYPE"] = "postgresql"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.refactor.smoke_credit_concurrency",
            "--url",
            url,
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
