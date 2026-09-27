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
    facade = current / "src/app/databases/db.py"
    facade.parent.mkdir(parents=True)
    facade.write_text("class DatabaseORM:\n    pass\n")
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
            and isinstance(node.args[0].value, str)
        ]
        next(path for path in paths if path.name == "snapshot.json").write_text("{}")
        next(
            path for path in paths if path.name == "module-import-errors.json"
        ).write_text("[]")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _run_snapshot(tmp_path, tmp_path) == {}
    assert list(tmp_path.iterdir()) == []


def test_b2_retained_definition_cannot_be_disguised_as_deletion(tmp_path: Path) -> None:
    from scripts.refactor.verify import compare_inventory

    base, current = tmp_path / "base", tmp_path / "current"
    for root in (base, current):
        file = root / "src/app/webapp/routers/user.py"
        file.parent.mkdir(parents=True)
        file.write_text("def route():\n    return 1\n")
    mapping = tmp_path / "mapping.toml"
    mapping.write_text(
        '[[items]]\nid = "app.webapp.routers.user:route"\n'
        'target = "app.api.app"\nkind = "function"\n'
        'reason = "pretend to delete"\naction = "delete"\n'
    )
    assert any(
        "retained B2 unit marked deleted" in error
        for error in compare_inventory(base, current, mapping)
    )


def test_b2_unrelated_function_cannot_be_disguised_as_assembly(tmp_path: Path) -> None:
    from scripts.refactor.verify import compare_inventory

    base, current = tmp_path / "base", tmp_path / "current"
    old = base / "src/app/webapp/routers/user.py"
    old.parent.mkdir(parents=True)
    old.write_text("def important():\n    return 1\n")
    assembled = current / "src/app/api/app.py"
    assembled.parent.mkdir(parents=True)
    assembled.write_text("def important():\n    return 2\n")
    mapping = tmp_path / "mapping.toml"
    mapping.write_text(
        '[[items]]\nid = "app.webapp.routers.user:important"\n'
        'target = "app.api.app"\nkind = "function"\n'
        'reason = "pretend to assemble"\naction = "assemble"\n'
    )
    assert any(
        "unreviewed assembly unit" in error
        for error in compare_inventory(base, current, mapping)
    )


def test_b2_import_redistribution_must_preserve_each_binding(tmp_path: Path) -> None:
    from scripts.refactor.verify import compare_inventory

    base, current = tmp_path / "base", tmp_path / "current"
    old = base / "src/app/webapp/routers/user.py"
    old.parent.mkdir(parents=True)
    old.write_text("from fastapi import Depends\n", encoding="utf-8")
    target = current / "src/app/domains/profile/router.py"
    target.parent.mkdir(parents=True)
    target.write_text("from fastapi import Depends\n", encoding="utf-8")
    assembly = current / "src/app/api/app.py"
    assembly.parent.mkdir(parents=True)
    assembly.write_text("from fastapi import FastAPI\n", encoding="utf-8")
    mapping = tmp_path / "mapping.toml"
    mapping.write_text(
        '[[items]]\nid = "app.webapp.routers.user:@import:1"\n'
        'target = "app.api.app"\nkind = "import"\n'
        'reason = "B2 reviewed import redistribution: Depends"\n'
        'redistributed_to = ["app.domains.profile.router"]\n',
        encoding="utf-8",
    )
    assert compare_inventory(base, current, mapping) == []
    target.write_text("from fastapi import HTTPException\n", encoding="utf-8")
    assert any(
        "missing import bindings" in error
        for error in compare_inventory(base, current, mapping)
    )


def test_b2_moved_function_cannot_drop_local_import(tmp_path: Path) -> None:
    from scripts.refactor.verify import compare_inventory

    base, current = tmp_path / "base", tmp_path / "current"
    old = base / "src/app/webapp/routers/user.py"
    new = current / "src/app/domains/profile/router.py"
    old.parent.mkdir(parents=True)
    new.parent.mkdir(parents=True)
    old.write_text(
        "def route():\n    from app.webapp.schemas import UserInfo\n    return UserInfo\n",
        encoding="utf-8",
    )
    new.write_text("def route():\n    return UserInfo\n", encoding="utf-8")
    mapping = tmp_path / "mapping.toml"
    mapping.write_text(
        '[[items]]\nid = "app.webapp.routers.user:route"\n'
        'target = "app.domains.profile.router"\nkind = "function"\n'
        'reason = "B2 moved route"\n',
        encoding="utf-8",
    )
    assert any(
        "AST changed" in error for error in compare_inventory(base, current, mapping)
    )


