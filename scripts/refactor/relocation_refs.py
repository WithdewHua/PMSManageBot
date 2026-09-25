"""Plan syntax-aware updates to references after a reviewed relocation."""

from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from scripts.refactor.inventory import module_name
from scripts.refactor.rewrite_refs import (
    RewriteError,
    rewrite_database_orm_refs,
    rewrite_file,
    rewrite_moved_file,
)


class ReferencePlanError(ValueError):
    """A reference could not be safely rewritten before writing any files."""


def module_context(path: Path, root: Path) -> str:
    """Use a package context for __init__.py relative imports."""
    if path.is_relative_to(root / "src"):
        module = module_name(path, root)
    else:
        module = ".".join(path.relative_to(root).with_suffix("").parts)
    return module + ".__init__" if path.name == "__init__.py" else module


def reference_map(units: Sequence[Any]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Build symbol moves and statically known star-import exports."""
    moves: dict[str, str] = {}
    exports: dict[str, list[str]] = {}
    by_source: dict[Path, list[Any]] = defaultdict(list)
    for unit in units:
        by_source[unit.source].append(unit)
    for source_units in by_source.values():
        old_module = source_units[0].item.module
        targets = {
            unit.target
            for unit in source_units
            if unit.item.parent_id is None and unit.action != "delete"
        }
        if len(targets) == 1 and not any(
            unit.action == "assemble" for unit in source_units
        ):
            target = next(iter(targets))
            if target != old_module:
                moves[old_module] = target
        public: list[str] = []
        for unit in source_units:
            if unit.item.parent_id is not None or unit.action == "delete":
                continue
            for item in unit.items:
                if item.kind in {"class", "function", "assignment", "export"}:
                    if not item.name.startswith("_"):
                        public.append(item.name)
                    if unit.target != old_module and item.kind != "export":
                        moves[f"{old_module}.{item.name}"] = unit.target
            if isinstance(unit.node, (ast.Import, ast.ImportFrom)):
                for alias in unit.node.names:
                    if alias.name == "*":
                        continue
                    bound = alias.asname or (
                        alias.name.split(".")[0]
                        if isinstance(unit.node, ast.Import)
                        else alias.name
                    )
                    if not bound.startswith("_"):
                        public.append(bound)
                    if unit.target != old_module:
                        moves[f"{old_module}.{bound}"] = unit.target
        all_assignments = [
            unit.node
            for unit in source_units
            if any(item.name == "__all__" for item in unit.items)
        ]
        if all_assignments:
            if len(all_assignments) != 1 or not isinstance(
                all_assignments[0], ast.Assign
            ):
                continue  # Star imports fail closed without static exports.
            try:
                literal = ast.literal_eval(all_assignments[0].value)
            except (ValueError, TypeError, SyntaxError):
                continue
            if not isinstance(literal, (list, tuple)) or not all(
                isinstance(name, str) for name in literal
            ):
                continue
            exports[old_module] = list(literal)
        else:
            exports[old_module] = list(dict.fromkeys(public))
    return moves, exports


def _validate_exports(units: Sequence[Any]) -> None:
    """A retained __all__ must not advertise names moved to another module."""
    by_source: dict[Path, list[Any]] = defaultdict(list)
    for unit in units:
        by_source[unit.source].append(unit)
    for source_units in by_source.values():
        bound: dict[str, set[str]] = defaultdict(set)
        for unit in source_units:
            if unit.item.parent_id is not None or unit.action == "delete":
                continue
            for item in unit.items:
                if item.kind in {"class", "function", "assignment"}:
                    bound[item.name].add(unit.target)
            if isinstance(unit.node, (ast.Import, ast.ImportFrom)):
                for alias in unit.node.names:
                    if alias.name != "*":
                        name = alias.asname or (
                            alias.name.split(".")[0]
                            if isinstance(unit.node, ast.Import)
                            else alias.name
                        )
                        bound[name].add(unit.target)
        for unit in source_units:
            if unit.action == "delete" or not any(
                item.name == "__all__" for item in unit.items
            ):
                continue
            if not isinstance(unit.node, ast.Assign):
                raise ReferencePlanError(
                    f"dynamic __all__ cannot be proven: {unit.item.id}"
                )
            try:
                names = ast.literal_eval(unit.node.value)
            except (ValueError, TypeError, SyntaxError) as error:
                raise ReferencePlanError(
                    f"dynamic __all__ cannot be proven: {unit.item.id}"
                ) from error
            if not isinstance(names, (list, tuple)) or not all(
                isinstance(name, str) for name in names
            ):
                raise ReferencePlanError(
                    f"dynamic __all__ cannot be proven: {unit.item.id}"
                )
            for name in names:
                if bound[name] != {unit.target}:
                    raise ReferencePlanError(
                        f"export {name} in {unit.item.id} is not bound in {unit.target}"
                    )


def rewrite_staged(
    root: Path,
    staged: dict[Path, str | None],
    units: Sequence[Any],
) -> dict[Path, str | None]:
    """Stage rewrites in src, tests, scripts and alembic, without writing."""
    _validate_exports(units)
    destinations, exports = reference_map(units)
    symbol_paths = set(destinations) - {unit.item.module for unit in units}
    sources: dict[str, set[str]] = defaultdict(set)
    for unit in units:
        if unit.action != "delete":
            sources[unit.target].add(module_context(unit.source, root))
    mixin_methods = {
        unit.item.name.rsplit(".", 1)[-1]: unit.target_class
        for unit in units
        if unit.item.kind == "method"
        and unit.item.name.startswith("DatabaseORM.")
        and unit.target_class
        and unit.action == "move"
    }
    rewritten = dict(staged)
    inspected = dict(staged)
    for path, content in staged.items():
        if content is None:
            continue
        module = module_context(path, root)
        origins = sources[module.removesuffix(".__init__")]
        if len(origins) > 1 and any(
            isinstance(node, ast.ImportFrom) and node.level
            for node in ast.walk(ast.parse(content))
        ):
            raise ReferencePlanError(
                f"relative imports from multiple source modules: {module}"
            )
        origin = next(iter(origins)) if origins else module
        try:
            changed = (
                rewrite_moved_file(
                    content,
                    origin,
                    module,
                    destinations,
                    exports,
                    symbol_paths=symbol_paths,
                )
                if origin != module
                else rewrite_file(
                    content,
                    module,
                    destinations,
                    exports,
                    symbol_paths=symbol_paths,
                )
            )
            changed = rewrite_database_orm_refs(changed, mixin_methods)
            owners = set(mixin_methods.values())
            for cls in (
                node
                for node in ast.walk(ast.parse(changed))
                if isinstance(node, ast.ClassDef)
            ):
                if cls.name in owners and any(
                    isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Load)
                    and node.id == "DatabaseORM"
                    for node in ast.walk(cls)
                ):
                    raise ReferencePlanError(
                        f"unresolved DatabaseORM self reference in {path}:{cls.name}"
                    )
            rewritten[path] = changed
            inspected[path] = changed
        except (RewriteError, SyntaxError) as error:
            raise ReferencePlanError(f"cannot rewrite {path}: {error}") from error
    for dirname in ("src", "tests", "scripts", "alembic"):
        directory = root / dirname
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.py"):
            if path in rewritten:
                continue
            source = path.read_text(encoding="utf-8")
            try:
                changed = rewrite_file(
                    source,
                    module_context(path, root),
                    destinations,
                    exports,
                    symbol_paths=symbol_paths,
                )
            except (RewriteError, SyntaxError) as error:
                raise ReferencePlanError(f"cannot rewrite {path}: {error}") from error
            inspected[path] = changed
            if changed != source:
                rewritten[path] = changed
    deleted_modules = {
        module_context(path, root).removesuffix(".__init__")
        for path, content in staged.items()
        if content is None
    }
    for path, content in inspected.items():
        if content is None:
            continue
        for node in ast.walk(ast.parse(content, filename=str(path))):
            if isinstance(node, ast.Import) and any(
                alias.name in deleted_modules for alias in node.names
            ):
                raise ReferencePlanError(
                    f"import still points to removed module: {path}:{node.lineno}"
                )
            if isinstance(node, ast.ImportFrom) and node.module in deleted_modules:
                raise ReferencePlanError(
                    f"import still points to removed module: {path}:{node.lineno}"
                )
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = (
                function.attr
                if isinstance(function, ast.Attribute)
                else (function.id if isinstance(function, ast.Name) else "")
            )
            receiver = (
                function.value.id
                if isinstance(function, ast.Attribute)
                and isinstance(function.value, ast.Name)
                else ""
            )
            if not (
                (name == "import_module" and receiver == "importlib")
                or (name == "setattr" and receiver == "monkeypatch")
                or (name == "run" and receiver == "uvicorn")
                or name in {"patch", "add_job"}
            ):
                continue
            for argument in (*node.args, *(keyword.value for keyword in node.keywords)):
                literals = (
                    [argument.value]
                    if isinstance(argument, ast.Constant)
                    else (
                        [
                            part.value
                            for part in argument.values
                            if isinstance(part, ast.Constant)
                        ]
                        if isinstance(argument, ast.JoinedStr)
                        else []
                    )
                )
                for value in literals:
                    if isinstance(value, str) and any(
                        value == old or value.startswith((old + ".", old + ":"))
                        for old in deleted_modules
                    ):
                        raise ReferencePlanError(
                            f"callable path still points to removed module: {path}:{node.lineno}"
                        )
    return rewritten
