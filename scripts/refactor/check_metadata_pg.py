"""Compare baseline and current SQLAlchemy metadata on disposable PostgreSQL.

Example::

    python -m scripts.refactor.check_metadata_pg \
        --base HEAD --url postgresql+psycopg2://user:pass@localhost/pms_check

The database URL must point at a disposable database. The checker drops tables
owned by the baseline metadata before creating the baseline schema, compares
current metadata with Alembic's ``compare_metadata``, then drops the baseline
schema again. It never runs application migrations or opens application
sessions.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url


class MetadataCheckError(RuntimeError):
    """The metadata comparison could not be completed or found differences."""


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


def validate_postgres_url(url: str) -> None:
    parsed = make_url(url)
    if parsed.get_backend_name() not in {"postgresql", "postgres"}:
        raise MetadataCheckError(
            "metadata comparison requires a PostgreSQL URL; use a disposable PostgreSQL database"
        )


def _pythonpath(tool_root: Path, target_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(tool_root), str(target_root / "src"), env.get("PYTHONPATH", "")]
    )
    return env


def _run_worker(
    tool_root: Path,
    target_root: Path,
    code: str,
    *,
    url: str,
) -> str:
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tool_root,
        env=_pythonpath(tool_root, target_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise MetadataCheckError(
            f"metadata worker failed for {target_root}: {result.stderr[-3000:]}"
        )
    return result.stdout


def _create_baseline(tool_root: Path, base_root: Path, url: str) -> None:
    code = f"""
from sqlalchemy import create_engine
try:
    from app.model_registry import metadata
except ModuleNotFoundError:  # B2 之前的树里元数据还在 legacy models 模块
    from app.models.models import Base as _Base

    metadata = _Base.metadata
engine = create_engine({url!r})
with engine.begin() as connection:
    metadata.drop_all(connection)
    metadata.create_all(connection)
engine.dispose()
"""
    _run_worker(tool_root, base_root, code, url=url)


def _compare_current(tool_root: Path, current_root: Path, url: str) -> list[Any]:
    code = f"""
import json
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine
try:
    from app.model_registry import metadata
except ModuleNotFoundError:  # B2 之前的树里元数据还在 legacy models 模块
    from app.models.models import Base as _Base

    metadata = _Base.metadata
engine = create_engine({url!r})
with engine.connect() as connection:
    context = MigrationContext.configure(connection)
    differences = compare_metadata(context, metadata)
    print(json.dumps([repr(item) for item in differences], ensure_ascii=False))
engine.dispose()
"""
    output = _run_worker(tool_root, current_root, code, url=url)
    try:
        return json.loads(output.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as error:
        raise MetadataCheckError("metadata worker returned invalid JSON") from error


def _cleanup_baseline(tool_root: Path, base_root: Path, url: str) -> None:
    code = f"""
from sqlalchemy import create_engine
try:
    from app.model_registry import metadata
except ModuleNotFoundError:  # B2 之前的树里元数据还在 legacy models 模块
    from app.models.models import Base as _Base

    metadata = _Base.metadata
engine = create_engine({url!r})
with engine.begin() as connection:
    metadata.drop_all(connection)
engine.dispose()
"""
    _run_worker(tool_root, base_root, code, url=url)


def check_metadata(base_ref: str, url: str, repository: Path) -> list[Any]:
    """Return Alembic metadata differences, using an isolated Git baseline."""
    validate_postgres_url(url)
    repository = repository.resolve()
    with tempfile.TemporaryDirectory(prefix="pms-metadata-") as temporary:
        base_root = Path(temporary) / "base"
        result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(base_root), base_ref],
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise MetadataCheckError(result.stderr.strip())
        try:
            _create_baseline(repository, base_root, url)
            try:
                return _compare_current(repository, repository, url)
            finally:
                _cleanup_baseline(repository, base_root, url)
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(base_root)],
                cwd=repository,
                capture_output=True,
                check=False,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base", required=True, help="Git ref containing baseline metadata"
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("METADATA_PG_URL"),
        help="Disposable PostgreSQL URL (or METADATA_PG_URL)",
    )
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if not args.url:
        parser.error("--url or METADATA_PG_URL is required")
    try:
        differences = check_metadata(args.base, args.url, args.repository)
    except MetadataCheckError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {"ok": not differences, "differences": _json_safe(differences)},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0 if not differences else 1


if __name__ == "__main__":
    raise SystemExit(main())
