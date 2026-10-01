"""Deterministic behavior snapshot fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify import snapshot
from scripts.verify.snapshot import (
    _dump,
    _static_reference_snapshot,
    build_snapshot,
)


def test_snapshot_is_byte_stable_and_contains_all_behavior_surfaces() -> None:
    first = build_snapshot()
    second = build_snapshot()

    assert _dump(first) == _dump(second)
    assert first["schema"] == 1
    assert first["openapi"]["openapi"]["paths"]
    assert first["openapi"]["routes"]
    assert first["metadata"]["tables"]
    assert first["scheduler"]["jobs"]
    assert first["bot"]["handlers"]
    assert first["bot"]["commands"]
    assert "facade" not in first
    assert first["references"]["imports"]
    assert "strings" not in first["references"]


def test_snapshot_does_not_require_database_for_scheduler_registration() -> None:
    snapshot_data = build_snapshot()
    job_ids = {
        job["kwargs"]["id"]
        for job in snapshot_data["scheduler"]["jobs"]
        if "id" in job["kwargs"]
    }
    assert "update_credits" in job_ids
    assert snapshot_data["scheduler"]["restoration_hooks"] == [
        "restore_auction_schedules",
        "restore_blackjack_timeouts",
    ]
    assert all(
        "relative_seconds" not in job["kwargs"].get("id", "")
        for job in snapshot_data["scheduler"]["jobs"]
    )


def test_build_snapshot_fails_when_src_app_missing(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="src/app directory missing"):
        build_snapshot(root=tmp_path)


def test_build_snapshot_fails_when_routes_empty(monkeypatch) -> None:
    monkeypatch.setattr(snapshot, "_route_snapshot", lambda app: {"routes": []})
    with pytest.raises(RuntimeError, match="Snapshot openapi routes must not be empty"):
        build_snapshot()


def test_build_snapshot_fails_when_imports_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        snapshot, "_static_reference_snapshot", lambda root: {"imports": []}
    )
    with pytest.raises(RuntimeError, match="Snapshot static imports must not be empty"):
        build_snapshot()


def test_static_reference_snapshot_resolves_function_imports_and_paths(
    tmp_path: Path,
) -> None:
    package = tmp_path / "src/app"
    (package / "pkg").mkdir(parents=True)
    (package / "pkg/__init__.py").write_text("", encoding="utf-8")
    (package / "pkg/worker.py").write_text("def run():\n    pass\n", encoding="utf-8")
    (package / "pkg/consumer.py").write_text(
        "def invoke():\n"
        "    from .worker import run\n"
        "    import app.pkg.worker\n"
        "    return run()\n"
        "scheduler.add_job('app.pkg.worker:run')\n"
        "print('not a callable reference')\n",
        encoding="utf-8",
    )

    ref_snapshot = _static_reference_snapshot(tmp_path)
    function_imports = [
        item for item in ref_snapshot["imports"] if item["scope"] == "function"
    ]
    assert any(item["target"] == "app.pkg.worker.run" for item in function_imports)
    assert all(item["resolved"] for item in function_imports)
    assert "not a callable reference" not in json.dumps(ref_snapshot)
