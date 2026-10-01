"""Tests for openspec/changes/retire-legacy-db-facade/prerequisite_audit.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).parent / "prerequisite_audit.py"
_spec = importlib.util.spec_from_file_location("prerequisite_audit", _SCRIPT_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["prerequisite_audit"] = _mod
_spec.loader.exec_module(_mod)

audit_baseline = _mod.audit_baseline
audit_compat_and_scripts = _mod.audit_compat_and_scripts
audit_import_linter = _mod.audit_import_linter
audit_src_databases_imports = _mod.audit_src_databases_imports
get_repo_root = _mod.get_repo_root
render_markdown = _mod.render_markdown
run_full_audit = _mod.run_full_audit


@pytest.fixture
def repo_root() -> Path:
    return get_repo_root()


def test_audit_baseline(repo_root: Path) -> None:
    res = audit_baseline(repo_root)
    assert isinstance(res, dict)
    assert res["passed"] is True  # Only facade counts remain in mirror metadata.
    assert res["violations_count"] == 0
    assert "cross_domain_calls" in res["categories"]
    assert res["categories"]["cross_domain_calls"]["count"] == 0
    assert res["categories"]["line_budgets"]["status"] == "exempt"
    assert res["categories"]["model_registry"]["status"] == "clean"
    assert res["categories"]["config_access"]["status"] == "clean"
    assert res["categories"]["numbered_modules"]["status"] == "clean"


def test_audit_import_linter(repo_root: Path) -> None:
    res = audit_import_linter(repo_root)
    assert isinstance(res, dict)
    assert res["passed"] is True  # Only the four facade composition edges remain.
    assert res["facade_composition_count"] == 4  # 2 in Six-tier + 2 in Acyclic
    assert res["non_facade_legacy_count"] == 0
    assert len(res["facade_freeze_allowed_importers"]) == 10


def test_audit_src_databases_imports(repo_root: Path) -> None:
    res = audit_src_databases_imports(repo_root)
    assert isinstance(res, dict)
    assert res["passed"] is True  # Only app.databases itself imports app.databases
    assert len(res["ast_external_imports"]) == 0
    assert len(res["ast_internal_imports"]) >= 1
    assert res["grimp_downstream_databases"] == []
    assert res["grimp_downstream_db"] == ["app.databases"]


def test_audit_compat_and_scripts(repo_root: Path) -> None:
    res = audit_compat_and_scripts(repo_root)
    assert isinstance(res, dict)
    assert "IdentityRepository" in res["composed_mixins"]
    assert "LinesCompat" in res["composed_mixins"]
    assert res["identity_compat_methods_count"] == 15
    assert res["db_calls_src_count"] == 0
    assert res["db_calls_scripts_count"] == 0
    script_paths = [s["path"] for s in res["scripts_databases_imports"]]
    assert script_paths == ["scripts/refactor/snapshot.py"]
    assert len(res["tests_databases_imports"]) == 6
    assert any("conftest.py" in p["path"] for p in res["tests_databases_imports"])


def test_run_full_audit(repo_root: Path) -> None:
    data = run_full_audit(repo_root)
    assert data["change"] == "retire-legacy-db-facade"
    assert data["all_prerequisites_passed"] is True
    assert data["gate_verdict"] == "PASS"
    assert data["summary"]["check_1_baseline_clean"] is True
    assert data["summary"]["check_2_only_facade_ignores"] is True
    assert data["summary"]["check_3_src_databases_clean"] is True
    assert data["responsible_changes_summary"] == {}

    md = render_markdown(data)
    assert "PASSED" in md
    assert "cross_domain_calls" in md
