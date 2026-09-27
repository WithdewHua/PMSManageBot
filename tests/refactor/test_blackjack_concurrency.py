"""黑杰克结算/锦标赛的 PostgreSQL 并发冒烟（需要显式提供测试库 URL）。

用 `BLACKJACK_TEST_DATABASE_URL` 指向一次性容器：

    BLACKJACK_TEST_DATABASE_URL=postgresql+psycopg2://user:pw@127.0.0.1:55440/db \
      .venv/bin/python -m pytest tests/refactor/test_blackjack_concurrency.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.mark.skipif(
    not os.environ.get("BLACKJACK_TEST_DATABASE_URL"),
    reason="set BLACKJACK_TEST_DATABASE_URL to run PostgreSQL concurrency checks",
)
def test_blackjack_concurrency_against_postgresql() -> None:
    url = os.environ["BLACKJACK_TEST_DATABASE_URL"]
    # 子进程必须拿到干净的环境：父进程（pytest）导入 settings 时会把 data/.env 的
    # 内容写回 os.environ，其中列表字段是逗号分隔的，pydantic-settings 会当 JSON 解码
    # 而报错。只透传运行必需的基础变量。
    env = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "LANG", "LC_ALL", "TZ")
        if key in os.environ
    }
    env["PYTHONPATH"] = str(ROOT / "src")
    env["DATABASE_URL"] = url
    env["DATABASE_TYPE"] = "postgresql"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.refactor.smoke_blackjack_concurrency",
            "--url",
            url,
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
