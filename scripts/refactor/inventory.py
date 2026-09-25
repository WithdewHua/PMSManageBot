"""Inventory relocatable Python definitions and verify mapping coverage.

Run ``python -m scripts.refactor.inventory --module app.databases.db`` to inspect
one module, or omit --module to scan all ``src/app`` sources. The JSON output
contains source spans (including contiguous leading comments and decorators)
and a location-independent AST for each item. Coverage accepts a TOML file with
``[[items]]`` records containing an ``id`` and either a ``target`` module or the
literal ``TODO``; deletions use ``action = 'delete'`` with a reason.
"""

from __future__ import annotations

import argparse
import ast
import json
import tomllib
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "app"
ASSIGNMENT = (ast.Assign, ast.AnnAssign)


@dataclass(frozen=True)
class Item:
    id: str
    module: str
    name: str
    kind: str
    path: str
    start_line: int
    end_line: int
    ast: str
    parent_id: str | None = None
    unit_id: str = ""


def module_name(path: Path, root: Path = ROOT) -> str:
    """Get the import path for a source file, including namespace packages."""
    parts = list(path.relative_to(root / "src").with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    def unpack(target: ast.expr) -> Iterable[str]:
        if isinstance(target, ast.Name):
            yield target.id
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                yield from unpack(element)

    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return sorted({name for target in targets for name in unpack(target)})


def _start(node: ast.stmt, lines: list[str]) -> int:
    start = node.lineno
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        start = min([start, *(decorator.lineno for decorator in node.decorator_list)])
    # Contiguous standalone comments immediately above a definition belong to
    # it; do not cross a blank line or take a previous definition's inline note.
    while start > 1 and lines[start - 2].lstrip().startswith("#"):
        start -= 1
    return start


def _items_in_body(
    body: list[ast.stmt],
    *,
    module: str,
    parent: str | None,
    path: str,
    lines: list[str],
) -> list[Item]:
    items: list[Item] = []
    occurrences: Counter[str] = Counter()
    anonymous: Counter[str] = Counter()
    parent_id = f"{module}:{parent}" if parent else None
    is_package = path.endswith("/__init__.py")
    for ordinal, node in enumerate(body, start=1):
        if isinstance(node, ast.ClassDef):
            kind, names = "class", [node.name]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind, names = ("method" if parent else "function"), [node.name]
        elif isinstance(node, ASSIGNMENT):
            names = _names(node)
            kind = (
                "export"
                if is_package and "__all__" in names
                else ("attribute" if parent else "assignment")
            )
        else:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                kind = "package_import" if is_package and not parent else "import"
            elif (
                isinstance(node, ast.Expr)
                and not parent
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and node is body[0]
            ):
                kind = "docstring"
            else:
                # Includes if/try/with/while/for, bare calls, and class-body
                # executable statements. None may be silently dropped.
                kind = "statement"
            anonymous[kind] += 1
            names = [f"@{kind}:{anonymous[kind]}"]
        if not names:
            raise ValueError(f"unrecognized assignment at {path}:{node.lineno}")
        unit_id = f"{module}:@unit:{parent or 'module'}:{ordinal}"
        for name in names:
            qualified = f"{parent}.{name}" if parent else name
            occurrences[qualified] += 1
            suffix = f"#{occurrences[qualified]}" if occurrences[qualified] > 1 else ""
            items.append(
                Item(
                    id=f"{module}:{qualified}{suffix}",
                    module=module,
                    name=qualified,
                    kind=kind,
                    path=path,
                    start_line=_start(node, lines),
                    end_line=node.end_lineno,
                    ast=ast.dump(node, annotate_fields=True, include_attributes=False),
                    parent_id=parent_id,
                    unit_id=unit_id,
                )
            )
        if isinstance(node, ast.ClassDef):
            items.extend(
                _items_in_body(
                    node.body,
                    module=module,
                    parent=f"{parent}.{node.name}" if parent else node.name,
                    path=path,
                    lines=lines,
                )
            )
    return items


def inventory(paths: Iterable[Path], *, root: Path = ROOT) -> list[Item]:
    """Inventory explicitly supplied source files in stable ID order."""
    items: list[Item] = []
    for candidate in sorted(paths):
        source = candidate if candidate.is_absolute() else root / candidate
        lines = source.read_text(encoding="utf-8").splitlines()
        tree = ast.parse("\n".join(lines), filename=str(source))
        items.extend(
            _items_in_body(
                tree.body,
                module=module_name(source, root),
                parent=None,
                path=source.relative_to(root).as_posix(),
                lines=lines,
            )
        )
    return sorted(items, key=lambda item: item.id)


def coverage(items: list[Item], mapping_file: Path) -> dict[str, list[str]]:
    """Find missing and unresolved mapping entries without guessing locations."""
    with mapping_file.open("rb") as stream:
        mapping = tomllib.load(stream)
    entries = mapping.get("items", [])
    by_id: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise TypeError("each [[items]] record needs a string id")
        if entry["id"] in by_id:
            raise ValueError(f"duplicate mapping ID: {entry['id']}")
        by_id[entry["id"]] = entry
    ids = {item.id for item in items}
    missing = sorted(ids - by_id.keys())
    stale = sorted(by_id.keys() - ids)
    todo = sorted(
        key
        for key in ids & by_id.keys()
        if by_id[key].get("target") == "TODO" and by_id[key].get("action") != "delete"
    )
    invalid = sorted(
        key
        for key in ids & by_id.keys()
        if by_id[key].get("target") != "TODO"
        and not (
            isinstance(by_id[key].get("target"), str)
            and by_id[key]["target"].startswith("app.")
        )
        and not (
            by_id[key].get("action") == "delete"
            and isinstance(by_id[key].get("reason"), str)
            and by_id[key]["reason"].strip()
        )
    )
    return {"missing": missing, "todo": todo, "invalid": invalid, "stale": stale}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--module", help="Filter by full import path (for example app.databases.db)"
    )
    parser.add_argument("--coverage", type=Path, help="TOML mapping file to check")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show counts instead of the full inventory",
    )
    args = parser.parse_args()
    paths = SOURCE.rglob("*.py")
    items = inventory(paths)
    if args.module:
        items = [item for item in items if item.module == args.module]
    if args.coverage:
        report = coverage(items, args.coverage)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
        return int(bool(report["missing"] or report["invalid"] or report["stale"]))
    if args.summary:
        print(
            json.dumps(
                dict(sorted(Counter(item.kind for item in items).items())),
                sort_keys=True,
            )
        )
    else:
        print(
            json.dumps(
                [asdict(item) for item in items],
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
