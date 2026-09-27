"""Rewrite architecture baseline ``path|line`` keys after a pure code move.

A sub-topic split changes the ``key`` of every baseline entry in the moved
modules (``key`` embeds the path and the line). Regenerating the baseline would
hide removals or additions, so the reviewed flow is:

1. declare the move per module and per symbol in ``baseline_moves.toml``;
2. run this script, which rescans the tree, proves that the multiset over
   ``(owner, kind, source_domain, target_domain, target)`` is unchanged, proves
   that every path change is covered by the declared moves, and only then
   rewrites ``path``/``line``/``key`` while preserving the review metadata
   (``owner``, ``b3_source_id``, ...);
3. review the resulting baseline diff: it must contain nothing but path, line
   and key changes.

Usage::

    PYTHONPATH=src .venv/bin/python -m scripts.refactor.rewrite_baseline_keys \\
      --moves scripts/refactor/baseline_moves.toml --base HEAD --write
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

IDENTITY_FIELDS = (
    "owner",
    "kind",
    "source_domain",
    "target_domain",
    "target",
    "symbol",
)
DEFAULT_MOVES_PATH = PROJECT_ROOT / "scripts/refactor/baseline_moves.toml"
DEFAULT_BASELINE_PATH = PROJECT_ROOT / "tests/architecture/baseline.json"
DEFAULT_MAPPING_PATH = PROJECT_ROOT / "scripts/refactor/mapping.toml"


class BaselineMoveError(RuntimeError):
    """Raised when a rewrite would hide a change that was not reviewed."""


@dataclass(frozen=True)
class MoveRecord:
    """Declared destination of one moved module."""

    source: str
    module_level: str | None = None
    symbols: dict[str, str] = field(default_factory=dict)


def identity(entry: dict[str, Any]) -> tuple[Any, ...]:
    """Return the reviewed identity of a baseline entry (path/line excluded)."""
    return tuple(entry.get(field) for field in IDENTITY_FIELDS)


def load_moves(path: Path) -> dict[str, MoveRecord]:
    """Parse the declared module moves."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    moves: dict[str, MoveRecord] = {}
    for item in data.get("move", []):
        source = item.get("source")
        if not isinstance(source, str) or not source:
            raise BaselineMoveError(f"{path} 中的 move 缺少 source")
        if source in moves:
            raise BaselineMoveError(f"{path} 中重复登记了 {source}")
        symbols = item.get("symbols", {})
        if not isinstance(symbols, dict):
            raise BaselineMoveError(f"{path} 中 {source} 的 symbols 必须是表")
        moves[source] = MoveRecord(
            source=source,
            module_level=item.get("module_level"),
            symbols={str(key): str(value) for key, value in symbols.items()},
        )
    if not moves:
        raise BaselineMoveError(f"{path} 没有登记任何 move")
    return moves


def enclosing_symbol(source: str, line: int) -> str | None:
    """Return the innermost function/class containing ``line``, else ``None``."""
    tree = ast.parse(source)
    found: str | None = None
    best = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        end = node.end_lineno or node.lineno
        if node.lineno <= line <= end and node.lineno >= best:
            found = node.name
            best = node.lineno
    return found


def module_path(module: str) -> str:
    """Convert ``app.domains.x.repository.conditions`` to its source path."""
    return "src/" + module.replace(".", "/") + ".py"


def path_to_module(path: str) -> str:
    """Convert ``src/app/domains/x/repository/conditions.py`` to its module name."""
    return path.removeprefix("src/").removesuffix(".py").replace("/", ".")


def _planned_targets(mapping_path: Path) -> dict[str, str]:
    """Read the reviewed sub-topic destination of every mapped repository symbol."""
    if not mapping_path.exists():
        return {}
    data = tomllib.loads(mapping_path.read_text(encoding="utf-8"))
    planned: dict[str, str] = {}
    for item in data.get("items", []):
        target = item.get("planned_target")
        identifier = item.get("id")
        if not target or not isinstance(identifier, str):
            continue
        symbol = identifier.rsplit(".", 1)[-1]
        planned[symbol] = str(target)
    return planned


def _take_match(
    bucket: list[dict[str, Any]],
    symbol: str | None,
    new_symbol: Callable[[str, int], str | None] | None,
) -> dict[str, Any]:
    """Pick the new entry belonging to the same function as the old one.

    Entries that share an identity (same kind, domains and target) are told
    apart by their enclosing symbol, so provenance such as ``b3_source_id``
    keeps following the function it was audited for.
    """
    if new_symbol is not None:
        for index, candidate in enumerate(bucket):
            if new_symbol(candidate["path"], int(candidate["line"])) == symbol:
                return bucket.pop(index)
    return bucket.pop(0)


def _symbol_reader(reader: Callable[[str], str]) -> Callable[[str, int], str | None]:
    """Cache file sources and resolve the enclosing symbol of a line."""
    cache: dict[str, str] = {}

    def symbol(path: str, line: int) -> str | None:
        if path not in cache:
            try:
                cache[path] = reader(path)
            except Exception:
                cache[path] = ""
        text = cache[path]
        if not text:
            return None
        return enclosing_symbol(text, line)

    return symbol


