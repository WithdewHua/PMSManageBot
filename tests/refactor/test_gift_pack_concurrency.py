"""礼包领取的 PostgreSQL 并发冒烟（需要显式提供测试库 URL）。

用 `GIFT_PACK_TEST_DATABASE_URL` 指向一次性容器：

    GIFT_PACK_TEST_DATABASE_URL=postgresql+psycopg2://user:pw@127.0.0.1:55441/db \
      .venv/bin/python -m pytest tests/refactor/test_gift_pack_concurrency.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.mark.skipif(
    not os.environ.get("GIFT_PACK_TEST_DATABASE_URL"),
    reason="set GIFT_PACK_TEST_DATABASE_URL to run PostgreSQL concurrency checks",
)
def test_gift_pack_concurrency_against_postgresql() -> None:
    url = os.environ["GIFT_PACK_TEST_DATABASE_URL"]
    # 子进程必须拿到干净的环境：父进程导入 settings 时会把 data/.env 的内容写回
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
            "scripts.refactor.smoke_gift_pack_concurrency",
            "--url",
            url,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    assert lines, f"没有输出结果\n{completed.stdout}\n{completed.stderr}"
    payload = json.loads(lines[-1])

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert payload["ok"] is True
    assert payload["s1"]["winners"] == 1
    assert payload["s2"]["successes"] == 1
    # 固定加锁顺序后，礼包领取与线路解锁交叉进行不再死锁
    assert payload["s3"]["deadlock"] is False
