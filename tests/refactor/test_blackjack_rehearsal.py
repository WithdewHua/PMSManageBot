"""黑杰克提升的“生产形态”演练（需要显式提供副本库 URL）。

用一次性本地容器导入一份脱敏的生产库副本后运行：

    BLACKJACK_REHEARSAL_DATABASE_URL=postgresql+psycopg2://user:pw@127.0.0.1:55442/db \
      .venv/bin/python -m pytest tests/refactor/test_blackjack_rehearsal.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.mark.skipif(
    not os.environ.get("BLACKJACK_REHEARSAL_DATABASE_URL"),
    reason="set BLACKJACK_REHEARSAL_DATABASE_URL to run the production-shaped rehearsal",
)
def test_blackjack_rehearsal_against_production_copy() -> None:
    url = os.environ["BLACKJACK_REHEARSAL_DATABASE_URL"]
    # 子进程必须拿到干净环境：父进程导入 settings 时会把 data/.env 的逗号分隔列表
    # 写回 os.environ，子进程再次实例化 Settings 会 JSON 解析失败。
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
            "scripts.refactor.rehearse_blackjack",
            "--url",
            url,
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
