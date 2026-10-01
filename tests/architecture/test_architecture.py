"""Focused tests for the repository architecture scanners."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from .checks import (
    scan_all,
    scan_config_access,
    scan_credit_writes,
    scan_cross_domain_calls,
    scan_line_budgets,
    scan_model_registry,
    scan_numbered_modules,
)
from .helpers import (
    BASELINE_PATH,
    PROJECT_ROOT,
    assert_baseline_exact,
    load_baseline,
    write_baseline,
)


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_config_access_allows_reads_and_owner_writes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/app/domains/accounts/service.py",
        "from app.domains.invitation import config as invitation_config\n"
        "def read(): return invitation_config.INVITATION_CONFIG.get()\n"
        "def write(): return invitation_config.INVITATION_CONFIG.update(invitation_credits=1)\n",
    )
    _write(
        tmp_path,
        "src/app/domains/accounts/rules.py",
        "from app.domains.invitation import config as invitation_config\n"
        "def read(): return invitation_config.INVITATION_CONFIG.get()\n",
    )
    _write(
        tmp_path,
        "src/app/integrations/client.py",
        "from app.domains.invitation import config as invitation_config\n"
        "def read(): return invitation_config.INVITATION_CONFIG.get()\n",
    )
    violations = scan_config_access(tmp_path)
    assert len(violations) == 3
    assert {item["source_role"] for item in violations} == {
        "service",
        "rules",
        "integrations",
    }


def test_current_layout_matches_the_architecture_baseline() -> None:
    baseline = load_baseline(BASELINE_PATH)
    actual = scan_all(PROJECT_ROOT)

    assert_baseline_exact("line_budgets", actual["line_budgets"], baseline)
    assert actual["cross_domain_calls"] == []
    assert actual["config_access"] == []
    assert actual["model_registry"] == []
    assert actual["numbered_modules"] == []
    assert actual["credit_writes"] == []


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
    _write(tmp_path, "src/app/domains/demo/service.py", "\n" * 1001)
    actual = scan_line_budgets(tmp_path)
    baseline = {
        "line_budgets": [
            {
                "key": "src/app/domains/demo/service.py",
                "owner": "restructure-backend-architecture",
                "path": "src/app/domains/demo/service.py",
                "lines": 1001,
                "budget": 1000,
            }
        ]
    }
    assert_baseline_exact("line_budgets", actual, baseline)

    _write(tmp_path, "src/app/domains/demo/service.py", "\n" * 1002)
    with pytest.raises(AssertionError, match="line counts changed"):
        assert_baseline_exact("line_budgets", scan_line_budgets(tmp_path), baseline)


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


def test_baseline_writer_round_trips_without_refreshing_repository_baseline(
    tmp_path: Path,
) -> None:
    baseline = {
        "line_budgets": [],
    }
    path = tmp_path / "baseline.json"
    write_baseline(baseline, path)
    assert load_baseline(path) == baseline
    assert BASELINE_PATH.exists()


def test_numbered_repository_modules_are_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path, "src/app/domains/demo/repository/part_1.py", "class M:\n    pass\n"
    )
    violations = scan_numbered_modules(tmp_path)
    assert len(violations) == 1
    assert violations[0]["path"] == "src/app/domains/demo/repository/part_1.py"


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
        "line_budgets": [
            {
                "key": "src/app/a.py",
                "owner": "restructure-backend-architecture",
                "lines": 1001,
            }
        ]
    }
    with pytest.raises(AssertionError, match="new violations"):
        assert_baseline_exact(
            "line_budgets",
            expected["line_budgets"]
            + [
                {
                    "key": "src/app/b.py",
                    "owner": "promote-blackjack-domain",
                    "lines": 1002,
                }
            ],
            expected,
        )
    with pytest.raises(AssertionError, match="stale violations"):
        assert_baseline_exact("line_budgets", [], expected)
    with pytest.raises(AssertionError, match="owner changes"):
        assert_baseline_exact(
            "line_budgets",
            [
                {
                    "key": "src/app/a.py",
                    "owner": "promote-blackjack-domain",
                    "lines": 1001,
                }
            ],
            expected,
        )


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


def test_all_import_linter_contracts_have_no_ignore_imports() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as stream:
        contracts = tomllib.load(stream)["tool"]["importlinter"]["contracts"]
    for contract in contracts:
        assert contract.get("ignore_imports", []) == [], (
            f"Contract '{contract['name']}' has ignore_imports: {contract.get('ignore_imports')}"
        )


def test_six_tier_contract_rejects_unclassified_domain() -> None:
    import shutil

    with (PROJECT_ROOT / "pyproject.toml").open("rb") as stream:
        contracts = tomllib.load(stream)["tool"]["importlinter"]["contracts"]
    six_tier = next(c for c in contracts if c["name"] == "Six-tier domain dependencies")
    assert six_tier.get("exhaustive") is True

    lint_cmd = Path(sys.executable).parent / "lint-imports"
    if not lint_cmd.exists():
        lint_cmd = Path(
            shutil.which("lint-imports") or (PROJECT_ROOT / ".venv/bin/lint-imports")
        )

    probe_dir = PROJECT_ROOT / "src/app/domains/_probe_unclassified_domain"
    probe_dir.mkdir(parents=True, exist_ok=True)
    (probe_dir / "__init__.py").write_text("", encoding="utf-8")
    try:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        result = subprocess.run(
            [str(lint_cmd), "--no-cache"],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "app.domains._probe_unclassified_domain" in result.stdout
    finally:
        if probe_dir.exists():
            shutil.rmtree(probe_dir)


def test_credit_absolute_write_is_rejected(tmp_path: Path) -> None:
    # 1. 属性赋值
    p1 = tmp_path / "case1"
    _write(
        p1,
        "src/app/domains/demo/service.py",
        "def change(stats):\n    stats.credits = 100.0\n",
    )
    violations = scan_credit_writes(p1)
    assert len(violations) == 1
    assert violations[0]["kind"] == "attribute-assignment"
    assert violations[0]["target"] == "stats.credits"

    # 2. 增强赋值
    p2 = tmp_path / "case2"
    _write(
        p2,
        "src/app/domains/demo/service.py",
        "def change(stats):\n    stats.emby_credits += 10.0\n",
    )
    violations = scan_credit_writes(p2)
    assert len(violations) == 1
    assert violations[0]["kind"] == "attribute-augmented-assignment"
    assert violations[0]["target"] == "stats.emby_credits"

    # 3. 门面绝对值调用
    p3 = tmp_path / "case3"
    _write(
        p3,
        "src/app/domains/demo/service.py",
        "def change(db):\n    db.update_user_credits(1, 100)\n",
    )
    violations = scan_credit_writes(p3)
    assert len(violations) == 1
    assert violations[0]["kind"] == "absolute-facade-call"

    # 4. SQL values 写入
    p4 = tmp_path / "case4"
    _write(
        p4,
        "src/app/domains/demo/repository.py",
        "def update_sql(session):\n    session.execute(update(Table).values(credits=50))\n",
    )
    violations = scan_credit_writes(p4)
    assert len(violations) == 1
    assert violations[0]["kind"] == "sql-values-write"
