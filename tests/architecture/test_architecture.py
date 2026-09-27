"""Focused tests for the repository architecture scanners."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from .checks import (
    scan_all,
    scan_cross_domain_calls,
    scan_line_budgets,
    scan_mixin_duplicates,
    scan_model_registry,
    scan_numbered_modules,
)
from .helpers import (
    BASELINE_PATH,
    PROJECT_ROOT,
    assert_baseline_exact,
    load_baseline,
    owner_for_domain,
    write_baseline,
)


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_current_layout_matches_the_architecture_baseline() -> None:
    baseline = load_baseline(BASELINE_PATH)
    actual = scan_all(PROJECT_ROOT)

    for category, entries in actual.items():
        assert_baseline_exact(category, entries, baseline)


def test_domain_models_can_configure_mappers_independently() -> None:
    model_paths = sorted((PROJECT_ROOT / "src/app/domains").glob("*/models.py"))
    model_paths += sorted(
        (PROJECT_ROOT / "src/app/domains").glob("*/models/__init__.py")
    )
    # Settings.load_config_from_file() mirrors comma-separated list values into
    # os.environ; Pydantic expects JSON if those inherited values are present in
    # a fresh process. Let each subprocess read data/.env independently.
    from typing import get_origin

    from app.core.config import Settings

    list_fields = {
        name
        for name, field in Settings.model_fields.items()
        if field.annotation is list or get_origin(field.annotation) is list
    }
    env = {key: value for key, value in os.environ.items() if key not in list_fields}
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    for path in model_paths:
        domain = path.relative_to(PROJECT_ROOT / "src/app/domains").parts[0]
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import importlib; from sqlalchemy.orm import configure_mappers; "
                "importlib.import_module('app.domains." + domain + ".models'); "
                "configure_mappers()",
            ],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{domain}: {result.stderr}"


def test_line_budget_regression_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "src/app/databases/db.py", "\n" * 1001)
    actual = scan_line_budgets(tmp_path)
    baseline = {
        "line_budgets": [
            {
                "key": "src/app/databases/db.py",
                "owner": "restructure-backend-architecture",
                "path": "src/app/databases/db.py",
                "lines": 1001,
            }
        ]
    }
    assert_baseline_exact("line_budgets", actual, baseline)

    _write(tmp_path, "src/app/databases/db.py", "\n" * 1002)
    with pytest.raises(AssertionError, match="line counts changed"):
        assert_baseline_exact("line_budgets", scan_line_budgets(tmp_path), baseline)


def test_cross_domain_facade_and_self_calls_are_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/app/databases/db.py",
        """
from app.domains.a.repository import ARepository
from app.domains.b.repository import BRepository


class DatabaseORM(ARepository, BRepository):
    pass


db = DatabaseORM()
""",
    )
    _write(
        tmp_path,
        "src/app/domains/a/repository.py",
        """
class ARepository:
    def call_b(self):
        self.b_method()
""",
    )
    _write(
        tmp_path,
        "src/app/domains/b/repository.py",
        """
class BRepository:
    def b_method(self):
        return True
""",
    )
    _write(
        tmp_path,
        "src/app/domains/a/service.py",
        """
from app.databases import db


def call_b():
    return db.b_method()
""",
    )

    violations = scan_cross_domain_calls(tmp_path)
    kinds = {entry["kind"] for entry in violations}
    assert {"facade_call", "self_call"} <= kinds
    assert all(entry["source_domain"] == "a" for entry in violations)


def test_cross_domain_types_imports_and_calls_are_allowed(tmp_path: Path) -> None:
    """types 是共享词汇：任何角色都可跨域导入与调用（design D3）。"""
    _write(
        tmp_path,
        "src/app/domains/a/repository.py",
        """
from app.domains.b.types import Money


def spend():
    return Money.of(1)