def test_mapping_verifier_rejects_unreviewed_current_only_or_stale_id(
    tmp_path: Path,
) -> None:
    from scripts.refactor.verify import compare_inventory

    base, current = tmp_path / "base", tmp_path / "current"
    old = base / "src/app/example.py"
    new = current / "src/app/example.py"
    old.parent.mkdir(parents=True)
    new.parent.mkdir(parents=True)
    old.write_text("def present():\n    return 1\n", encoding="utf-8")
    new.write_text(
        "def present():\n    return 1\n\ndef added():\n    return 2\n", encoding="utf-8"
    )
    mapping = tmp_path / "mapping.toml"
    prefix = (
        '[[items]]\nid = "app.example:present"\n'
        'target = "app.example"\nkind = "function"\nreason = "keep"\n'
    )
    current_only = (
        '[[items]]\nid = "app.example:added"\n'
        'target = "app.example"\nkind = "function"\nreason = "current"\n'
    )
    mapping.write_text(prefix + current_only, encoding="utf-8")
    assert any("current-only" in x for x in compare_inventory(base, current, mapping))
    mapping.write_text(prefix + current_only + 'source_state = "current"\n')
    assert compare_inventory(base, current, mapping) == []
    mapping.write_text(
        prefix
        + current_only
        + 'source_state = "current"\n'
        + '[[items]]\nid = "app.example:missing"\n'
        + 'target = "app.example"\nkind = "function"\n'
        + 'reason = "not actually present"\nsource_state = "current"\n'
    )
    assert any("stale" in x for x in compare_inventory(base, current, mapping))


def test_reviewed_field_default_normalization_rejects_added_constraints(
    tmp_path: Path,
) -> None:
    from scripts.refactor.verify import compare_inventory

    base, current = tmp_path / "base", tmp_path / "current"
    old = base / "src/app/webapp/schemas/user.py"
    new = current / "src/app/domains/profile/schemas.py"
    old.parent.mkdir(parents=True)
    new.parent.mkdir(parents=True)
    old.write_text(
        "class CustomLineListResponse:\n    lines: list[str] = []\n",
        encoding="utf-8",
    )
    new.write_text(
        "class CustomLineListResponse:\n    lines: list[str] = Field(default=[])\n",
        encoding="utf-8",
    )
    mapping = tmp_path / "mapping.toml"
    mapping.write_text(
        '[[items]]\nid = "app.webapp.schemas.user:CustomLineListResponse"\n'
        'target = "app.domains.profile.schemas"\nkind = "class"\nreason = "move"\n'
        '[[items]]\nid = "app.webapp.schemas.user:CustomLineListResponse.lines"\n'
        'target = "app.domains.profile.schemas"\nkind = "attribute"\nreason = "move"\n',
        encoding="utf-8",
    )
    assert compare_inventory(base, current, mapping) == []
    new.write_text(
        "class CustomLineListResponse:\n"
        "    lines: list[str] = Field(default=[], min_length=1)\n",
        encoding="utf-8",
    )
    assert any(
        "AST changed" in error for error in compare_inventory(base, current, mapping)
    )


def test_blackjack_timeout_persisted_ref_normalization_is_exact() -> None:
    import ast
    from dataclasses import replace

    from scripts.refactor.inventory import Item
    from scripts.refactor.verify import _normalized

    item = Item(
        id="app.webapp.routers.activities.blackjack:_schedule_blackjack_timeout",
        module="app.webapp.routers.activities.blackjack",
        name="_schedule_blackjack_timeout",
        kind="function",
        path="blackjack.py",
        start_line=1,
        end_line=1,
        ast="",
    )
    original = ast.parse(
        "def schedule():\n    scheduler.add_async_job(func=_settle_blackjack_hand_on_timeout)\n"
    ).body[0]
    preserved = ast.parse(
        'def schedule():\n    scheduler.add_async_job(func="app.webapp.routers.activities.blackjack:_settle_blackjack_hand_on_timeout")\n'
    ).body[0]
    altered = ast.parse(
        'def schedule():\n    scheduler.add_async_job(func="app.domains.blackjack.jobs.cash:_settle_blackjack_hand_on_timeout")\n'
    ).body[0]
    assert _normalized(item, original) == _normalized(item, preserved)
    assert _normalized(item, original) != _normalized(item, altered)
    assert _normalized(replace(item, id="unrelated:call"), original) != _normalized(
        replace(item, id="unrelated:call"), preserved
    )


