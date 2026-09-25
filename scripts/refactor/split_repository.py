"""Split a generated large repository class into a same-name package of mixins.

Only generated B1 repository modules with one top-level class are supported.
Global constants/functions stay in ``__init__`` and class methods retain their
source text. This preserves the public import path and class name while keeping
each module below the architecture line budget.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


class SplitError(ValueError):
    """Cannot safely split a repository without losing a source unit."""


def _trim_assembly_imports(source: str) -> str:
    """Keep only imports referenced by package globals and retained methods."""
    tree = ast.parse(source)
    loaded = {
        node.id
        for statement in tree.body
        if not isinstance(statement, (ast.Import, ast.ImportFrom))
        for node in ast.walk(statement)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    lines = source.splitlines(keepends=True)
    edits: list[tuple[int, int, str]] = []
    for statement in tree.body:
        if not isinstance(statement, (ast.Import, ast.ImportFrom)):
            continue
        aliases = [
            alias
            for alias in statement.names
            if (
                alias.asname
                or (
                    alias.name.split(".")[0]
                    if isinstance(statement, ast.Import)
                    else alias.name
                )
            )
            in loaded
        ]
        if len(aliases) == len(statement.names):
            continue
        replacement: ast.stmt | None = None
        if aliases:
            replacement = (
                ast.Import(names=aliases)
                if isinstance(statement, ast.Import)
                else ast.ImportFrom(
                    module=statement.module, names=aliases, level=statement.level
                )
            )
        edits.append(
            (
                statement.lineno - 1,
                statement.end_lineno,
                ast.unparse(replacement) + "\n" if replacement else "",
            )
        )
    for start, end, text in reversed(edits):
        lines[start:end] = [text]
    return "".join(lines)


def split_repository(path: Path, *, max_lines: int = 900) -> dict[Path, str]:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    tree = ast.parse("".join(lines), filename=str(path))
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    if len(classes) != 1 or any(
        isinstance(node, ast.ClassDef) and node is not classes[0] for node in tree.body
    ):
        raise SplitError("expected exactly one top-level repository class")
    owner = classes[0]
    if (
        owner.bases
        or owner.decorator_list
        or any(node.lineno > owner.end_lineno for node in tree.body)
    ):
        raise SplitError(
            "repository has unsupported bases, decorators, or trailing code"
        )
    package = path.with_suffix("")
    imports = "".join(
        "".join(lines[node.lineno - 1 : node.end_lineno])
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    )
    global_names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            global_names.append(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            global_names.extend(
                name.id
                for target in targets
                for name in ast.walk(target)
                if isinstance(name, ast.Name)
            )
    bridge = "from . import " + ", ".join(global_names) + "\n" if global_names else ""
    members = list(owner.body)
    doc = ""
    if (
        members
        and isinstance(members[0], ast.Expr)
        and isinstance(members[0].value, ast.Constant)
        and isinstance(members[0].value.value, str)
    ):
        doc = "".join(lines[members[0].lineno - 1 : members[0].end_lineno])
        members = members[1:]
    if not members:
        raise SplitError("cannot split an empty repository")
    retain = {
        "_gift_pack_condition_label",
        "_resolve_gift_pack_conditions",
        "_strip_gift_pack_conditions",
    }
    # Static class references must continue to resolve against the final public
    # class, not against a private mixin in a submodule.
    explicit_refs = {
        node.name
        for node in members
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(child, ast.Name) and child.id == owner.name
            for child in ast.walk(node)
        )
    }
    retain |= explicit_refs
    chunks: list[list[str]] = []
    current: list[str] = []
    retained: list[str] = []
    starts = [
        min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
        for node in members
    ]
    previous = members[0].lineno if not doc else owner.body[0].end_lineno + 1
    if not doc:
        previous = owner.lineno + 1
    for index, node in enumerate(members):
        end = starts[index + 1] - 1 if index + 1 < len(starts) else owner.end_lineno
        part = "".join(lines[previous - 1 : end])
        previous = end + 1
        if getattr(node, "name", None) in retain:
            retained.append(part)
            continue
        if (
            current
            and sum(x.count("\n") for x in current) + part.count("\n") > max_lines - 160
        ):
            chunks.append(current)
            current = []
        current.append(part)
    if current:
        chunks.append(current)
    if not chunks:
        raise SplitError("no mixin methods to split")
    staged: dict[Path, str] = {}
    mixin_names: list[str] = []
    for index, chunk in enumerate(chunks, 1):
        mixin = f"_{owner.name}Part{index}"
        mixin_names.append(mixin)
        content = imports + "\n" + bridge + f"\nclass {mixin}:\n" + "".join(chunk)
        staged[package / f"part_{index}.py"] = content
    # Import the private mixins only *after* global constants/functions have
    # been initialized, so member modules can import those globals safely.
    header = "".join(lines[: owner.lineno - 1])
    assembly_imports = "\n".join(
        f"from .part_{index} import {mixin}"
        for index, mixin in enumerate(mixin_names, 1)
    )
    definition = f"class {owner.name}({', '.join(mixin_names)}):\n"
    definition += doc or "    pass\n"
    definition += "".join(retained)
    staged[package / "__init__.py"] = _trim_assembly_imports(
        header + "\n" + assembly_imports + "\n\n\n" + definition
    )
    for destination, content in staged.items():
        if len(content.splitlines()) > 1000:
            raise SplitError(f"generated module exceeds 1000 lines: {destination}")
        ast.parse(content, filename=str(destination))
    return staged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.path.is_file() or args.path.with_suffix("").exists():
        parser.error("source must be a file and target package must not exist")
    staged = split_repository(args.path)
    if args.apply:
        for path, content in staged.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        args.path.unlink()
    for path in sorted(staged):
        print(path)


if __name__ == "__main__":
    main()