""",
    )
    assert scan_cross_domain_calls(tmp_path) == []


def test_types_role_does_not_whitelist_neighbour_roles(tmp_path: Path) -> None:
    """只有 types 被放开，同一领域里的其它角色仍然登记为债务。"""
    _write(
        tmp_path,
        "src/app/domains/a/repository.py",
        """
from app.domains.b.models import Ledger


def spend():
    return Ledger.query()
""",
    )
    keys = {
        (entry["target_module"], entry.get("symbol"))
        for entry in scan_cross_domain_calls(tmp_path)
    }
    assert ("app.domains.b.models", "Ledger") in keys


def test_cross_domain_import_and_direct_call_are_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/app/domains/a/router.py",
        """
from app.domains.b.repository import not_a_transaction


def route():
    return not_a_transaction()
""",
    )
    _write(
        tmp_path,
        "src/app/domains/b/repository.py",
        """
class BRepository:
    def not_a_transaction(self):
        return True
""",
    )

    violations = scan_cross_domain_calls(tmp_path)
    assert {entry["kind"] for entry in violations} == {"import", "call"}
    assert all(entry["target_domain"] == "b" for entry in violations)


def test_model_registry_completeness_supports_explicit_registry(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/app/domains/a/models.py",
        """
class AModel(Base):
    pass
""",
    )
    _write(
        tmp_path,
        "src/app/domains/b/models.py",
        """
class BModel(Base):
    pass
""",
    )
    _write(
        tmp_path,
        "src/app/model_registry.py",
        """
from app.domains.a.models import AModel
""",
    )

    violations = scan_model_registry(tmp_path)
    assert [entry["model"] for entry in violations] == ["BModel"]

    with (tmp_path / "src/app/model_registry.py").open("a", encoding="utf-8") as file:
        file.write("from app.domains.b.models import BModel\n")
    assert scan_model_registry(tmp_path) == []


def test_legacy_model_layout_is_considered_registered(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/app/models/models.py",
        """
class LegacyModel(Base):
    pass
""",
    )
    assert scan_model_registry(tmp_path) == []


def test_mixin_duplicate_members_are_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/app/domains/a/repository.py",
        """
class ARepository:
    def shared(self):
        return 1
""",
    )
    _write(
        tmp_path,
        "src/app/domains/b/repository.py",
        """
class BRepository:
    def shared(self):
        return 2
""",
    )

    violations = scan_mixin_duplicates(tmp_path)
    assert len(violations) == 1
    assert violations[0]["member"] == "shared"


def test_baseline_writer_round_trips_without_refreshing_repository_baseline(
    tmp_path: Path,
) -> None:
    baseline = {
        "cross_domain_calls": [],
        "line_budgets": [],
        "model_registry": [],
        "mixin_duplicates": [],
        "numbered_modules": [],
    }
    path = tmp_path / "baseline.json"
    write_baseline(baseline, path)
    assert load_baseline(path) == baseline
    assert BASELINE_PATH.exists()


def test_numbered_repository_modules_are_rejected(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline = {
        category: (
            [
                {
                    "key": "numbered|src/app/domains/demo/repository/part_1.py",
                    "owner": owner_for_domain("demo"),
                    "path": "src/app/domains/demo/repository/part_1.py",
                }
            ]
            if category == "numbered_modules"
            else []
        )
        for category in (
            "cross_domain_calls",
            "line_budgets",
            "model_registry",
            "mixin_duplicates",
            "numbered_modules",
        )
    }
    write_baseline(baseline, baseline_path)
    registered = load_baseline(baseline_path)
    _write(
        tmp_path, "src/app/domains/demo/repository/part_1.py", "class M:\n    pass\n"
    )
    assert_baseline_exact(
        "numbered_modules", scan_numbered_modules(tmp_path), registered
    )

    # 新增一个未登记的序号模块 → 检查失败
    _write(
        tmp_path, "src/app/domains/demo/repository/part_9.py", "class M:\n    pass\n"
    )
    with pytest.raises(AssertionError, match="new violations"):
        assert_baseline_exact(
            "numbered_modules", scan_numbered_modules(tmp_path), registered
        )

    # 文件还在但登记的例外被删掉 → 检查失败
    (tmp_path / "src/app/domains/demo/repository/part_9.py").unlink()
    registered["numbered_modules"] = []
    with pytest.raises(AssertionError, match="new violations"):
        assert_baseline_exact(
            "numbered_modules", scan_numbered_modules(tmp_path), registered
        )


def test_allowed_service_and_transaction_boundaries(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/app/domains/a/service.py",
        """
