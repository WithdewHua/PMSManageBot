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
    package_level: str | None = None
    symbols: dict[str, str] = field(default_factory=dict)


def identity(entry: dict[str, Any]) -> tuple[Any, ...]:
    """Return the reviewed identity of a baseline entry (path/line excluded)."""
    return tuple(entry.get(field) for field in IDENTITY_FIELDS)


@dataclass(frozen=True)
class Addition:
    """A reviewed new baseline entry that a move cannot avoid creating.

    Splitting one module into mixins can turn a single cross-domain import into
    two edges when both parts use it. Such an addition must be declared with the
    original key it duplicates, and it inherits that entry's owner.
    """

    key: str
    source_key: str
    reason: str


@dataclass(frozen=True)
class Removal:
    """A reviewed baseline entry a move makes disappear.

    Two source modules can import the same target for their own members; when
    those members end up in one sub-topic module, only one import site is left.
    The edge itself must still exist somewhere in the new scan.
    """

    key: str
    reason: str


def load_additions(path: Path) -> dict[str, Addition]:
    """Parse declared additions (empty when the file has none)."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    additions: dict[str, Addition] = {}
    for item in data.get("addition", []):
        key = str(item.get("key", ""))
        source_key = str(item.get("source_key", ""))
        reason = str(item.get("reason", "")).strip()
        if not key or not source_key or not reason:
            raise BaselineMoveError(f"{path} 的 addition 缺少 key/source_key/reason")
        if key in additions:
            raise BaselineMoveError(f"{path} 中重复登记了 addition {key}")
        additions[key] = Addition(key=key, source_key=source_key, reason=reason)
    return additions


def load_removals(path: Path) -> dict[str, Removal]:
    """Parse declared removals (empty when the file has none)."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    removals: dict[str, Removal] = {}
    for item in data.get("removal", []):
        key = str(item.get("key", ""))
        reason = str(item.get("reason", "")).strip()
        if not key or not reason:
            raise BaselineMoveError(f"{path} 的 removal 缺少 key/reason")
        if key in removals:
            raise BaselineMoveError(f"{path} 中重复登记了 removal {key}")
        removals[key] = Removal(key=key, reason=reason)
    return removals


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
            package_level=item.get("package_level"),
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


def _in_package_predicate(
    move: MoveRecord | None,
) -> Callable[[dict[str, Any]], bool] | None:
    """Prefer entries sitting in the package a moved module belongs to."""
    if move is None or not move.package_level:
        return None
    package = move.package_level

    def in_package(entry: dict[str, Any]) -> bool:
        return Path(str(entry.get("path"))).parent.as_posix() == package

    return in_package


def _take_match(
    bucket: list[dict[str, Any]],
    symbol: str | None,
    new_symbol: Callable[[str, int], str | None] | None,
    prefer: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Pick the new entry belonging to the same function as the old one.

    Entries that share an identity (same kind, domains and target) are told
    apart by their enclosing symbol, so provenance such as ``b3_source_id``
    keeps following the function it was audited for. ``prefer`` breaks ties
    between module-level entries: a moved import must be taken from the
    declared package, not from an unrelated edge with the same target.
    """
    if prefer is not None:
        bucket.sort(key=lambda entry: (not prefer(entry), entry.get("path", "")))
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
    additions: dict[str, Addition] | None = None,
    removals: dict[str, Removal] | None = None,
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
    old_by_key = {entry["key"]: entry for entry in old}
    new = list(new_entries)
    new_by_key = {entry["key"]: entry for entry in new}
    accepted: list[dict[str, Any]] = []
    for key, addition in (additions or {}).items():
        if key in old_by_key:
            # 已封存：只要仍有一条身份相同的“孪生边”，声明就依然成立
            # （孪生边会在后续搬移里换 key，所以不盯 source_key）。
            twins = [
                entry
                for entry in old
                if entry["key"] != key and identity(entry) == identity(old_by_key[key])
            ]
            if not twins:
                raise BaselineMoveError(f"addition 的孪生边已消失，声明过期：{key}")
            continue
        added = new_by_key.get(key)
        if added is None:
            raise BaselineMoveError(f"addition 在新扫描里不存在：{key}")
        original = old_by_key.get(addition.source_key)
        if original is None:
            raise BaselineMoveError(
                f"addition 的原始条目不在旧基线里：{addition.source_key}"
            )
        if identity(added) != identity(original):
            raise BaselineMoveError(
                f"addition 不是同一条重复边：{key} 与 {addition.source_key}"
            )
        # 重复的边继承原条目的 owner；除 key/path/line 外其余元数据相同。
        accepted.append({**{k: v for k, v in original.items()}, **added})
        new = [entry for entry in new if entry["key"] != key]
    dropped: list[dict[str, Any]] = []
    for key, removal in (removals or {}).items():
        original = old_by_key.get(key)
        if original is None:
            raise BaselineMoveError(f"removal 的条目不在旧基线里：{key}")
        if key in new_by_key:
            raise BaselineMoveError(f"removal 的条目在新扫描里还存在：{key}")
        if not [entry for entry in new if identity(entry) == identity(original)]:
            raise BaselineMoveError(
                f"removal 使这条边彻底消失，不能只靠声明去掉：{key}（{removal.reason}）"
            )
        dropped.append(original)
        old = [entry for entry in old if entry["key"] != key]
    old_symbol = _symbol_reader(read_source)
    new_symbol = _symbol_reader(read_new_source) if read_new_source else None

    buckets: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for entry in new:
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
        move = moves.get(path) if isinstance(path, str) else None
        prefer = _in_package_predicate(move)
        match = _take_match(bucket, symbol, new_symbol, prefer=prefer)
        if move is None:
            if match.get("path") != path:
                raise BaselineMoveError(
                    f"{path} 未登记搬移，但条目出现在 {match.get('path')}：{entry['key']}"
                )
        else:
            target = move.symbols.get(symbol) if symbol else None
            if target is None:
                target = move.module_level
            if target is None and move.package_level:
                # 模块级条目（导入）按使用位置散到同一个包的多个模块里，
                # 只要求落在登记的那个包内。
                parent = Path(str(match.get("path"))).parent.as_posix()
                if parent != move.package_level:
                    raise BaselineMoveError(
                        f"包外落点：{path} 应留在 {move.package_level}，实际在 "
                        f"{match.get('path')}"
                    )
            elif target is None:
                raise BaselineMoveError(
                    f"映射缺失：{path} 的 {symbol or '<module>'} 没有登记目标"
                )
            elif match.get("path") != target:
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
    return sorted([*rewritten, *accepted], key=lambda entry: entry["key"])


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
    additions = load_additions(args.moves)
    removals = load_removals(args.moves)
    baseline = load_baseline(args.baseline)
    current = scan_cross_domain_calls(PROJECT_ROOT)
    rewritten = rewrite_entries(
        baseline["cross_domain_calls"],
        current,
        moves,
        git_source(args.base),
        _planned_targets(args.mapping),
        read_new_source=lambda path: (PROJECT_ROOT / path).read_text(encoding="utf-8"),
        additions=additions,
        removals=removals,
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
