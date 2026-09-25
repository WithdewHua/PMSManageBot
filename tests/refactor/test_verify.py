"""Equivalence verifier fixtures."""

from __future__ import annotations

import copy
from pathlib import Path

from scripts.refactor.verify import (
    VerificationError,
    compare_routes,
    compare_snapshots,
    routes_overlap,
)


def _route(path: str, order: int, methods: list[str] | None = None) -> dict:
    return {
        "order": order,
        "path": path,
        "methods": methods or ["GET"],
        "name": path,
        "endpoint": f"app.api:{path.replace('/', '_')}",
        "response_model": None,
    }


def test_non_overlapping_route_reorder_is_allowed() -> None:
    base = [_route("/alpha", 0), _route("/beta", 1)]
    current = [_route("/beta", 0), _route("/alpha", 1)]
    assert not compare_routes(base, current)
    assert not routes_overlap(base[0], base[1])


def test_overlapping_route_reorder_is_rejected() -> None:
    base = [_route("/users/{user_id}", 0), _route("/users/me", 1)]
    current = [_route("/users/me", 0), _route("/users/{user_id}", 1)]
    errors = compare_routes(base, current)
    assert errors and "overlapping routes" in errors[0]
    assert routes_overlap(base[0], base[1])


def test_snapshot_detects_functional_surface_differences() -> None:
    base = {
        "openapi": {"openapi": {"paths": {}}, "routes": []},
        "metadata": {"tables": []},
        "scheduler": {"jobs": []},
        "bot": {"handlers": [], "commands": []},
        "facade": {"public_methods": []},
        "references": {"imports": [], "strings": []},
    }
    current = copy.deepcopy(base)
    current["metadata"]["tables"].append({"name": "unexpected"})
    assert "metadata snapshot changed" in compare_snapshots(base, current)


def test_snapshot_rejects_unresolved_references() -> None:
    base = {
        "openapi": {"openapi": {"paths": {}}, "routes": []},
        "metadata": {"tables": []},
        "scheduler": {"jobs": []},
        "bot": {"handlers": [], "commands": []},
        "facade": {"public_methods": []},
        "references": {
            "imports": [{"resolved": False}],
            "strings": [{"resolved": True}],
        },
    }
    assert "unresolved import in base reference snapshot" in compare_snapshots(
        base, base
    )


def test_verify_error_is_public() -> None:
    assert issubclass(VerificationError, ValueError)


def test_inventory_comparison_reports_function_body_change(tmp_path: Path) -> None:
    for root in (tmp_path / "base", tmp_path / "current"):
        (root / "src/app").mkdir(parents=True)
    (tmp_path / "base/src/app/sample.py").write_text(
        "def calculate(value):\n    return value + 1\n", encoding="utf-8"
    )
    (tmp_path / "current/src/app/sample.py").write_text(
        "def calculate(value):\n    return value + 2\n", encoding="utf-8"
    )
    from scripts.refactor.verify import compare_inventory

    assert compare_inventory(tmp_path / "base", tmp_path / "current")


def test_snapshot_reports_missing_task_and_facade_method() -> None:
    base = {
        "openapi": {"openapi": {"paths": {}}, "routes": []},
        "metadata": {"tables": []},
        "scheduler": {"jobs": [{"kwargs": {"id": "one"}}]},
        "bot": {"handlers": [], "commands": []},
        "facade": {"public_methods": ["manual_entry"]},
        "references": {"imports": [], "strings": []},
    }
    current = copy.deepcopy(base)
    current["scheduler"]["jobs"] = []
    current["facade"]["public_methods"] = []
    errors = compare_snapshots(base, current)
    assert "scheduler snapshot changed" in errors
    assert "db facade public methods changed" in errors