def test_treasure_auto_reopen_persisted_ref_normalization_is_exact() -> None:
    import ast

    from scripts.refactor.inventory import Item
    from scripts.refactor.verify import _normalized

    item = Item(
        id="app.webapp.routers.activities.treasure:schedule_auto_reopen_treasure_issue",
        module="app.webapp.routers.activities.treasure",
        name="schedule_auto_reopen_treasure_issue",
        kind="function",
        path="treasure.py",
        start_line=1,
        end_line=1,
        ast="",
    )
    original = ast.parse(
        "def schedule():\n    Scheduler().add_async_job(func=_auto_create_next_treasure_issue_from)\n"
    ).body[0]
    preserved = ast.parse(
        'def schedule():\n    Scheduler().add_async_job(func="app.webapp.routers.activities.treasure:_auto_create_next_treasure_issue_from")\n'
    ).body[0]
    changed = ast.parse(
        'def schedule():\n    Scheduler().add_async_job(func="app.domains.treasure.jobs:_auto_create_next_treasure_issue_from")\n'
    ).body[0]
    assert _normalized(item, original) == _normalized(item, preserved)
    assert _normalized(item, original) != _normalized(item, changed)


def test_b3_ast_exception_requires_itemized_behavior_test(tmp_path: Path) -> None:
    from scripts.refactor.verify import compare_inventory

    base = tmp_path / "base"
    current = tmp_path / "current"
    original = base / "src/app/legacy.py"
    moved = current / "src/app/domains/example.py"
    original.parent.mkdir(parents=True)
    moved.parent.mkdir(parents=True)
    original.write_text("def run():\n    return 1\n")
    moved.write_text("def run():\n    return 2\n")
    mapping = tmp_path / "mapping.toml"
    mapping.write_text(
        "[[items]]\n"
        'id = "app.legacy:run"\n'
        'target = "app.domains.example"\n'
        'kind = "function"\n'
        'reason = "B3 reviewed behavior change"\n'
        'b3_ast_exception = "B3 reviewed behavior change"\n'
    )
    assert any(
        "AST changed" in error for error in compare_inventory(base, current, mapping)
    )
    mapping.write_text(
        mapping.read_text() + 'b3_behavior_test = "tests/example.py::test_run"\n'
    )
    assert any(
        "AST changed" in error for error in compare_inventory(base, current, mapping)
    )
    test_file = current / "tests/example.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_run():\n    assert True\n")
    assert compare_inventory(base, current, mapping) == []


def test_ast_exception_must_name_a_reviewed_change(tmp_path: Path) -> None:
    """例外必须写成 `<变更> reviewed <说明>`，且变更是真实存在的 OpenSpec 变更。"""
    from scripts.refactor.verify import _reviewed_ast_exception

    root = tmp_path
    (root / "openspec/changes/promote-sample-domain").mkdir(parents=True)
    assert _reviewed_ast_exception("B3 reviewed named task registry", root)
    assert _reviewed_ast_exception("promote-sample-domain reviewed split", root)
    # 变更目录不存在时拒绝
    assert not _reviewed_ast_exception("promote-unknown-domain reviewed split", root)
    # 缺少 reviewed 标记或说明时拒绝
    assert not _reviewed_ast_exception("promote-sample-domain arbitrary note", root)
    assert not _reviewed_ast_exception("promote-sample-domain reviewed", root)
    assert not _reviewed_ast_exception(None, root)


def _split_mapping() -> str:
    """Mapping entries for a facade class whose method moved into a mixin."""
    return (
        "[[items]]\n"
        'id = "app.databases.db:DatabaseORM"\n'
        'target = "app.databases.db"\n'
        'kind = "class"\n'
        'reason = "facade"\n'
        'action = "assemble"\n'
        "[[items]]\n"
        'id = "app.databases.db:DatabaseORM.reserve"\n'
        'target = "app.domains.sample.repository"\n'
        'kind = "method"\n'
        'reason = "sub-topic split"\n'
    )


def test_repository_package_search_includes_sub_topic_modules(tmp_path: Path) -> None:
    from scripts.refactor.verify import _module_paths

    package = tmp_path / "src/app/domains/sample/repository"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "conditions.py").write_text("class Conditions:\n    pass\n")
    (package / "part_9.py").write_text("class Legacy:\n    pass\n")

    paths = _module_paths(tmp_path, "app.domains.sample.repository")
    assert [path.name for path in paths] == [
        "__init__.py",
        "conditions.py",
        "part_9.py",
    ]


