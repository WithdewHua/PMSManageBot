from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.mark.skipif(
    not os.environ.get("KV_TEST_DATABASE_URL"),
    reason="set KV_TEST_DATABASE_URL to run PostgreSQL concurrency checks",
)
def test_kv_compare_and_update_concurrency_against_postgresql() -> None:
    url = os.environ["KV_TEST_DATABASE_URL"]
    # 过滤环境：父进程已把 data/.env 的值写进 os.environ，子进程再实例化
    # Settings 会因逗号分隔的列表字段解析失败（见 AGENTS.md 已知约束）。
    env = {
        "PATH": os.environ.get("PATH", ""),
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
            "scripts.refactor.smoke_kv_concurrency",
            "--url",
            url,
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