from app.domains.b import service as b_service


def call_b():
    return b_service.run()
""",
    )
    _write(
        tmp_path,
        "src/app/domains/a/repository.py",
        """
from app.domains.b import repository as b_repository
from app.domains.identity.models import PlexUser


class ARepository:
    def call_b(self, session):
        return b_repository.run_tx(session)
""",
    )
    _write(
        tmp_path,
        "src/app/domains/b/repository.py",
        """
class BRepository:
    def run_tx(self, session):
        return True
""",
    )
    assert scan_cross_domain_calls(tmp_path) == []


def test_baseline_requires_new_and_removed_entries_and_owner_changes() -> None:
    expected = {
        "cross_domain_calls": [{"key": "call|a", "owner": "promote-account-domains"}]
    }
    with pytest.raises(AssertionError, match="new violations"):
        assert_baseline_exact(
            "cross_domain_calls",
            expected["cross_domain_calls"]
            + [{"key": "call|b", "owner": "promote-blackjack-domain"}],
            expected,
        )
    with pytest.raises(AssertionError, match="stale violations"):
        assert_baseline_exact("cross_domain_calls", [], expected)
    with pytest.raises(AssertionError, match="owner changes"):
        assert_baseline_exact(
            "cross_domain_calls",
            [{"key": "call|a", "owner": "promote-blackjack-domain"}],
            expected,
        )


def test_duplicate_members_in_legacy_monolith_are_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/app/databases/db.py",
        """
class DatabaseORM:
    def duplicated(self):
        return 1

    def duplicated(self):
        return 2
""",
    )
    assert [entry["member"] for entry in scan_mixin_duplicates(tmp_path)] == [
        "duplicated"
    ]


def test_legacy_models_do_not_mask_missing_future_registry(tmp_path: Path) -> None:
    _write(tmp_path, "src/app/models/models.py", "class OldModel(Base):\n    pass\n")
    _write(
        tmp_path,
        "src/app/domains/identity/models.py",
        "class NewModel(Base):\n    pass\n",
    )
    assert [entry["key"] for entry in scan_model_registry(tmp_path)] == [
        "missing|app.model_registry"
    ]


def test_delayed_cross_domain_import_is_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/app/domains/a/jobs.py",
        "def run():\n    from app.domains.b.repository import run_tx\n    return run_tx(None)\n",
    )
    _write(
        tmp_path,
        "src/app/domains/b/repository.py",
        "def run_tx(session):\n    return None\n",
    )
    violations = scan_cross_domain_calls(tmp_path)
    assert {entry["kind"] for entry in violations} == {"import", "call"}


def test_allowed_model_constructor_import(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/app/domains/a/repository.py",
        "from app.domains.identity.models import PlexUser\n\n"
        "def create():\n    return PlexUser()\n",
    )
    assert scan_cross_domain_calls(tmp_path) == []


def test_app_package_does_not_merge_with_stale_installed_modules() -> None:
    import app

    assert [Path(path).resolve() for path in app.__path__] == [PROJECT_ROOT / "src/app"]


def test_import_contract_ignore_counts_are_frozen() -> None:
    import json
    import tomllib

    with (PROJECT_ROOT / "pyproject.toml").open("rb") as stream:
        contracts = tomllib.load(stream)["tool"]["importlinter"]["contracts"]
    frozen = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))[
        "contract_ignore_counts"
    ]
    assert frozen == {
        contract["name"]: len(contract.get("ignore_imports", []))
        for contract in contracts
    }
