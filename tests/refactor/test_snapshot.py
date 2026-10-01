"""Deterministic behavior snapshot fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.refactor.snapshot import (
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
    assert "public_methods" in first["facade"]
    assert first["references"]["imports"]
    assert first["references"]["strings"]


def test_snapshot_does_not_require_database_for_scheduler_registration() -> None:
    snapshot = build_snapshot()
    job_ids = {
        job["kwargs"]["id"]
        for job in snapshot["scheduler"]["jobs"]
        if "id" in job["kwargs"]
    }
    assert "update_credits" in job_ids
    assert snapshot["scheduler"]["restoration_hooks"] == [
        "restore_auction_schedules",
        "restore_blackjack_timeouts",
    ]
    assert all(
        "relative_seconds" not in job["kwargs"].get("id", "")
        for job in snapshot["scheduler"]["jobs"]
    )


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

    snapshot = _static_reference_snapshot(tmp_path)
    function_imports = [
        item for item in snapshot["imports"] if item["scope"] == "function"
    ]
    assert any(item["target"] == "app.pkg.worker.run" for item in function_imports)
    assert all(item["resolved"] for item in function_imports)
    paths = [item for item in snapshot["strings"] if item["kind"] == "add_job"]
    assert paths == [
        {
            "kind": "add_job",
            "line": 5,
            "module": "app.pkg.consumer",
            "resolved": True,
            "scope": "module",
            "value": "app.pkg.worker:run",
        }
    ]
    assert "not a callable reference" not in json.dumps(snapshot)
