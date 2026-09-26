"""Compare the B2 and B3 custom-line traffic lookup on disposable SQLite.

Both revisions execute against identical newly seeded databases. The trace
counts independent identity lookup sessions and checks caller-session behavior.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import get_origin

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = r"""
import asyncio
import importlib
import json
import os
from contextlib import contextmanager
from datetime import datetime

from app.core import db as core_db
from app.domains.identity import repository as identity_repository
from app.domains.identity.models import EmbyUser, PlexUser
from app.domains.traffic.models import LineTrafficMonthlyStats, LineTrafficStats
from app.model_registry import metadata

metadata.create_all(core_db.engine)
with core_db.get_session() as session:
    session.add_all([
        PlexUser(id=1, plex_id=100, tg_id=7, plex_username="PlexOwner"),
        EmbyUser(emby_username="EmbyOwner", emby_id="e-7", tg_id=7),
        LineTrafficMonthlyStats(id=1, line="example.test", service="plex", username="plexowner", year_month="2026-01", total_bytes=1024**3, created_at="2026-01-01"),
        LineTrafficMonthlyStats(id=2, line="example.test", service="emby", username="other", year_month="2026-01", total_bytes=2 * 1024**3, created_at="2026-01-01"),
        LineTrafficStats(id=1, line="example.test", service="plex", username="plexowner", timestamp="2026-01-02T00:00:00+00:00", send_bytes=3 * 1024**3, event_hash="owner"),
        LineTrafficStats(id=2, line="example.test", service="plex", username="other", timestamp="2026-01-02T00:00:00+00:00", send_bytes=4 * 1024**3, event_hash="other"),
    ])

if os.environ["B3_TRAFFIC_SIDE"] == "b2":
    from app.modules.custom_line import _get_line_monthly_traffic as lookup
else:
    from app.domains.traffic.repository import _get_line_monthly_traffic as lookup

original = identity_repository.get_session
trace = []
@contextmanager
def counted():
    trace.append("open")
    with original() as session:
        try:
            yield session
        finally:
            trace.append("close")
identity_repository.get_session = counted

async def execute():
    cases = []
    for raw in (False, True):
        for owner in (None, 7, 999):
            trace.clear()
            with core_db.get_session() as session:
                value = await lookup(session, "https://example.test/path", "2026-01", owner, raw)
                cases.append([raw, owner, value, list(trace), session.in_transaction()])
    # Both versions must swallow an identity lookup failure identically and
    # leave the caller's transaction available, without writing traffic rows.
    def failing():
        trace.append("failed-open")
        raise RuntimeError("identity lookup failed")
    identity_repository.get_session = failing
    trace.clear()
    with core_db.get_session() as session:
        failed = await lookup(session, "example.test", "2026-01", 7, False)
        cases.append(["identity-error", failed, list(trace), session.in_transaction()])

    # The read-model aggregation moved from traffic to reports unchanged.
    from app.databases import db
    read_module = importlib.import_module(type(db).get_traffic_statistics.__module__)
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 3, tzinfo=tz)
    read_module.datetime = FrozenDatetime
    cases.append(["read-model", db.get_traffic_statistics()])
    return cases
print("B3_DEYCLE_RESULTS=" + json.dumps(asyncio.run(execute())))
"""


def _run(source: Path, side: str, database: Path) -> list[list[object]]:
    env = dict(os.environ)
    env.update(
        DATABASE_URL=f"sqlite:///{database}",
        B3_TRAFFIC_SIDE=side,
        PYTHONPATH=str(source / "src"),
    )
    # Tests can mirror comma-separated settings lists into os.environ; Pydantic
    # expects JSON for an inherited list. Each subprocess reads data/.env itself.
    import sys as _sys

    _sys.path.insert(0, str(ROOT / "src"))
    from app.core.config import Settings

    for key, field in Settings.model_fields.items():
        if field.annotation is list or get_origin(field.annotation) is list:
            env.pop(key, None)
    # Drop the caller's Git index override inside a linked worktree.
    env.pop("GIT_INDEX_FILE", None)
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        cwd=source,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"{side}: {result.stderr[-3500:]}")
    return json.loads(
        next(
            line.split("=", 1)[1]
            for line in result.stdout.splitlines()
            if line.startswith("B3_DEYCLE_RESULTS=")
        )
    )


def main() -> int:
    base = (ROOT / "scripts/refactor/B3_BASE").read_text().strip()
    with tempfile.TemporaryDirectory(prefix="b3-decycle-") as directory:
        workspace = Path(directory)
        old_root = workspace / "b2"
        env = dict(os.environ)
        env.pop("GIT_INDEX_FILE", None)
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(old_root), base],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        try:
            before = _run(old_root, "b2", workspace / "before.db")
            after = _run(ROOT, "b3", workspace / "after.db")
            if before != after:
                print(json.dumps({"ok": False, "before": before, "after": after}))
                return 1
            print(json.dumps({"ok": True, "cases": before}))
            return 0
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(old_root)],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )


if __name__ == "__main__":
    raise SystemExit(main())
