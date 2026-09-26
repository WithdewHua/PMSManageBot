"""B3 orchestration and utility relocation mappings must be reviewed."""

import ast
import subprocess
import tomllib
from collections import defaultdict
from pathlib import Path

from scripts.refactor.inventory import ROOT, coverage, inventory
from scripts.refactor.relocate import _nodes_by_unit, _references

MAPPING = ROOT / "scripts/refactor/mapping.toml"
B3_BASE = (ROOT / "scripts/refactor/B3_BASE").read_text().strip()
B3_SOURCES = (
    "databases/db_func.py",
    "premium.py",
    "modules/custom_line.py",
    "utils/report.py",
    "utils/utils.py",
)


def _frozen_b3_sources(tmp_path: Path) -> tuple[Path, list[Path]]:
    frozen_root = tmp_path / "b3-base"
    paths: list[Path] = []
    for name in B3_SOURCES:
        destination = frozen_root / "src/app" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "show", f"{B3_BASE}:src/app/{name}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        destination.write_text(result.stdout, encoding="utf-8")
        paths.append(destination)
    return frozen_root, paths


def test_b3_orchestration_mapping_has_no_todo(tmp_path: Path) -> None:
    frozen_root, paths = _frozen_b3_sources(tmp_path)
    items = inventory(paths, root=frozen_root)
    result = coverage(items, MAPPING)
    assert result["missing"] == []
    # The global mapping also retains B1 source IDs for BASE AST equivalence;
    # those IDs no longer exist in the current compatibility modules.
    assert result["invalid"] == []
    assert result["todo"] == []


def test_b3_utility_owners_follow_design_d9() -> None:
    with MAPPING.open("rb") as stream:
        records = {row["id"]: row for row in tomllib.load(stream)["items"]}
    expected = {
        "get_user_total_duration": "app.integrations.tautulli",
        "caculate_credits_fund": "app.domains.media_access.rules",
        "refresh_tg_user_info": "app.domains.accounts.service",
        "refresh_emby_user_info": "app.domains.accounts.jobs",
        "normalize_line_domain": "app.domains.lines.rules",
    }
    for name, target in expected.items():
        assert records[f"app.utils.utils:{name}"]["target"] == target


def test_b3_manual_entry_points_are_not_discarded() -> None:
    with MAPPING.open("rb") as stream:
        records = {row["id"]: row for row in tomllib.load(stream)["items"]}
    for source in ("app.databases.db_func", "app.utils.report"):
        guard = records[f"{source}:@statement:1"]
        assert guard["target"] == "app.manage"
        assert guard["action"] in {"assemble", "manual"}
        assert "manual CLI guard" in guard["reason"]
    assert records["app.modules.custom_line:@import:10"]["target"] != "TODO"
    assert records["app.databases.db_func:@import:28"]["target"] != "TODO"


def test_b3_reviewed_import_splits_match_actual_uses(tmp_path: Path) -> None:
    with MAPPING.open("rb") as stream:
        records = {row["id"]: row for row in tomllib.load(stream)["items"]}
    frozen_root, paths = _frozen_b3_sources(tmp_path)
    for path in paths[:1] + paths[2:4]:
        items = inventory([path], root=frozen_root)
        nodes = _nodes_by_unit(path, items)
        consumers: dict[str, set[str]] = defaultdict(set)
        for item in items:
            if item.parent_id is not None or item.kind in {"import", "package_import"}:
                continue
            for binding in _references(nodes[item.unit_id]):
                consumers[binding].add(records[item.id]["target"])
        for item in items:
            if item.kind != "import":
                continue
            node = nodes[item.unit_id]
            bindings = {
                alias.asname
                or (
                    alias.name.split(".")[0]
                    if isinstance(node, ast.Import)
                    else alias.name
                )
                for alias in node.names
            }
            used = {
                binding: sorted(consumers[binding])
                for binding in bindings
                if consumers[binding]
            }
            destinations = sorted(
                {target for targets in used.values() for target in targets}
            )
            record = records[item.id]
            assert destinations, item.id
            assert record["target"] in destinations, item.id
            assert record.get("split_targets", []) == (
                destinations if len(destinations) > 1 else []
            ), item.id
            assert record.get("split_bindings", {}) == (
                used if len(used) > 1 else {}
            ), item.id
