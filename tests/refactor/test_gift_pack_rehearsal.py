"""礼包提升的“生产形态”彩排（需要显式提供副本库 URL）。

用一次性本地容器导入一份脱敏的生产库副本（先 ``alembic upgrade head``）后运行：

    GIFT_PACK_REHEARSAL_DATABASE_URL=postgresql+psycopg2://user:pw@127.0.0.1:55443/db \
      .venv/bin/python -m pytest tests/refactor/test_gift_pack_rehearsal.py
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
    """取出脚本输出的最后一份 JSON 报告（日志走 stderr，stdout 只有报告）。"""
    start = stdout.rfind("\n{")
    payload = stdout[start + 1 :] if start >= 0 else stdout[stdout.find("{") :]
    report, _ = json.JSONDecoder().raw_decode(payload)
    assert isinstance(report, dict)
    return report


@pytest.mark.skipif(
    not os.environ.get("GIFT_PACK_REHEARSAL_DATABASE_URL"),
    reason="set GIFT_PACK_REHEARSAL_DATABASE_URL to run the production-shaped rehearsal",
)
def test_gift_pack_rehearsal_against_production_copy() -> None:
    url = os.environ["GIFT_PACK_REHEARSAL_DATABASE_URL"]
    # 子进程必须拿到干净环境：父进程导入 settings 时会把 data/.env 的内容写回
    # os.environ，其中列表字段是逗号分隔的，pydantic-settings 会当 JSON 解码而报错。
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
            "scripts.refactor.rehearse_gift_pack",
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
    assert report["logged_errors"] == []
    assert report["checks"]["no_error_logs"]["ok"] is True

    round_report = report["rounds"][0]
    failed = {
        name: check["detail"]
        for name, check in round_report["checks"].items()
        if not check["ok"]
    }
    assert failed == {}, failed

    # 关键不变量：全部奖励类型都发放、快照落库一致、限量礼包领完。
    reward_types = {item["type"] for item in round_report["reward_snapshot_service"]}
    assert reward_types == {
        "credits",
        "premium_days",
        "wheel_free_spins",
        "tournament_wallet",
        "invite_codes",
        "line_schedule_unlock",
        "download_unlock",
    }
    assert (
        round_report["reward_snapshot_persisted"]
        == round_report["reward_snapshot_service"]
    )
    assert round_report["claimed_count"] == 1
    assert round_report["sold_out"] is True

    # 落库的邀请码行与媒体解锁列。
    snapshot_codes = sorted(
        code
        for item in round_report["reward_snapshot_service"]
        if item["type"] == "invite_codes"
        for code in item["codes"]
    )
    assert round_report["invite_codes_in_db"] == snapshot_codes
    for service, key in (("plex", "sync_unlocked"), ("emby", "download_unlocked")):
        assert round_report["media_flags"][service][key] == 1
        assert round_report["media_flags"][service]["line_schedule_unlocked"] == 1

    # 提交后的副作用参数：两条下载同步、两条 Premium 权限同步（plex → emby）。
    assert [
        call["service"] for call in round_report["media_sync_calls"]["download_unlock"]
    ] == ["plex", "emby"]
    assert round_report["media_sync_calls"]["premium_permission"] == [
        {"tg_id": round_report["tg_id"], "services": ["plex"]},
        {"tg_id": round_report["tg_id"], "services": ["emby"]},
    ]
    assert round_report["notifications"] == [
        {
            "function": "notify_gift_pack_sold_out",
            "args": {
                "pack_id": round_report["pack_id"],
                "title": round_report["title"],
                "total_quantity": 1,
            },
        }
    ]
