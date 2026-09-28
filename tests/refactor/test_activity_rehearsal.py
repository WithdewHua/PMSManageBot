"""活动领域提升的生产形态本地彩排（需要显式提供副本库 URL）。

用一次性本地容器导入一份脱敏的生产库副本（先 ``alembic upgrade head``）后运行：

    ACTIVITY_REHEARSAL_DATABASE_URL=postgresql+psycopg2://user:pw@127.0.0.1:55444/db \
      .venv/bin/python -m pytest tests/refactor/test_activity_rehearsal.py
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
    """取出彩排脚本输出的最后一份 JSON 报告。"""
    start = stdout.rfind("\n{")
    payload = stdout[start + 1 :] if start >= 0 else stdout[stdout.find("{") :]
    report, _ = json.JSONDecoder().raw_decode(payload)
    assert isinstance(report, dict)
    return report


@pytest.mark.skipif(
    not os.environ.get("ACTIVITY_REHEARSAL_DATABASE_URL"),
    reason="set ACTIVITY_REHEARSAL_DATABASE_URL to run the production-shaped rehearsal",
)
def test_activity_rehearsal_against_production_copy() -> None:
    url = os.environ["ACTIVITY_REHEARSAL_DATABASE_URL"]
    # 子进程必须拿到干净环境：父进程导入 settings 后会把 data/.env 中的逗号
    # 分隔列表写回 os.environ，子进程再次实例化 Settings 会 JSON 解析失败。
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
            "scripts.refactor.rehearse_activity",
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
    assert report["ok"] is True, report["failures"]
    assert report["failures"] == []
    assert set(report["flows"]) == {"luckywheel", "treasure", "prediction", "auction"}

    failed = {
        name: check["detail"]
        for name, check in report["checks"].items()
        if not check["ok"]
    }
    assert failed == {}, failed

    luckywheel = report["flows"]["luckywheel"]
    assert luckywheel["ten_count"] == 10
    assert luckywheel["sources"] == ["paid", "gift_pack_free", *(["paid"] * 10)]

    treasure = report["flows"]["treasure"]
    assert treasure["winner_tg_id"] == report["marker_users"]["treasure_winner"]
    assert treasure["reopen_job_id"].startswith("treasure_auto_reopen_")

    prediction = report["flows"]["prediction"]
    assert prediction["result"]["total_real_pool"] == 200
    assert prediction["result"]["payout_pool"] == 190
    assert prediction["glory_after"] == prediction["glory_before"] + 4

    auction = report["flows"]["auction"]
    assert auction["job_present_before_finish"] is True
    assert auction["credits_after"] == auction["credits_before"] - 25
