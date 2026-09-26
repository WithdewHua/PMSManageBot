"""Compare B2 uvicorn API responses on isolated, identically seeded SQLite copies.

The frozen base runs app.webapp:app; the current checkout runs app.api.app:app.
No bot, scheduler, live database, or external services are started.
"""

from __future__ import annotations

import argparse
import json
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

from scripts.refactor.smoke_b1 import SmokeError, _environment, _seed

# Cover public, authenticated user, and authenticated administrator routes.
_REQUESTS = (
    ("/health", None, 200),
    ("/api/system/status", None, 200),
    ("/api/rankings/credits", 101, 200),
    ("/api/admin/settings", 123456789, 200),
    ("/api/admin/settings", None, 401),
    ("/openapi.json", None, 200),
)


def _get(port: int, path: str, user_id: int | None) -> tuple[int, object]:
    headers: dict[str, str] = {}
    if user_id is not None:
        headers["X-Telegram-Init-Data"] = urllib.parse.urlencode(
            {
                "user": json.dumps({"id": user_id, "first_name": "Smoke"}),
                "hash": "mock_hash_for_development",
            }
        )
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def _serve(
    root: Path, database: Path, data_dir: Path, *, target: str
) -> list[tuple[int, object]]:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryFile(mode="w+t") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                target,
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
                    raise SmokeError(
                        f"API exited early ({process.returncode}): {log.read()[-1500:]}"
                    )
                try:
                    _get(port, "/health", None)
                    break
                except (OSError, TimeoutError):
                    time.sleep(0.15)
            else:
                raise SmokeError(f"API did not start: {target}")
            responses = [_get(port, path, user_id) for path, user_id, _ in _REQUESTS]
            failures = [
                (path, actual, expected)
                for (path, _, expected), (actual, _) in zip(
                    _REQUESTS, responses, strict=True
                )
                if actual != expected
            ]
            if failures:
                log.seek(0)
                raise SmokeError(
                    f"unexpected API statuses for {target}: {failures}; "
                    f"server log: {log.read()[-1500:]}"
                )
            return responses
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def smoke(base_ref: str, repository: Path) -> dict[str, object]:
    repository = repository.resolve()
    with tempfile.TemporaryDirectory(prefix="pms-b2-smoke-") as temp:
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
            left = _serve(base, left_db, data_dir, target="app.webapp:app")
            right = _serve(repository, right_db, data_dir, target="app.api.app:app")
            if left != right:
                differing = [
                    path
                    for (path, _, _), old, new in zip(
                        _REQUESTS, left, right, strict=True
                    )
                    if old != new
                ]
                raise SmokeError(f"API responses differ: {differing}")
            return {"ok": True, "paths": [path for path, _, _ in _REQUESTS]}
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(base)],
                cwd=repository,
                capture_output=True,
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
