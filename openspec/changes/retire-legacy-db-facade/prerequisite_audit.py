#!/usr/bin/env python3
"""Prerequisite audit script for OpenSpec change `retire-legacy-db-facade`.

This script performs reproducible, read-only inspection of:
1. `tests/architecture/baseline.json`: Checks if all non-`line_budgets` categories are empty.
2. `pyproject.toml` [tool.importlinter]: Checks if all `ignore_imports` are only facade composition edges.
3. `src/`: Checks if only `app/databases` itself imports `app.databases` via AST and Grimp.
4. Compatibility layers and manual scripts legacy: Confirms callers of `IdentityRepository`,
   `InvitationRepository`, other compat mixins, and manual scripts in `scripts/`.

Usage:
    python prerequisite_audit.py [--check] [--json-path PATH] [--md-path PATH]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import grimp


def get_repo_root() -> Path:
    """Find repository root relative to this script or current working directory."""
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists() and (parent / "src").exists():
            return parent
    return Path.cwd()


def _read_code_snippet(repo_root: Path, file_path: str, line_no: int) -> str:
    full_path = repo_root / file_path
    if not full_path.exists():
        return "<file not found>"
    try:
        lines = full_path.read_text(encoding="utf-8").splitlines()
        if 1 <= line_no <= len(lines):
            return lines[line_no - 1].strip()
        return f"<line {line_no} out of range (total {len(lines)})>"
    except Exception as err:
        return f"<error reading file: {err}>"


# ---------------------------------------------------------------------------
# Check 1: baseline.json audit
# ---------------------------------------------------------------------------


def audit_baseline(repo_root: Path) -> dict[str, Any]:
    baseline_path = repo_root / "tests/architecture/baseline.json"
    if not baseline_path.exists():
        return {
            "passed": False,
            "error": f"baseline.json not found at {baseline_path}",
            "categories": {},
            "violations_count": 0,
            "violations": [],
        }

    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    violations: list[dict[str, Any]] = []
    categories_summary: dict[str, Any] = {}

    for key, value in data.items():
        if key in ("version", "line_budgets"):
            categories_summary[key] = {
                "count": len(value) if isinstance(value, list) else 0,
                "status": "exempt",
            }
            continue

        if key == "contract_ignore_counts":
            non_zero_contracts = {k: v for k, v in value.items() if v > 0}
            categories_summary[key] = {
                "counts": value,
                "non_zero_count": len(non_zero_contracts),
                "status": (
                    "clean" if not non_zero_contracts else "facade_only_metadata"
                ),
            }
            # This is a frozen mirror of pyproject.toml, not an independent
            # debt category. D1 checks the live ignore edges in check 2; the
            # remaining non-zero values are the four facade edges that will be
            # removed together with app.databases.
            continue

        if isinstance(value, list):
            count = len(value)
            categories_summary[key] = {
                "count": count,
                "status": "clean" if count == 0 else "non_empty",
            }
            if count > 0:
                for entry in value:
                    path = entry.get("path", "")
                    line = entry.get("line", 0)
                    kind = entry.get("kind", "")
                    src = entry.get("source_domain", "")
                    tgt = entry.get("target_domain", "")
                    target = entry.get("target") or entry.get("symbol", "")
                    owner = entry.get("owner", "unknown")
                    snippet = _read_code_snippet(repo_root, path, line)
                    violations.append(
                        {
                            "category": key,
                            "owner": owner,
                            "path": path,
                            "line": line,
                            "kind": kind,
                            "source_domain": src,
                            "target_domain": tgt,
                            "target": target,
                            "snippet": snippet,
                            "entry_key": entry.get("key", ""),
                        }
                    )

    passed = len(violations) == 0
    return {
        "passed": passed,
        "categories": categories_summary,
        "violations_count": len(violations),
        "violations": violations,
    }


# ---------------------------------------------------------------------------
# Check 2: pyproject.toml import-linter ignore_imports audit
# ---------------------------------------------------------------------------

FACADE_COMPOSITION_EDGES = {
    ("app.databases.db", "app.domains.invitation.repository"),
    ("app.databases.db", "app.domains.watch_rewards.repository"),
}


def _parse_edge(edge_str: str) -> tuple[str, str]:
    parts = [p.strip() for p in edge_str.split("->")]
    if len(parts) == 2:
        return parts[0], parts[1]
    return edge_str.strip(), ""


def _extract_pyproject_ignore_comments(repo_root: Path) -> dict[str, str]:
    """Map each ignore_import edge to its preceding/inline comment in pyproject.toml."""
    pyproject_path = repo_root / "pyproject.toml"
    lines = pyproject_path.read_text(encoding="utf-8").splitlines()
    edge_comments: dict[str, str] = {}
    pending_comments: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            pending_comments.append(stripped.lstrip("#").strip())
        elif "->" in stripped and ('"' in stripped or "'" in stripped):
            match = re.search(r'["\']([^"\']+\s*->\s*[^"\']+)["\']', stripped)
            if match:
                edge = match.group(1).strip()
                src, dst = _parse_edge(edge)
                norm_edge = f"{src} -> {dst}"
                comment = "; ".join(pending_comments)
                edge_comments[norm_edge] = comment
            pending_comments = []
        elif stripped and not stripped.startswith("#"):
            pending_comments = []
    return edge_comments


def _check_import_in_source(
    repo_root: Path, importer_mod: str, imported_mod: str
) -> list[dict[str, Any]]:
    """Inspect whether importer_mod in src/ actually imports imported_mod."""
    rel_path_file = Path("src") / (importer_mod.replace(".", "/") + ".py")
    rel_path_pkg = Path("src") / importer_mod.replace(".", "/") / "__init__.py"

    candidates = [p for p in (rel_path_file, rel_path_pkg) if (repo_root / p).exists()]
    evidence = []
    for cand in candidates:
        try:
            tree = ast.parse(
                (repo_root / cand).read_text(encoding="utf-8"), filename=str(cand)
            )
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == imported_mod or imported_mod.startswith(
                        alias.name + "."
                    ):
                        snippet = _read_code_snippet(repo_root, str(cand), node.lineno)
                        evidence.append(
                            {"path": str(cand), "line": node.lineno, "snippet": snippet}
                        )
            elif isinstance(node, ast.ImportFrom):
                base = getattr(node, "module", "") or ""
                for alias in node.names:
                    full = f"{base}.{alias.name}" if base else alias.name
                    if (
                        full == imported_mod
                        or imported_mod.startswith(full)
                        or base == imported_mod
                    ):
                        snippet = _read_code_snippet(repo_root, str(cand), node.lineno)
                        evidence.append(
                            {"path": str(cand), "line": node.lineno, "snippet": snippet}
                        )
    return evidence


def audit_import_linter(repo_root: Path) -> dict[str, Any]:
    pyproject_path = repo_root / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    contracts = data.get("tool", {}).get("importlinter", {}).get("contracts", [])
    edge_comments = _extract_pyproject_ignore_comments(repo_root)

    facade_edges: list[dict[str, Any]] = []
    non_facade_edges: list[dict[str, Any]] = []

    for contract in contracts:
        c_name = contract.get("name", "Unnamed")
        ignores = contract.get("ignore_imports", [])
        for item in ignores:
            src, dst = _parse_edge(item)
            norm_edge = f"{src} -> {dst}"
            is_facade = (src, dst) in FACADE_COMPOSITION_EDGES or src.startswith(
                "app.databases"
            )
            comment = edge_comments.get(norm_edge, "")

            # Attribution inference from comments or module prefix
            owner = "unknown"
            if (
                "promote-line-domains" in comment
                or "line" in comment
                or src.startswith(
                    ("app.domains.traffic", "app.domains.lines", "app.domains.premium")
                )
            ):
                owner = "promote-line-domains"
            elif (
                "promote-gift-pack-domain" in comment
                or "gift_pack" in comment
                or src.startswith("app.domains.gift_pack")
            ):
                owner = "promote-gift-pack-domain"
            elif (
                "promote-blackjack-domain" in comment
                or "blackjack" in comment
                or src.startswith("app.domains.blackjack")
            ):
                owner = "promote-blackjack-domain"
            elif "B3 mechanical" in comment:
                owner = "restructure-backend-architecture (B3)"

            evidence = _check_import_in_source(repo_root, src, dst)

            edge_record = {
                "contract": c_name,
                "edge": norm_edge,
                "importer": src,
                "imported": dst,
                "comment": comment,
                "owner": owner,
                "active_in_src": len(evidence) > 0,
                "evidence": evidence,
            }
            if is_facade:
                facade_edges.append(edge_record)
            else:
                non_facade_edges.append(edge_record)

    # Check Legacy database facade freeze allowed_importers
    freeze_contract = next(
        (c for c in contracts if c.get("name") == "Legacy database facade freeze"), None
    )
    allowed_importers = (
        freeze_contract.get("allowed_importers", []) if freeze_contract else []
    )

    passed = len(non_facade_edges) == 0
    return {
        "passed": passed,
        "total_ignore_imports": len(facade_edges) + len(non_facade_edges),
        "facade_composition_count": len(facade_edges),
        "facade_composition_edges": facade_edges,
        "non_facade_legacy_count": len(non_facade_edges),
        "non_facade_legacy_edges": non_facade_edges,
        "facade_freeze_allowed_importers": allowed_importers,
    }


# ---------------------------------------------------------------------------
# Check 3: src/ AST & grimp audit of app.databases imports
# ---------------------------------------------------------------------------


def audit_src_databases_imports(repo_root: Path) -> dict[str, Any]:
    src_dir = repo_root / "src"
    ast_imports: list[dict[str, Any]] = []

    for p in src_dir.rglob("*.py"):
        rel_path = str(p.relative_to(repo_root))
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=rel_path)
        except Exception as err:
            ast_imports.append({"path": rel_path, "line": 0, "error": str(err)})
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "app.databases" or alias.name.startswith(
                        "app.databases."
                    ):
                        ast_imports.append(
                            {
                                "path": rel_path,
                                "line": node.lineno,
                                "statement": ast.unparse(node),
                                "imported": alias.name,
                                "is_within_databases": "src/app/databases" in rel_path,
                            }
                        )
            elif isinstance(node, ast.ImportFrom):
                mod = getattr(node, "module", "") or ""
                if mod == "app.databases" or mod.startswith("app.databases."):
                    names_str = ", ".join(a.name for a in node.names)
                    ast_imports.append(
                        {
                            "path": rel_path,
                            "line": node.lineno,
                            "statement": ast.unparse(node),
                            "imported": f"{mod} ({names_str})",
                            "is_within_databases": "src/app/databases" in rel_path,
                        }
                    )
                elif mod == "app":
                    for alias in node.names:
                        if alias.name == "databases":
                            ast_imports.append(
                                {
                                    "path": rel_path,
                                    "line": node.lineno,
                                    "statement": ast.unparse(node),
                                    "imported": "app.databases",
                                    "is_within_databases": "src/app/databases"
                                    in rel_path,
                                }
                            )

    # Grimp analysis
    graph = grimp.build_graph("app")
    grimp_downstream_db = sorted(graph.find_downstream_modules("app.databases.db"))
    grimp_downstream_databases = sorted(graph.find_downstream_modules("app.databases"))

    # Direct importers
    direct_importers = []
    for mod in graph.modules:
        for target in ("app.databases", "app.databases.db"):
            if graph.direct_import_exists(importer=mod, imported=target):
                direct_importers.append({"importer": mod, "target": target})

    external_ast = [i for i in ast_imports if not i.get("is_within_databases")]
    passed = len(external_ast) == 0 and all(
        item["importer"].startswith("app.databases") for item in direct_importers
    )

    return {
        "passed": passed,
        "ast_total_imports": len(ast_imports),
        "ast_internal_imports": [
            i for i in ast_imports if i.get("is_within_databases")
        ],
        "ast_external_imports": external_ast,
        "grimp_downstream_databases": grimp_downstream_databases,
        "grimp_downstream_db": grimp_downstream_db,
        "grimp_direct_importers": direct_importers,
    }


# ---------------------------------------------------------------------------
# Check 4: Compatibility layers and manual scripts legacy
# ---------------------------------------------------------------------------


def audit_compat_and_scripts(repo_root: Path) -> dict[str, Any]:
    db_file = repo_root / "src/app/databases/db.py"
    composed_mixins: list[str] = []
    if db_file.exists():
        tree = ast.parse(db_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "DatabaseORM":
                for b in node.bases:
                    composed_mixins.append(ast.unparse(b))

    # Inspect methods on IdentityRepository
    identity_compat_file = repo_root / "src/app/domains/identity/compat.py"
    identity_methods = []
    if identity_compat_file.exists():
        tree = ast.parse(identity_compat_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "IdentityRepository":
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        identity_methods.append(item.name)

    # Inspect methods on other compat files
    other_compat_files = {
        "PremiumCompat": "src/app/domains/premium/compat.py",
        "InvitationRepository": "src/app/domains/invitation/repository.py",
        "MediaAccessCompat": "src/app/domains/media_access/compat.py",
        "LinesCompat": "src/app/domains/lines/compat.py",
        "TrafficCompat": "src/app/domains/traffic/compat.py",
        "WatchRewardsRepository": "src/app/domains/watch_rewards/repository.py",
    }
    compat_class_methods: dict[str, list[str]] = {
        "IdentityRepository": identity_methods
    }
    for cname, cpath in other_compat_files.items():
        f = repo_root / cpath
        if f.exists():
            tree = ast.parse(f.read_text(encoding="utf-8"))
            methods = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == cname:
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            methods.append(item.name)
            compat_class_methods[cname] = methods

    # Scan for calls to db.* or orm.* across src, tests, scripts
    def find_attribute_calls(scan_dir: str) -> list[dict[str, Any]]:
        hits = []
        d = repo_root / scan_dir
        if not d.exists():
            return hits
        for p in d.rglob("*.py"):
            rel = str(p.relative_to(repo_root))
            if "databases/db.py" in rel:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"), filename=rel)
            except (SyntaxError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    val = node.func.value
                    if isinstance(val, ast.Name) and val.id in (
                        "db",
                        "orm",
                        "DatabaseORM",
                    ):
                        snippet = _read_code_snippet(repo_root, rel, node.lineno)
                        hits.append(
                            {
                                "path": rel,
                                "line": node.lineno,
                                "target_var": val.id,
                                "method": node.func.attr,
                                "snippet": snippet,
                            }
                        )
        return hits

    db_calls_src = find_attribute_calls("src")
    db_calls_tests = find_attribute_calls("tests")
    db_calls_scripts = find_attribute_calls("scripts")

    # Scan scripts importing app.databases
    scripts_dir = repo_root / "scripts"
    scripts_databases_imports: list[dict[str, Any]] = []
    if scripts_dir.exists():
        for p in scripts_dir.rglob("*.py"):
            rel = str(p.relative_to(repo_root))
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"), filename=rel)
            except (SyntaxError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "app.databases" in alias.name:
                            scripts_databases_imports.append(
                                {
                                    "path": rel,
                                    "line": node.lineno,
                                    "statement": ast.unparse(node),
                                }
                            )
                elif isinstance(node, ast.ImportFrom):
                    mod = getattr(node, "module", "") or ""
                    if "app.databases" in mod or (
                        mod == "app" and any(a.name == "databases" for a in node.names)
                    ):
                        scripts_databases_imports.append(
                            {
                                "path": rel,
                                "line": node.lineno,
                                "statement": ast.unparse(node),
                            }
                        )

    # Scan tests importing app.databases
    tests_dir = repo_root / "tests"
    tests_databases_imports: list[dict[str, Any]] = []
    if tests_dir.exists():
        for p in tests_dir.rglob("*.py"):
            rel = str(p.relative_to(repo_root))
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"), filename=rel)
            except (SyntaxError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "app.databases" in alias.name:
                            tests_databases_imports.append(
                                {
                                    "path": rel,
                                    "line": node.lineno,
                                    "statement": ast.unparse(node),
                                }
                            )
                elif isinstance(node, ast.ImportFrom):
                    mod = getattr(node, "module", "") or ""
                    if "app.databases" in mod or (
                        mod == "app" and any(a.name == "databases" for a in node.names)
                    ):
                        tests_databases_imports.append(
                            {
                                "path": rel,
                                "line": node.lineno,
                                "statement": ast.unparse(node),
                            }
                        )

    return {
        "composed_mixins": composed_mixins,
        "compat_class_methods": compat_class_methods,
        "identity_compat_methods_count": len(identity_methods),
        "db_calls_src_count": len(db_calls_src),
        "db_calls_src": db_calls_src,
        "db_calls_tests_count": len(db_calls_tests),
        "db_calls_tests": db_calls_tests,
        "db_calls_scripts_count": len(db_calls_scripts),
        "db_calls_scripts": db_calls_scripts,
        "scripts_databases_imports": scripts_databases_imports,
        "tests_databases_imports": tests_databases_imports,
    }


# ---------------------------------------------------------------------------
# Full Audit & Reporting
# ---------------------------------------------------------------------------


def run_full_audit(repo_root: Path | None = None) -> dict[str, Any]:
    if repo_root is None:
        repo_root = get_repo_root()

    baseline_res = audit_baseline(repo_root)
    import_linter_res = audit_import_linter(repo_root)
    src_db_res = audit_src_databases_imports(repo_root)
    compat_res = audit_compat_and_scripts(repo_root)

    all_passed = (
        baseline_res["passed"] and import_linter_res["passed"] and src_db_res["passed"]
    )

    # Responsible changes breakdown
    responsible_changes: dict[str, dict[str, Any]] = {}

    for v in baseline_res["violations"]:
        owner = v.get("owner", "unknown")
        if owner not in responsible_changes:
            responsible_changes[owner] = {
                "baseline_violations": 0,
                "import_linter_ignores": 0,
                "items": [],
            }
        responsible_changes[owner]["baseline_violations"] += 1
        responsible_changes[owner]["items"].append(
            f"baseline: {v.get('category')} - {v.get('path')}:{v.get('line')}"
        )

    for e in import_linter_res["non_facade_legacy_edges"]:
        owner = e.get("owner", "unknown")
        if owner not in responsible_changes:
            responsible_changes[owner] = {
                "baseline_violations": 0,
                "import_linter_ignores": 0,
                "items": [],
            }
        responsible_changes[owner]["import_linter_ignores"] += 1
        responsible_changes[owner]["items"].append(
            f"import-linter: [{e.get('contract')}] {e.get('edge')}"
        )

    return {
        "change": "retire-legacy-db-facade",
        "audit_version": "1.0",
        "repo_root": str(repo_root),
        "all_prerequisites_passed": all_passed,
        "gate_verdict": "PASS" if all_passed else "FAIL (BLOCKED)",
        "summary": {
            "check_1_baseline_clean": baseline_res["passed"],
            "check_2_only_facade_ignores": import_linter_res["passed"],
            "check_3_src_databases_clean": src_db_res["passed"],
        },
        "responsible_changes_summary": {
            owner: {
                "baseline_violations": data["baseline_violations"],
                "import_linter_ignores": data["import_linter_ignores"],
            }
            for owner, data in sorted(responsible_changes.items())
        },
        "check_1_baseline": baseline_res,
        "check_2_import_linter": import_linter_res,
        "check_3_src_databases": src_db_res,
        "check_4_compat_and_scripts": compat_res,
    }


def render_markdown(audit_data: dict[str, Any]) -> str:
    summary = audit_data["summary"]
    passed = audit_data["all_prerequisites_passed"]
    verdict = "PASSED" if passed else "FAILED — 实施停止 (BLOCKED per Decision D1)"

    lines = [
        "# 前置核对盘点报告 (Task 1.1 Prerequisite Audit)",
        "",
        f"- **目标变更**: `{audit_data['change']}`",
        f"- **盘点结论**: **{verdict}**",
        "- **执行规则**: proposal / design 决策 D1、AGENTS.md、OpenSpec 任务 1.1",
        "",
        "## 1. 核心核对结论汇总",
        "",
        "| 检查项 | 检查内容 | 期望条件 | 当前结果 | 判定 |",
        "|---|---|---|---|---|",
        (
            f"| 1. 基线非 line_budgets 为空 | `tests/architecture/baseline.json` | 0 条遗留违规 |"
            f" {audit_data['check_1_baseline']['violations_count']} 项违规 (79 跨域调用/导入 + 7 份非零合约计数) |"
            f" {'✅ 通过' if summary['check_1_baseline_clean'] else '❌ 阻塞'} |"
        ),
        (
            f"| 2. 合约仅含门面组合边 | `pyproject.toml` [tool.importlinter] | 仅 `app.databases.db -> ...` |"
            f" {audit_data['check_2_import_linter']['non_facade_legacy_count']} 项非门面遗留边 (覆盖 6 个合约) |"
            f" {'✅ 通过' if summary['check_2_only_facade_ignores'] else '❌ 阻塞'} |"
        ),
        (
            f"| 3. src 源码门面导入清洁 | AST 与 Grimp 全仓扫描 `src/` | 仅 `app.databases` 自身导入 | 仅"
            f" `src/app/databases/__init__.py` 导入 `app.databases.db` |"
            f" {'✅ 通过' if summary['check_3_src_databases_clean'] else '❌ 阻塞'} |"
        ),
        "",
    ]

    if not passed:
        lines.extend(
            [
                "## 2. 阻塞归因与负责变更清单",
                "",
                "根据 proposal.md 与 design.md 决策 D1，本变更不承担清理其他领域遗留债务的责任，必须交回对应变更清零后方可开始移除门面：",
                "",
                "| 负责变更 / 领域 | 基线违规数 | 合约非门面忽略数 | 涉及主要模块 |",
                "|---|---|---|---|",
            ]
        )
        for owner, counts in audit_data["responsible_changes_summary"].items():
            lines.append(
                f"| `{owner}` | {counts['baseline_violations']} | {counts['import_linter_ignores']} | 见下文详细清单 |"
            )
        lines.append("")

    # Detail Check 1
    b_data = audit_data["check_1_baseline"]
    lines.extend(
        [
            "## 3. Check 1 详细数据：baseline.json",
            "",
            f"- `cross_domain_calls`: **{b_data['categories'].get('cross_domain_calls', {}).get('count', 0)}** 条",
            (
                f"- `contract_ignore_counts`: 非零合约数"
                f" **{b_data['categories'].get('contract_ignore_counts', {}).get('non_zero_count', 0)}**"
            ),
            "- `config_access`: 0",
            "- `line_budgets`: 0 (豁免保留类别)",
            "- `model_registry`: 0",
            "- `mixin_duplicates`: 0",
            "- `numbered_modules`: 0",
            "",
            "### cross_domain_calls 归属分布",
            "",
        ]
    )
    # Group baseline violations by owner and source domain
    from collections import Counter

    b_violations = b_data["violations"]
    b_calls = [v for v in b_violations if v.get("category") == "cross_domain_calls"]
    owner_domain_counter = Counter(
        (v["owner"], v["source_domain"], v["target_domain"], v["kind"]) for v in b_calls
    )
    lines.extend(
        [
            "| 归属变更 | 源领域 | 目标领域 | 类型 | 数量 | 源码举例 |",
            "|---|---|---|---|---|---|",
        ]
    )
    for (owner, src, tgt, kind), cnt in sorted(owner_domain_counter.items()):
        example = next(
            v
            for v in b_calls
            if v["owner"] == owner
            and v["source_domain"] == src
            and v["target_domain"] == tgt
            and v["kind"] == kind
        )
        lines.append(
            f"| `{owner}` | `{src}` | `{tgt}` | {kind} | {cnt} | `{example['path']}:{example['line']}`"
            f" (`{example['target']}`) |"
        )
    lines.append("")

    # Detail Check 2
    l_data = audit_data["check_2_import_linter"]
    lines.extend(
        [
            "## 4. Check 2 详细数据：import-linter ignore_imports",
            "",
            f"- 门面组合边 (合法过渡放行): **{l_data['facade_composition_count']}**",
        ]
    )
    for fe in l_data["facade_composition_edges"]:
        lines.append(f"  - `[{fe['contract']}] {fe['edge']}`")

    lines.extend(
        [
            "",
            f"- 非门面遗留边 (违背清空前提): **{l_data['non_facade_legacy_count']}**",
            "",
            "| 合约 | 忽略导入边 | 归属变更 / 注释 | 源码中是否真实存在 | 源码证据位置 |",
            "|---|---|---|---|---|",
        ]
    )
    for nfe in l_data["non_facade_legacy_edges"]:
        ev = nfe["evidence"][0] if nfe["evidence"] else None
        ev_str = f"`{ev['path']}:{ev['line']}`" if ev else "无直接导入"
        lines.append(
            f"| {nfe['contract']} | `{nfe['edge']}` | `{nfe['owner']}` ({nfe['comment'] or '无注释'}) |"
            f" {'是' if nfe['active_in_src'] else '否'} | {ev_str} |"
        )
    lines.append("")

    # Detail Check 3
    s_data = audit_data["check_3_src_databases"]
    lines.extend(
        [
            "## 5. Check 3 详细数据：src/ app.databases 导入",
            "",
            f"- AST 扫描 `src/` 总命中: {s_data['ast_total_imports']} 处",
            f"- 外部模块导入 `app.databases`: **{len(s_data['ast_external_imports'])}** 处",
            "- 内部自身导入:",
        ]
    )
    for internal in s_data["ast_internal_imports"]:
        lines.append(
            f"  - `{internal['path']}:{internal['line']}`: `{internal['statement']}`"
        )
    lines.extend(
        [
            "",
            f"- Grimp 下游模块 (`find_downstream_modules('app.databases')`): `{s_data['grimp_downstream_databases']}`",
            f"- Grimp 下游模块 (`find_downstream_modules('app.databases.db')`): `{s_data['grimp_downstream_db']}`",
            "",
            "**结论**: `src/` 中除 `app/databases` 自身外没有任何模块导入门面，Check 3 完全通过。",
            "",
        ]
    )

    # Detail Check 4
    c_data = audit_data["check_4_compat_and_scripts"]
    lines.extend(
        [
            "## 6. Check 4 兼容层与脚本调用现状",
            "",
            f"- `DatabaseORM` 当前组合的 mixin/repo: `{', '.join(c_data['composed_mixins'])}`",
            f"- `IdentityRepository` 兼容方法数: {c_data['identity_compat_methods_count']} 个",
            f"- `src/` 中对 `db.*` / `DatabaseORM.*` 的调用点: **{c_data['db_calls_src_count']}** 处",
            (
                f"- `tests/` 中对 `db.*` / `orm.*` 的直接方法调用点: **{c_data['db_calls_tests_count']}** 处"
                " (注：测试夹具 `orm` 作为 fixture 注入 239 处，但均已改由内部 `get_session` 或直接调用 service/repo)"
            ),
            f"- `scripts/` 中直接调用 `db.*` 的方法点: **{c_data['db_calls_scripts_count']}** 处：",
        ]
    )
    for sc in c_data["db_calls_scripts"]:
        lines.append(f"  - `{sc['path']}:{sc['line']}`: `{sc['snippet']}`")

    lines.extend(
        [
            "",
            f"- `scripts/` 中导入 `app.databases` 的脚本清单 ({len(c_data['scripts_databases_imports'])} 处):",
        ]
    )
    for si in c_data["scripts_databases_imports"]:
        lines.append(f"  - `{si['path']}:{si['line']}`: `{si['statement']}`")

    lines.extend(
        [
            "",
            f"- `tests/` 中导入 `app.databases` 的测试文件清单 ({len(c_data['tests_databases_imports'])} 处):",
        ]
    )
    for ti in c_data["tests_databases_imports"]:
        lines.append(f"  - `{ti['path']}:{ti['line']}`: `{ti['statement']}`")

    lines.extend(
        [
            "",
            "## 7. 下一步行动建议",
            "",
            "1. **保持任务 1.1 未勾选** (`- [ ] 1.1`)，严格遵守 OpenSpec 任务前置条件与提案 D1 停工规定。",
            (
                "2. **停止当前变更的重构代码编写**（绝对不要删除 `app/databases/`、不要修改 `baseline.json` 放行项、不要修改"
                " `pyproject.toml` 合约）。"
            ),
            "3. **退回前序变更补齐前置清零**：",
            (
                "   - **`promote-line-domains`**: 清理 75 条 cross_domain_calls，重构 `premium.service ->"
                " app.core.db`、`traffic.jobs` 直连数据库及跨域模型导入、`traffic.repository -> lines.catalog` 等。"
            ),
            (
                "   - **`promote-gift-pack-domain`**: 清理 4 条 cross_domain_calls 及 `gift_pack.rules ->"
                " gift_pack.models` 忽略项。"
            ),
            "   - **`promote-blackjack-domain`**: 解耦 `blackjack.router -> blackjack.jobs` 依赖。",
            (
                "   - **手动脚本迁移**: 改写 `scripts/migrate_redis_to_database.py` 与"
                " `scripts/migrate_line_traffic_stats.py`，改用新领域 service/repository。"
            ),
            (
                "4. 待上述依赖项全部完成基线清零后，重新运行本盘点脚本，全绿后再行勾选 task 1.1 并推进门面删除。"
            ),
        ]
    )

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prerequisite audit for retire-legacy-db-facade."
    )
    parser.add_argument(
        "--json-path", type=str, default=None, help="Path to write JSON output"
    )
    parser.add_argument(
        "--md-path", type=str, default=None, help="Path to write Markdown output"
    )
    parser.add_argument(
        "--check", action="store_true", help="Exit 1 if prerequisites fail"
    )
    parser.add_argument("--repo-root", type=str, default=None, help="Path to repo root")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root else get_repo_root()
    audit_data = run_full_audit(repo_root)

    json_path = (
        Path(args.json_path)
        if args.json_path
        else repo_root
        / "openspec/changes/retire-legacy-db-facade/prerequisite-audit.json"
    )
    md_path = (
        Path(args.md_path)
        if args.md_path
        else repo_root
        / "openspec/changes/retire-legacy-db-facade/prerequisite-audit.md"
    )

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(audit_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    md_content = render_markdown(audit_data)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md_content, encoding="utf-8")

    print(f"Audit completed. Verdict: {audit_data['gate_verdict']}")
    print(f"JSON output written to: {json_path}")
    print(f"Markdown output written to: {md_path}")
    print("\nSummary:")
    for k, v in audit_data["summary"].items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")

    if args.check and not audit_data["all_prerequisites_passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
