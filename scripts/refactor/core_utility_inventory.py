"""Inventory the pre-migration core utility surface and its consumers.

The generated JSON is an audit artifact, not a runtime registry. It records the
current implementation commit, the D2 disposition for every core module, AST
symbols, direct imports, dynamic string references, manual-operation hints, and
scheduler/jobstore references so a later structural migration can prove that
no caller was silently dropped.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = (ROOT / "src", ROOT / "tests", ROOT / "scripts")
CORE_ROOT = ROOT / "src" / "app" / "core"

DISPOSITIONS: dict[str, dict[str, object]] = {
    "app.core.cache": {
        "decision": "retain-and-purify",
        "target": "app.core.cache",
        "contract": "RedisCache/Lua mechanism only; business instances leave this module",
    },
    "app.core.config": {
        "decision": "retain",
        "target": "app.core.config",
        "contract": "infrastructure settings and filesystem paths; private container detection",
    },
    "app.core.db": {
        "decision": "retain",
        "target": "app.core.db",
        "contract": "engine/session/post-commit callbacks only",
    },
    "app.core.domain_config": {
        "decision": "retain",
        "target": "app.core.domain_config",
        "contract": "generic typed business-config storage and cache",
    },
    "app.core.errors": {
        "decision": "retain",
        "target": "app.core.errors",
        "contract": "shared DomainError base only",
    },
    "app.core.byte_size": {
        "decision": "retain",
        "target": "app.core.byte_size",
        "contract": "pure generic byte-size formatting only",
    },
    "app.core.http": {
        "decision": "retain",
        "target": "app.core.http",
        "contract": "outbound HTTP session/connection pool mechanism",
    },
    "app.core.kv": {
        "decision": "retain",
        "target": "app.core.kv",
        "contract": "generic SystemConfig key/value transaction helpers",
    },
    "app.core.legacy_env": {
        "decision": "purify",
        "target": "app.core.legacy_env",
        "contract": "parameterized legacy source reader; no business key registry",
    },
    "app.core.log": {
        "decision": "retain",
        "target": "app.core.log",
        "contract": "logging infrastructure",
    },
    "app.core.redis": {
        "decision": "retain",
        "target": "app.core.redis",
        "contract": "Redis connection/pool mechanism",
    },
    "app.core.scheduler": {
        "decision": "retain-and-privatize",
        "target": "app.core.scheduler",
        "contract": "scheduler mechanism; singleton implementation private to Scheduler",
    },
}

_DYNAMIC_REF_RE = re.compile(r"app\.(?:core|utils|webapp)(?:\.[A-Za-z_][\w]*)+")
_MANUAL_HINT_RE = re.compile(r"manual|operational|运维|手动|入口", re.IGNORECASE)
_SCHEDULER_HINT_RE = re.compile(
    r"scheduler|schedule|jobstore|add_job|callable", re.IGNORECASE
)


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT / "src").with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _top_level_symbols(path: Path) -> list[dict[str, object]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    symbols: list[dict[str, object]] = []
    for node in tree.body:
        names: list[str] = []
        kind = "statement"
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
        elif isinstance(node, ast.Assign):
            kind = "assignment"
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.append(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
            kind = "assignment"
        for name in names:
            symbols.append(
                {
                    "name": name,
                    "kind": kind,
                    "line": node.lineno,
                    "end_line": node.end_lineno,
                    "public": not name.startswith("_"),
                }
            )
    return symbols


def _import_edges(path: Path, targets: set[str]) -> list[dict[str, object]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    edges: list[dict[str, object]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                if module in targets or any(
                    module.startswith(f"{target}.") for target in targets
                ):
                    edges.append(
                        {
                            "path": path.relative_to(ROOT).as_posix(),
                            "line": node.lineno,
                            "module": module,
                            "symbol": "*",
                            "kind": "import",
                        }
                    )
        elif isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            if module in targets or any(
                module.startswith(f"{target}.") for target in targets
            ):
                for alias in node.names:
                    edges.append(
                        {
                            "path": path.relative_to(ROOT).as_posix(),
                            "line": node.lineno,
                            "module": module,
                            "symbol": alias.name,
                            "kind": "from",
                        }
                    )
    return edges


def _text_references(path: Path, targets: set[str]) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    references: list[dict[str, object]] = []
    for line_no, line in enumerate(lines, start=1):
        for match in _DYNAMIC_REF_RE.finditer(line):
            value = match.group(0)
            if value in targets or any(
                value.startswith(f"{target}.") for target in targets
            ):
                references.append(
                    {
                        "path": path.relative_to(ROOT).as_posix(),
                        "line": line_no,
                        "value": value,
                    }
                )
    return references


def _files() -> Iterable[Path]:
    for root in SOURCE_ROOTS:
        if root.exists():
            yield from sorted(root.rglob("*.py"))
    yield from sorted((ROOT / "docs").rglob("*.md"))
    for path in (ROOT / "AGENTS.md", ROOT / "pyproject.toml"):
        if path.exists():
            yield path


def build_inventory() -> dict[str, object]:
    modules: dict[str, dict[str, object]] = {}
    for path in sorted(CORE_ROOT.glob("*.py")):
        module = _module_name(path)
        if module == "app.core":
            continue
        disposition = DISPOSITIONS.get(module)
        if disposition is None:
            raise AssertionError(f"core module has no D2 disposition: {module}")
        modules[module] = {
            **disposition,
            "path": path.relative_to(ROOT).as_posix(),
            "symbols": _top_level_symbols(path),
        }

    target_modules = set(modules)
    imports: list[dict[str, object]] = []
    dynamic_refs: list[dict[str, object]] = []
    manual_hints: list[dict[str, object]] = []
    scheduler_refs: list[dict[str, object]] = []
    for path in _files():
        imports.extend(_import_edges(path, target_modules))
        dynamic_refs.extend(_text_references(path, target_modules))
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _MANUAL_HINT_RE.search(text) and any(
            module in text for module in target_modules
        ):
            manual_hints.append({"path": path.relative_to(ROOT).as_posix()})
        if _SCHEDULER_HINT_RE.search(text) and any(
            module in text for module in target_modules
        ):
            scheduler_refs.append({"path": path.relative_to(ROOT).as_posix()})

    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    return {
        "baseline_commit": commit,
        "source_roots": [path.relative_to(ROOT).as_posix() for path in SOURCE_ROOTS],
        "modules": modules,
        "imports": sorted(
            imports,
            key=lambda item: (
                str(item["path"]),
                int(item["line"]),
                str(item["module"]),
                str(item["symbol"]),
            ),
        ),
        "dynamic_references": sorted(
            dynamic_refs,
            key=lambda item: (str(item["path"]), int(item["line"]), str(item["value"])),
        ),
        "manual_operation_hints": sorted(
            manual_hints, key=lambda item: str(item["path"])
        ),
        "scheduler_callable_hints": sorted(
            scheduler_refs, key=lambda item: str(item["path"])
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inventory = build_inventory()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(inventory, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