def _write_split_repository(root: Path, mixin: str) -> None:
    """Minimal facade package whose method lives in a sub-topic mixin."""
    package = root / "src/app/domains/sample/repository"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(
        f"from .conditions import {mixin}\n\n\nclass SampleRepository({mixin}):\n    pass\n"
    )
    (package / "conditions.py").write_text(
        f"class {mixin}:\n    def reserve(self, delta):\n        return delta + 1\n"
    )


def test_declared_repository_mixins_resolve_moved_members(tmp_path: Path) -> None:
    from scripts.refactor.verify import compare_inventory

    base = tmp_path / "base"
    current = tmp_path / "current"
    (base / "src/app/databases").mkdir(parents=True)
    (base / "src/app/databases/db.py").write_text(
        "class DatabaseORM:\n    def reserve(self, delta):\n        return delta + 1\n"
    )
    _write_split_repository(current, "_SampleRepositoryConditions")
    (current / "src/app/databases").mkdir(parents=True)
    (current / "src/app/databases/db.py").write_text("class DatabaseORM:\n    pass\n")
    mapping = tmp_path / "mapping.toml"
    mapping.write_text(_split_mapping())

    # 没有声明组合类时，找不到搬移后的成员。
    assert any(
        "missing moved method" in error
        for error in compare_inventory(base, current, mapping)
    )

    mapping.write_text(
        mapping.read_text()
        + "\n[repository_mixins]\n"
        + '"app.domains.sample.repository" = ["_SampleRepositoryConditions"]\n'
    )
    assert compare_inventory(base, current, mapping) == []


def test_declared_repository_mixin_must_exist(tmp_path: Path) -> None:
    from scripts.refactor.verify import compare_inventory

    base = tmp_path / "base"
    current = tmp_path / "current"
    (base / "src/app/databases").mkdir(parents=True)
    (base / "src/app/databases/db.py").write_text(
        "class DatabaseORM:\n    def reserve(self, delta):\n        return delta + 1\n"
    )
    _write_split_repository(current, "_SampleRepositoryConditions")
    (current / "src/app/databases").mkdir(parents=True)
    (current / "src/app/databases/db.py").write_text("class DatabaseORM:\n    pass\n")
    mapping = tmp_path / "mapping.toml"
    mapping.write_text(
        _split_mapping()
        + "\n[repository_mixins]\n"
        + '"app.domains.sample.repository" = ["_SampleRepositoryRenamed"]\n'
    )
    errors = compare_inventory(base, current, mapping)
    assert any("declared repository mixin not found" in error for error in errors), (
        errors
    )


def test_reviewed_change_may_drop_a_base_import(tmp_path: Path) -> None:
    """登记过的变更允许少一个导入绑定（迁移后不再需要某模块时）。"""
    from scripts.refactor.verify import compare_inventory

    base = tmp_path / "base"
    current = tmp_path / "current"
    original = base / "src/app/legacy.py"
    moved = current / "src/app/domains/example.py"
    original.parent.mkdir(parents=True)
    moved.parent.mkdir(parents=True)
    original.write_text("import json\n\n\ndef run():\n    return 1\n")
    moved.write_text("def run():\n    return 1\n")
    test_file = current / "tests/example.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_run():\n    assert True\n")
    mapping = tmp_path / "mapping.toml"
    mapping.write_text(
        "[[items]]\n"
        'id = "app.legacy:run"\n'
        'target = "app.domains.example"\n'
        'kind = "function"\n'
        'reason = "moved"\n'
        "[[items]]\n"
        'id = "app.legacy:@import:1"\n'
        'target = "app.domains.example"\n'
        'kind = "import"\n'
        'reason = "moved"\n'
    )
    assert any(
        "missing import bindings" in error
        for error in compare_inventory(base, current, mapping)
    )

    mapping.write_text(
        mapping.read_text()
        + 'b3_ast_exception = "B3 reviewed removal"\n'
        + 'b3_behavior_test = "tests/example.py::test_run"\n'
    )
    assert compare_inventory(base, current, mapping) == []

    # 例外必须指向真实存在的测试，否则不放行
    mapping.write_text(
        mapping.read_text().replace(
            "tests/example.py::test_run", "tests/example.py::test_missing"
        )
    )
    assert any(
        "missing import bindings" in error
        for error in compare_inventory(base, current, mapping)
    )