def rewrite_entries(
    old_entries: Iterable[dict[str, Any]],
    new_entries: Iterable[dict[str, Any]],
    moves: dict[str, MoveRecord],
    read_source: Callable[[str], str],
    planned_targets: dict[str, str] | None = None,
    read_new_source: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """Rewrite ``path``/``line``/``key`` while proving the move was reviewed.

    ``read_source`` reads the pre-move sources (git revision), so the enclosing
    symbol of every old entry is known. Entries are grouped by
    ``identity + enclosing symbol``, which keeps provenance (for example
    ``b3_source_id``) attached to the same function and turns a silent symbol
    rename into an error. When ``read_new_source`` is given, the matched entry
    must sit in the same-named symbol on the new side.
    """
    old = sorted(old_entries, key=lambda entry: entry["key"])
    old_symbol = _symbol_reader(read_source)
    new_symbol = _symbol_reader(read_new_source) if read_new_source else None

    buckets: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for entry in new_entries:
        buckets.setdefault(identity(entry), []).append(entry)
    for entries in buckets.values():
        entries.sort(key=lambda item: (item.get("path", ""), item.get("line", 0)))

    rewritten: list[dict[str, Any]] = []
    for entry in old:
        path = entry.get("path")
        symbol = old_symbol(path, int(entry["line"])) if isinstance(path, str) else None
        bucket = buckets.get(identity(entry))
        if not bucket:
            raise BaselineMoveError(
                f"未登记的多重集合变化：{identity(entry)} 在新扫描里没有对应条目"
            )
        match = _take_match(bucket, symbol, new_symbol)
        move = moves.get(path) if isinstance(path, str) else None
        if move is None:
            if match.get("path") != path:
                raise BaselineMoveError(
                    f"{path} 未登记搬移，但条目出现在 {match.get('path')}：{entry['key']}"
                )
        else:
            target = move.symbols.get(symbol) if symbol else None
            if target is None:
                target = move.module_level
            if target is None:
                raise BaselineMoveError(
                    f"映射缺失：{path} 的 {symbol or '<module>'} 没有登记目标"
                )
            if match.get("path") != target:
                raise BaselineMoveError(
                    f"映射不一致：{path} 的 {symbol or '<module>'} 应到 {target}，"
                    f"实际在 {match.get('path')}"
                )
            planned = (planned_targets or {}).get(symbol or "")
            if planned and planned != path_to_module(match["path"]):
                raise BaselineMoveError(
                    f"与 mapping.toml 的 planned_target 不一致：{symbol} 登记为 "
                    f"{planned}，实际目标为 {match.get('path')}"
                )
        if new_symbol is not None:
            matched_symbol = new_symbol(match["path"], int(match["line"]))
            if matched_symbol != symbol:
                raise BaselineMoveError(
                    f"符号不一致：{entry['key']} 原本在 {symbol or '<module>'}，"
                    f"新位置属于 {matched_symbol or '<module>'}"
                )
        updated = dict(entry)
        updated["path"] = match["path"]
        updated["line"] = match["line"]
        updated["key"] = match["key"]
        rewritten.append(updated)

    leftovers = [entry for entries in buckets.values() for entry in entries]
    if leftovers:
        raise BaselineMoveError(
            "未登记的多重集合变化：新扫描多出条目 "
            + ", ".join(str(entry.get("key")) for entry in leftovers[:5])
        )
    return sorted(rewritten, key=lambda entry: entry["key"])


def git_source(rev: str) -> Callable[[str], str]:
    """Read the pre-move source of a path straight from a git revision."""

    def read(path: str) -> str:
        result = subprocess.run(
            ["git", "show", f"{rev}:{path}"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise BaselineMoveError(
                f"git show {rev}:{path} 失败：{result.stderr.strip()}"
            )
        return result.stdout

    return read


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--moves", type=Path, default=DEFAULT_MOVES_PATH)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING_PATH)
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    from tests.architecture.checks import scan_cross_domain_calls
    from tests.architecture.helpers import load_baseline, write_baseline

    moves = load_moves(args.moves)
    baseline = load_baseline(args.baseline)
    current = scan_cross_domain_calls(PROJECT_ROOT)
    rewritten = rewrite_entries(
        baseline["cross_domain_calls"],
        current,
        moves,
        git_source(args.base),
        _planned_targets(args.mapping),
        read_new_source=lambda path: (PROJECT_ROOT / path).read_text(encoding="utf-8"),
    )
    baseline["cross_domain_calls"] = rewritten
    changed = sum(
        1
        for old, new in zip(
            sorted(
                load_baseline(args.baseline)["cross_domain_calls"],
                key=lambda entry: entry["key"],
            ),
            rewritten,
        )
        if old["key"] != new["key"]
    )
    print(
        json.dumps(
            {
                "entries": len(rewritten),
                "rewritten": changed,
                "moved_modules": sorted(moves),
                "baseline": str(args.baseline),
                "written": bool(args.write),
            },
            ensure_ascii=False,
        )
    )
    if args.write:
        write_baseline(baseline, args.baseline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
