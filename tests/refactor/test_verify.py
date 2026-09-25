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


def test_mapping_verifier_detects_changed_or_missing_moved_method(
    tmp_path: Path,
) -> None:
    from scripts.refactor.verify import compare_inventory

    base = tmp_path / "base"
    current = tmp_path / "current"
    original = base / "src/app/databases/db.py"
    moved = current / "src/app/domains/credits/repository.py"
    original.parent.mkdir(parents=True)
    moved.parent.mkdir(parents=True)
    original.write_text(
        "class DatabaseORM:\n    def reserve(self, delta):\n        return delta + 1\n"
    )
    moved.write_text(
        "class CreditsRepository:\n"
        "    def reserve(self, delta):\n"
        "        return delta + 1\n"
    )
    mapping = tmp_path / "mapping.toml"
    mapping.write_text(
        '[[items]]\nid = "app.databases.db:DatabaseORM"\n'
        'target = "app.databases.db"\nkind = "class"\n'
        'reason = "facade"\naction = "assemble"\n'
        '[[items]]\nid = "app.databases.db:DatabaseORM.reserve"\n'
        'target = "app.domains.credits.repository"\n'
        'class = "CreditsRepository"\nkind = "method"\nreason = "move"\n'
    )
    assert compare_inventory(base, current, mapping) == []
    moved.write_text(moved.read_text().replace("delta + 1", "delta + 2"))
    assert any(
        "AST changed" in error for error in compare_inventory(base, current, mapping)
    )
    moved.write_text("class CreditsRepository:\n    pass\n")
    assert any(
        "missing moved method" in error
        for error in compare_inventory(base, current, mapping)
    )


def test_mapping_verifier_detects_lost_model_column(tmp_path: Path) -> None:
    from scripts.refactor.verify import compare_inventory

    base, current = tmp_path / "base", tmp_path / "current"
    old = base / "src/app/models/models.py"
    new = current / "src/app/domains/identity/models.py"
    old.parent.mkdir(parents=True)
    new.parent.mkdir(parents=True)
    text = "class Person(Base):\n    credits = mapped_column(Integer)\n"
    old.write_text(text)
    new.write_text(text)
    mapping = tmp_path / "mapping.toml"
    mapping.write_text(
        '[[items]]\nid = "app.models.models:Person"\n'
        'target = "app.domains.identity.models"\nkind = "class"\nreason = "move"\n'
        '[[items]]\nid = "app.models.models:Person.credits"\n'
        'target = "app.domains.identity.models"\nkind = "attribute"\nreason = "move"\n'
    )
    assert compare_inventory(base, current, mapping) == []
    new.write_text("class Person(Base):\n    pass\n")
    assert any(
        "missing moved attribute" in x
        for x in compare_inventory(base, current, mapping)
    )


def test_mapping_verifier_rejects_changed_executable_top_level_statement(
    tmp_path: Path,
) -> None:
    from scripts.refactor.inventory import inventory
    from scripts.refactor.verify import compare_inventory

    base, current = tmp_path / "base", tmp_path / "current"
    old = base / "src/app/log.py"
    new = current / "src/app/core/log.py"
    old.parent.mkdir(parents=True)
    new.parent.mkdir(parents=True)
    source = "flag = 1\nwhile flag:\n    flag = 0\n"
    old.write_text(source)
    new.write_text(source)
    mapping = tmp_path / "mapping.toml"
    mapping.write_text(
        "".join(
            "[[items]]\n"
            f'id = "{item.id}"\n'
            'target = "app.core.log"\n'
            f'kind = "{item.kind}"\n'
            'reason = "move executable statement"\n'
            for item in inventory([old], root=base)
        )
    )
    assert compare_inventory(base, current, mapping) == []
    new.write_text(source.replace("flag = 0", "flag = 2"))
    assert any(
        "statement" in error for error in compare_inventory(base, current, mapping)
    )


def test_snapshot_verification_leaves_no_files_in_checkout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import ast
    import subprocess

    from scripts.refactor.verify import _run_snapshot

    def fake_run(argv, **kwargs):
        paths = [
            Path(node.args[0].value)
            for node in ast.walk(ast.parse(argv[-1]))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Path"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ]
        next(path for path in paths if path.name == "snapshot.json").write_text("{}")
        next(
            path for path in paths if path.name == "module-import-errors.json"
        ).write_text("[]")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _run_snapshot(tmp_path, tmp_path) == {}
    assert list(tmp_path.iterdir()) == []
