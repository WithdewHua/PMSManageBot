"""Shared AST and baseline helpers for architecture checks."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"
BASELINE_PATH = Path(__file__).with_name("baseline.json")
ARCHITECTURE_CATEGORIES = (
    "cross_domain_calls",
    "config_access",
    "line_budgets",
    "model_registry",
    "mixin_duplicates",
    "numbered_modules",
)


def python_files(root: Path) -> list[Path]:
    """Return source Python files in deterministic order."""
    source_root = root / "src"
    if not source_root.exists():
        source_root = root
    return sorted(
        path for path in source_root.rglob("*.py") if "__pycache__" not in path.parts
    )


def parse_python(path: Path) -> ast.Module:
    """Parse one Python source file with its filename in syntax errors."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def module_name(path: Path, root: Path) -> str:
    """Convert a source path to its importable ``app.*`` module name."""
    source_root = root / "src"
    if not source_root.exists():
        source_root = root
    relative = path.relative_to(source_root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def relative_path(path: Path, root: Path) -> str:
    """Return a stable repository-relative path for baseline entries."""
    return path.relative_to(root).as_posix()


def dotted_name(node: ast.AST) -> str | None:
    """Return a dotted name for a ``Name``/``Attribute`` AST node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def class_member_names(node: ast.ClassDef) -> list[tuple[str, int]]:
    """Return direct class member names, preserving duplicate definitions."""
    members: list[tuple[str, int]] = []
    for statement in node.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            members.append((statement.name, statement.lineno))
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            for target in targets:
                if isinstance(target, ast.Name):
                    members.append((target.id, statement.lineno))
    return members


def make_violation(
    key: str,
    owner: str,
    *,
    path: str | None = None,
    line: int | None = None,
    **details: Any,
) -> dict[str, Any]:
    """Build a JSON-compatible, stable violation record."""
    record: dict[str, Any] = {"key": key, "owner": owner}
    if path is not None:
        record["path"] = path
    if line is not None:
        record["line"] = line
    record.update(details)
    return record


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, list[dict[str, Any]]]:
    """Read and validate a baseline without modifying it."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("architecture baseline must have version 1")

    baseline: dict[str, list[dict[str, Any]]] = {}
    for category in ARCHITECTURE_CATEGORIES:
        entries = data.get(category)
        if not isinstance(entries, list):
            raise TypeError(f"baseline category {category!r} must be a list")
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise TypeError(f"baseline entry in {category!r} must be an object")
            key = entry.get("key")
            owner = entry.get("owner")
            if not isinstance(key, str) or not key:
                raise ValueError(f"baseline entry in {category!r} has no key")
            if not isinstance(owner, str) or not owner:
                raise ValueError(f"baseline entry {key!r} has no owner")
            if key in seen:
                raise ValueError(f"duplicate baseline key {key!r}")
            seen.add(key)
            normalized.append(dict(entry))
        baseline[category] = sorted(normalized, key=lambda item: item["key"])
    return baseline


def write_baseline(
    baseline: dict[str, list[dict[str, Any]]],
    path: Path = BASELINE_PATH,
) -> None:
    """Write a canonical baseline explicitly requested by a maintainer."""
    payload: dict[str, Any] = {"version": 1}
    for category in ARCHITECTURE_CATEGORIES:
        entries = baseline.get(category, [])
        payload[category] = sorted(entries, key=lambda item: item["key"])
    if path == BASELINE_PATH:
        import tomllib

        with (PROJECT_ROOT / "pyproject.toml").open("rb") as stream:
            contracts = tomllib.load(stream)["tool"]["importlinter"]["contracts"]
        payload["contract_ignore_counts"] = {
            contract["name"]: len(contract.get("ignore_imports", []))
            for contract in contracts
        }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def assert_baseline_exact(
    category: str,
    actual: list[dict[str, Any]],
    baseline: dict[str, list[dict[str, Any]]],
) -> None:
    """Require exact keys and owners; neither additions nor stale entries pass."""
    expected_entries = baseline[category]
    expected = {entry["key"]: entry for entry in expected_entries}
    found = {entry["key"]: entry for entry in actual}

    added = sorted(set(found) - set(expected))
    removed = sorted(set(expected) - set(found))
    owner_changed = sorted(
        key
        for key in set(found) & set(expected)
        if found[key].get("owner") != expected[key].get("owner")
    )
    details: list[str] = []
    if added:
        details.append(f"new violations: {added}")
    if removed:
        details.append(f"stale violations: {removed}")
    if owner_changed:
        details.append(f"owner changes: {owner_changed}")

    if category == "line_budgets":
        line_changed = sorted(
            key
            for key in set(found) & set(expected)
            if found[key].get("lines") != expected[key].get("lines")
        )
        if line_changed:
            details.append(f"line counts changed: {line_changed}")

    if details:
        raise AssertionError(f"{category} baseline mismatch; " + "; ".join(details))


def owner_for_domain(domain: str | None) -> str:
    """Map a domain to the change responsible for its current debt."""
    owners = {
        "accounts": "promote-account-domains",
        "auction": "promote-activity-domains",
        "badges": "promote-reward-domains",
        "badge_awards": "promote-reward-domains",
        "blackjack": "promote-blackjack-domain",
        "credits": "make-credit-changes-atomic",
        "crypto_donation": "promote-remaining-domains",
        "custom_lines": "promote-line-domains",
        "donation": "promote-remaining-domains",
        "gift_pack": "promote-gift-pack-domain",
        "identity": "promote-account-domains",
        "invitation": "promote-account-domains",
        "lines": "promote-line-domains",
        "luckywheel": "promote-activity-domains",
        "media_access": "promote-line-domains",
        "premium": "promote-line-domains",
        "prediction": "promote-activity-domains",
        "profile": "promote-remaining-domains",
        "rankings": "promote-remaining-domains",
        "reports": "promote-remaining-domains",
        "rewards": "promote-reward-domains",
        "tg_rebind": "promote-tg-rebind-domain",
        "traffic": "promote-line-domains",
        "treasure": "promote-activity-domains",
        "vaultwarden": "promote-remaining-domains",
        "watch_rewards": "promote-reward-domains",
    }
    return owners.get(domain or "", "restructure-backend-architecture")
