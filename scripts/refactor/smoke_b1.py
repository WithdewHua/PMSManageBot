"""Compare B1 API and TG-ID rebind behavior on disposable SQLite copies.

Runs uvicorn as an API-only process for the frozen Git base and the current
checkout. No Telegram bot, scheduler, production database, or external clients
are started. Temporary databases and Git worktree are removed on completion.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class SmokeError(RuntimeError):
    """The before/after API or database behavior is not equivalent."""


def _environment(root: Path, database: Path, data_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": str(root / "src"),
        "DATABASE_URL": f"sqlite:///{database}",
        "DATA_DIR": str(data_dir),
    }


def _seed(base: Path, database: Path, data_dir: Path) -> None:
    code = """
try:
    from app.core.db import engine
    from app.core.db import Base
    from app.domains.identity.models import Overseerr, PlexUser, Statistics
except ModuleNotFoundError:
    from app.databases.session import engine
    from app.models.models import Base, Overseerr, PlexUser, Statistics
from sqlalchemy.orm import Session
Base.metadata.create_all(bind=engine)
with Session(engine) as session:
    session.add_all([
        Statistics(tg_id=101, credits=12, donation=1),
        Statistics(tg_id=201, credits=5, donation=2),
        Statistics(tg_id=202, credits=7, donation=3),
        PlexUser(tg_id=101, plex_email='smoke-new@example.invalid'),
        PlexUser(tg_id=201, plex_email='smoke-merge@example.invalid'),
        Overseerr(user_id=501, tg_id=101),
        Overseerr(user_id=502, tg_id=201),
    ])
    session.commit()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=base,
        env=_environment(base, database, data_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise SmokeError(f"seed failed: {result.stderr[-1800:]}")


def _get(port: int, path: str, *, auth: bool = False) -> tuple[int, object]:
    headers: dict[str, str] = {}
    if auth:
        headers["X-Telegram-Init-Data"] = urllib.parse.urlencode(
            {
                "user": json.dumps({"id": 101, "first_name": "Smoke"}),
                "hash": "mock_hash_for_development",
            }
        )
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def _serve(root: Path, database: Path, data_dir: Path) -> dict[str, tuple[int, object]]:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    application = (
        "app.api.app:app"
        if (root / "src/app/api/app.py").exists()
        else "app.webapp:app"
    )
    with tempfile.TemporaryFile(mode="w+t") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                application,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--lifespan",
                "off",
            ],
            cwd=root,
            env=_environment(root, database, data_dir),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(80):
                if process.poll() is not None:
                    log.seek(0)
                    output = log.read()[-1800:]
                    raise SmokeError(
                        f"API exited early for {root} (code {process.returncode}): {output}"
                    )
                try:
                    _get(port, "/health")
                    break
                except (OSError, TimeoutError):
                    time.sleep(0.15)
            else:
                raise SmokeError(f"API did not start for {root}")
            responses = {
                path: _get(port, path, auth=auth)
                for path, auth in (
                    ("/health", False),
                    ("/api/system/status", False),
                    ("/api/rankings/credits", True),
                    ("/openapi.json", False),
                )
            }
            failures = {
                path: status for path, (status, _) in responses.items() if status != 200
            }
            if failures:
                raise SmokeError(
                    f"read-only API returned non-200 for {root}: {failures}"
                )
            return responses
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _rebind(root: Path, database: Path, data_dir: Path) -> dict[str, object]:
    code = """
import json
from sqlalchemy import select
from app.databases import db
try:
    from app.core.db import get_session
    from app.domains.identity.models import Overseerr, PlexUser, Statistics
except ModuleNotFoundError:
    from app.databases.session import get_session
    from app.models import Overseerr, PlexUser, Statistics
results = [
    db.rebind_user_tg_id(103, plex_email='smoke-new@example.invalid'),
    db.rebind_user_tg_id(202, plex_email='smoke-merge@example.invalid'),
]
with get_session() as session:
    state = {
        'results': results,
        'statistics': sorted([list(row) for row in session.execute(
            select(Statistics.tg_id, Statistics.credits, Statistics.donation)).all()]),
        'plex_users': sorted([list(row) for row in session.execute(
            select(PlexUser.plex_email, PlexUser.tg_id)).all()]),
        'overseerr': sorted([list(row) for row in session.execute(
            select(Overseerr.user_id, Overseerr.tg_id)).all()]),
    }
print(json.dumps(state, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env=_environment(root, database, data_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise SmokeError(f"rebind failed for {root}: {result.stderr[-1800:]}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def smoke(base_ref: str, repository: Path) -> dict[str, object]:
    repository = repository.resolve()
    with tempfile.TemporaryDirectory(prefix="pms-b1-smoke-") as temp:
        folder = Path(temp)
        base = folder / "base"
        added = subprocess.run(
            ["git", "worktree", "add", "--detach", str(base), base_ref],
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )
        if added.returncode:
            raise SmokeError(added.stderr.strip())
        try:
            data_dir = folder / "data"
            data_dir.mkdir()
            seed_db = folder / "seed.sqlite"
            _seed(base, seed_db, data_dir)
            left_db, right_db = folder / "base.sqlite", folder / "current.sqlite"
            shutil.copy2(seed_db, left_db)
            shutil.copy2(seed_db, right_db)
            left_api = _serve(base, left_db, data_dir)
            right_api = _serve(repository, right_db, data_dir)
            if left_api != right_api:
                differing = [
                    path for path in left_api if left_api[path] != right_api[path]
                ]
                raise SmokeError(f"read-only API responses differ: {differing}")
            left = _rebind(base, left_db, data_dir)
            right = _rebind(repository, right_db, data_dir)
            if left != right:
                raise SmokeError(f"TG rebind states differ: {left!r} != {right!r}")
            if left["results"] != [True, True] or left["statistics"] != [
                [103, 12.0, 1.0],
                [202, 12.0, 5.0],
            ]:
                raise SmokeError(f"TG rebind result unexpected: {left!r}")
            return {"ok": True, "read_only_paths": list(left_api), "rebind": left}
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(base)],
                cwd=repository,
                capture_output=True,
                text=True,
                check=False,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        result = smoke(args.base, args.repository)
    except SmokeError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
