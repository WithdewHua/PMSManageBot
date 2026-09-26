"""B2 architecture exceptions must be sourced from the frozen B1 implementation."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.refactor.audit_b2_baseline import (
    B2_BASE,
    audit,
    audit_added_violations,
    audit_import_contracts,
)
from tests.architecture.helpers import PROJECT_ROOT


@pytest.fixture(scope="module")
def b1_tree(tmp_path_factory: pytest.TempPathFactory):
    base = tmp_path_factory.mktemp("b2-provenance-base") / "base"
    # Git's commit hook sets GIT_INDEX_FILE=.git/index relative to the main
    # checkout; a linked worktree has a .git *file*, so that path is invalid.
    git_env = os.environ.copy()
    git_env.pop("GIT_INDEX_FILE", None)
    result = subprocess.run(
        ["git", "worktree", "add", "--detach", str(base), B2_BASE.read_text().strip()],
        cwd=PROJECT_ROOT,
        env=git_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    try:
        yield base
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(base)],
            cwd=PROJECT_ROOT,
            env=git_env,
            capture_output=True,
            text=True,
            check=True,
        )


def test_b2_baseline_and_ignore_edges_have_b1_provenance(b1_tree: Path) -> None:
    assert not audit(b1_tree, PROJECT_ROOT)
    baseline = json.loads(
        (PROJECT_ROOT / "tests/architecture/baseline.json").read_text(encoding="utf-8")
    )
    assert any("b2_source_id" in row for row in baseline["cross_domain_calls"])


def _fixture_trees(tmp_path: Path) -> tuple[Path, Path, Path]:
    base, current = tmp_path / "base", tmp_path / "current"
    source = base / "src/app/webapp/routers/user.py"
    target = current / "src/app/domains/accounts/router.py"
    source.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    source.write_text(
        "def route():\n"
        "    from app.domains.premium.service import existing\n"
        "    return existing()\n",
        encoding="utf-8",
    )
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    baseline = base / "tests/architecture/baseline.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(
        json.dumps({"cross_domain_calls": [], "line_budgets": []}), encoding="utf-8"
    )
    mapping = current / "scripts/refactor/mapping.toml"
    mapping.parent.mkdir(parents=True)
    mapping.write_text(
        '[[items]]\nid = "app.webapp.routers.user:route"\n'
        'target = "app.domains.accounts.router"\nkind = "function"\n'
        'reason = "reviewed original call"\n',
        encoding="utf-8",
    )
    return base, current, target


def test_relocated_call_accepted_but_new_call_rejected(tmp_path: Path) -> None:
    base, current, target = _fixture_trees(tmp_path)
    errors, proofs = audit_added_violations(base, current)
    assert not errors and proofs
    target.write_text(
        target.read_text().replace(
            "return existing()", "return existing() + existing()"
        )
    )
    errors, _ = audit_added_violations(base, current)
    assert any("new or changed call" in error for error in errors)


def test_new_over_budget_file_is_never_grandfathered(tmp_path: Path) -> None:
    base, current, target = _fixture_trees(tmp_path)
    target.write_text(target.read_text() + "\n".join("# legacy" for _ in range(1001)))
    errors, _ = audit_added_violations(base, current)
    assert any("new over-budget file" in error for error in errors)


def test_contract_audit_rejects_duplicate_and_unproven_ignore(tmp_path: Path) -> None:
    base, current, _ = _fixture_trees(tmp_path)
    for root, ignores in (
        (base, ""),
        (
            current,
            'ignore_imports = ["app.domains.accounts.router -> app.core.db", "app.domains.accounts.router -> app.core.db"]\n',
        ),
    ):
        (root / "pyproject.toml").write_text(
            "[tool.importlinter]\n"
            '[[tool.importlinter.contracts]]\nname = "Legacy database facade freeze"\n'
            'type = "protected"\nallowed_importers = []\n'
            '[[tool.importlinter.contracts]]\nname = "Database engine import scope"\n'
            f'type = "forbidden"\n{ignores}',
            encoding="utf-8",
        )
    errors = audit_import_contracts(base, current)
    assert any("duplicate ignore edge" in error for error in errors)
    assert any("unproven B2 import exception" in error for error in errors)


def test_forged_b1_source_id_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.refactor.audit_b2_baseline as provenance
    from tests.architecture.checks import scan_all

    base, current, _ = _fixture_trees(tmp_path)
    commit = "a" * 40
    base_file = current / "scripts/refactor/B2_BASE"
    base_file.write_text(commit + "\n", encoding="utf-8")
    records = scan_all(current)["cross_domain_calls"]
    assert records
    for record in records:
        record["b2_source_id"] = "app.webapp.routers.user:not_a_real_source"
    baseline = current / "tests/architecture/baseline.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(
        json.dumps({"b2_source_commit": commit, "cross_domain_calls": records}),
        encoding="utf-8",
    )
    monkeypatch.setattr(provenance, "audit_import_contracts", lambda *_: [])
    errors = provenance.audit(base, current)
    assert any("B2 baseline source ID missing or changed" in error for error in errors)


def test_changed_import_target_without_symbol_mapping_is_rejected(
    tmp_path: Path,
) -> None:
    base, current, target = _fixture_trees(tmp_path)
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "app.domains.premium.service", "app.domains.premium.models"
        ),
        encoding="utf-8",
    )
    errors, _ = audit_added_violations(base, current)
    assert any("unmapped B2 import target" in error for error in errors)


def test_contract_audit_rejects_wrong_clean_up_owner(tmp_path: Path) -> None:
    base, current, _ = _fixture_trees(tmp_path)
    for root, ignore in (
        (base, ""),
        (
            current,
            'ignore_imports = ["app.domains.accounts.router -> app.domains.premium.service"]\n',
        ),
    ):
        (root / "pyproject.toml").write_text(
            "[tool.importlinter]\n"
            '[[tool.importlinter.contracts]]\nname = "Legacy database facade freeze"\n'
            'type = "protected"\nallowed_importers = []\n'
            '[[tool.importlinter.contracts]]\nname = "Six-tier domain dependencies"\n'
            f'type = "forbidden"\n{ignore}',
            encoding="utf-8",
        )
    errors = audit_import_contracts(base, current)
    assert any("missing B2 exception owner" in error for error in errors)


def test_same_ordinal_module_import_cannot_change_target(tmp_path: Path) -> None:
    base, current, _ = _fixture_trees(tmp_path)
    old_import = "from app.domains.profile.schemas import CreditsTransferResponse\n"
    new_import = "from app.domains.reports.schemas import CreditsTransferResponse\n"
    source = base / "src/app/webapp/routers/user.py"
    target = current / "src/app/domains/accounts/router.py"
    source.write_text(old_import + source.read_text(encoding="utf-8"), encoding="utf-8")
    target.write_text(new_import + target.read_text(encoding="utf-8"), encoding="utf-8")
    errors, _ = audit_added_violations(base, current)
    assert any("import" in error for error in errors)


def test_new_protected_importer_in_other_contract_is_rejected(tmp_path: Path) -> None:
    base, current, _ = _fixture_trees(tmp_path)
    for root, allowed in ((base, ""), (current, '"app.domains.accounts.router"')):
        (root / "pyproject.toml").write_text(
            "[tool.importlinter]\n"
            '[[tool.importlinter.contracts]]\nname = "Legacy database facade freeze"\n'
            'type = "protected"\nallowed_importers = []\n'
            '[[tool.importlinter.contracts]]\nname = "SQLAlchemy direct use scope"\n'
            f'type = "protected"\nallowed_importers = [{allowed}]\n',
            encoding="utf-8",
        )
    errors = audit_import_contracts(base, current)
    assert any("unreviewed B2 allowed importer" in error for error in errors)


def test_frozen_b1_parent_matches_committed_source() -> None:
    from scripts.refactor.audit_b2_baseline import FROZEN_B2_PARENT

    assert B2_BASE.read_text().strip() == FROZEN_B2_PARENT
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert (
        result == FROZEN_B2_PARENT
        or subprocess.run(
            ["git", "merge-base", "--is-ancestor", FROZEN_B2_PARENT, "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def test_old_import_unused_by_moved_function_does_not_prove_new_edge(
    tmp_path: Path,
) -> None:
    base, current, target = _fixture_trees(tmp_path)
    source = base / "src/app/webapp/routers/user.py"
    source.write_text(
        "from app.databases import db\n\n"
        "def route():\n    return 1\n\n"
        "def unrelated():\n    return db.get_user_credits(1)\n",
        encoding="utf-8",
    )
    target.write_text("from app.databases import db\n\ndef route():\n    return 1\n")
    for root, edge in (
        (base, ""),
        (
            current,
            '"app.domains.accounts.router -> app.databases.db", # promote-account-domains (B2 inherited)',
        ),
    ):
        (root / "pyproject.toml").write_text(
            "[tool.importlinter]\n"
            '[[tool.importlinter.contracts]]\nname = "Legacy database facade freeze"\n'
            'type = "protected"\nallowed_importers = []\n'
            '[[tool.importlinter.contracts]]\nname = "Domain entry points do not touch data layer"\n'
            f'type = "forbidden"\nignore_imports = [\n  {edge}\n]\n',
            encoding="utf-8",
        )
    errors = audit_import_contracts(base, current)
    assert any("unproven B2 import exception" in error for error in errors)


def test_same_named_imported_call_cannot_switch_domain(tmp_path: Path) -> None:
    base, current, target = _fixture_trees(tmp_path)
    source = base / "src/app/webapp/routers/user.py"
    source.write_text(
        "from app.domains.profile.schemas import CreditsTransferResponse\n\n"
        "def route():\n    return CreditsTransferResponse()\n",
        encoding="utf-8",
    )
    target.write_text(
        "from app.domains.reports.schemas import CreditsTransferResponse\n\n"
        "def route():\n    return CreditsTransferResponse()\n",
        encoding="utf-8",
    )
    errors, _ = audit_added_violations(base, current)
    assert any("changed imported call binding" in error for error in errors)
