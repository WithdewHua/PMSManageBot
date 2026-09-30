"""生产形态本地彩排测试：move-privileged-codes-to-database。

在隔离的 PostgreSQL 容器上对生产形态副本数据执行彩排：
    PRIVILEGED_CODES_REHEARSAL_DATABASE_URL=postgresql+psycopg2://postgres:testpass@127.0.0.1:55499/pms_test \
        .venv/bin/python -m pytest tests/refactor/test_privileged_codes_rehearsal.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def _report_from_stdout(stdout: str) -> dict:
    start = stdout.rfind("\n{")
    payload = stdout[start + 1 :] if start >= 0 else stdout[stdout.find("{") :]
    report, _ = json.JSONDecoder().raw_decode(payload)
    assert isinstance(report, dict)
    return report


@pytest.mark.skipif(
    not os.environ.get("PRIVILEGED_CODES_REHEARSAL_DATABASE_URL"),
    reason="set PRIVILEGED_CODES_REHEARSAL_DATABASE_URL to run the rehearsal test",
)
def test_privileged_codes_rehearsal_against_production_shape() -> None:
    url = os.environ["PRIVILEGED_CODES_REHEARSAL_DATABASE_URL"]
    env = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "LANG", "LC_ALL", "TZ")
        if key in os.environ
    }
    env["PYTHONPATH"] = str(ROOT / "src")
    env["DATABASE_URL"] = url
    env["DATABASE_TYPE"] = "postgresql"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.refactor.rehearse_privileged_codes",
            "--url",
            url,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = _report_from_stdout(completed.stdout)
    assert report["ok"] is True
    assert len(report["import_summary"]["marked"]) == 4
    assert len(report["import_summary"]["used_skipped"]) == 2
    assert report["import_summary"]["not_found_skipped"] == []
    assert report["registration_verification"]["registered"] is True
    assert report["registration_verification"]["retained_privileged"] is True
    assert report["env_untouched"] is True
