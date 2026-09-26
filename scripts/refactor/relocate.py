"""Preflight and stage reviewed, mechanical Python relocations.

The generated mapping is NOT authorization to move application code. Invoke this
only on an explicitly reviewed set of source modules. ``--apply`` is required to
write: the default prints the staged paths without changing any file.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import json
import os
import stat
import tempfile
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from scripts.refactor.cycles import new_cycles, project_modules
from scripts.refactor.inventory import Item, inventory, module_name
from scripts.refactor.relocation_refs import (
    ReferencePlanError,
    module_context,
    reference_map,
    rewrite_staged,
)


class RelocationError(ValueError):
    """A relocation could not be proven complete and safe."""


@dataclass(frozen=True)
class Unit:
    """One indivisible source AST statement, possibly binding several names."""

    items: tuple[Item, ...]
    target: str
    action: str
    target_class: str | None
    source: Path
    text: str
    node: ast.stmt

    @property
    def item(self) -> Item:
        return self.items[0]


def _target_path(root: Path, module: str) -> Path:
    if not module.startswith("app."):
        raise RelocationError(f"non-app target module: {module}")
    base = root / "src" / Path(*module.split("."))
    if base.is_dir():
        return base / "__init__.py"
    return base.with_suffix(".py")


def _slice(lines: list[str], item: Item) -> str:
    return "\n".join(lines[item.start_line - 1 : item.end_line]) + "\n"


def _nodes_by_unit(path: Path, items: list[Item]) -> dict[str, ast.stmt]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes: dict[str, ast.stmt] = {}
    by_span: dict[tuple[int, int], ast.stmt] = {}

    def add_children(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            by_span[(node.lineno, node.end_lineno)] = node
            if isinstance(node, ast.ClassDef):
                add_children(node.body)

    add_children(tree.body)
    for item in items:
        node = by_span.get((item.start_line, item.end_line))
        if node is None or ast.dump(node, include_attributes=False) != item.ast:
            # Leading comments and decorators shift the recorded start. AST
            # identity disambiguates a parent class and its final child.
            node = next(
                (
                    candidate
                    for candidate in by_span.values()
                    if candidate.end_lineno == item.end_line
                    and candidate.lineno >= item.start_line
                    and ast.dump(candidate, include_attributes=False) == item.ast
                ),
                None,
            )
        if node is None:
            raise RelocationError(f"cannot match AST unit: {item.id}")
        if item.unit_id in nodes and nodes[item.unit_id] is not node:
            raise RelocationError(f"source span collision: {item.unit_id}")
        nodes[item.unit_id] = node
    return nodes


def _units(path: Path, root: Path, mapping: dict[str, dict]) -> list[Unit]:
    items = inventory([path], root=root)
    prefix = module_name(path, root) + ":"
    missing = sorted(item.id for item in items if item.id not in mapping)
    stale = sorted(
        key
        for key in mapping
        if key.startswith(prefix) and key not in {i.id for i in items}
    )
    if missing or stale:
        raise RelocationError(
            f"unmapped or stale source items: missing={missing[:5]}, stale={stale[:5]}"
        )
    by_unit: dict[str, list[Item]] = defaultdict(list)
    for item in items:
        by_unit[item.unit_id].append(item)
    lines = path.read_text(encoding="utf-8").splitlines()
    nodes = _nodes_by_unit(path, items)
    results: list[Unit] = []
    for members in by_unit.values():
        instructions = [mapping[item.id] for item in members]
        decisions = {
            (record.get("target"), record.get("action", "move"), record.get("class"))
            for record in instructions
        }
        if len(decisions) != 1:
            raise RelocationError(
                f"one assignment has conflicting destinations: {[i.id for i in members]}"
            )
        target, action, target_class = decisions.pop()
        if (target == "TODO" and action != "delete") or (
            action in {"move", "assemble"}
            and (not isinstance(target, str) or not target.startswith("app."))
        ):
            raise RelocationError(f"unreviewed item: {members[0].id}")
        if action not in {"move", "delete", "assemble", "manual"}:
            raise RelocationError(f"unknown action: {members[0].id}: {action}")
        if action == "manual":
            continue
        if action == "delete" and not all(
            record.get("reason", "").strip() for record in instructions
        ):
            raise RelocationError(f"deletion without reason: {members[0].id}")
        if action == "assemble" and (len(members) != 1 or members[0].kind != "class"):
            raise RelocationError(
                f"only a class parent may be assembled: {members[0].id}"
            )
        results.append(
            Unit(
                tuple(members),
                target or "",
                action,
                target_class,
                path,
                _slice(lines, members[0]),
                nodes[members[0].unit_id],
            )
        )
    return sorted(results, key=lambda unit: (unit.item.start_line, unit.item.end_line))


def _validate_parents(units: list[Unit]) -> None:
    by_id = {item.id: unit for unit in units for item in unit.items}
    for unit in units:
        parent = unit.item.parent_id
        if parent is None:
            continue
        owner = by_id.get(parent)
        if owner is None:
            raise RelocationError(f"unmapped parent of {unit.item.id}: {parent}")
        if owner.action == "delete" and unit.action != "delete":
            raise RelocationError(f"deleted parent retains a child: {unit.item.id}")
        if owner.action == "assemble":
            if (
                unit.action == "move"
                and unit.target != owner.target
                and not unit.target_class
            ):
                raise RelocationError(
                    f"split class member without target class: {unit.item.id}"
                )
        elif owner.action == "move" and (
            owner.target != unit.target or unit.action != "move"
        ):
            raise RelocationError(
                f"overlapping class and member mappings: {unit.item.id}"
            )


def _validate_target_bindings(units: list[Unit]) -> None:
    """Never merge distinct source definitions under one Python binding."""
    bindings: dict[tuple[str, str], set[Path]] = defaultdict(set)
    for unit in units:
        if unit.action == "delete":
            continue
        if unit.item.parent_id is None:
            for item in unit.items:
                if item.kind in {"class", "function", "assignment", "export"}:
                    bindings[(unit.target, item.name)].add(unit.source)
        if unit.target_class and unit.item.parent_id:
            bindings[(unit.target, unit.target_class)].add(unit.source)
    conflicts = [
        (module, name) for (module, name), owners in bindings.items() if len(owners) > 1
    ]
    if conflicts:
        raise RelocationError(
            f"target name collision across sources: {sorted(conflicts)}"
        )


def _module_writes(unit: Unit) -> set[str]:
    if unit.item.parent_id is not None or unit.action != "move":
        return set()
    if unit.item.kind in {"assignment", "export"}:
        return {item.name for item in unit.items}
    if unit.item.kind != "statement":
        return set()
    writes: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                writes.add(node.id)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            pass  # assignments inside a function are not module-level writes

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_ClassDef = visit_FunctionDef
        visit_Lambda = visit_FunctionDef

    Visitor().visit(unit.node)
    return writes


def _validate_globals(units: list[Unit]) -> None:
    assignments: dict[tuple[Path, str], set[str]] = defaultdict(set)
    for unit in units:
        for name in _module_writes(unit):
            assignments[(unit.source, name)].add(unit.target)
    for (source, name), targets in assignments.items():
        if len(targets) > 1:
            raise RelocationError(
                f"split module-level rebinding {source}:{name}: {sorted(targets)}"
            )
    for unit in units:
        if unit.action != "move":
            continue
        for node in ast.walk(unit.node):
            if not isinstance(node, ast.Global):
                continue
            for name in node.names:
                key = (unit.source, name)
                if key in assignments and unit.target not in assignments[key]:
                    raise RelocationError(
                        f"split global rebinding {name}: {unit.item.id} vs "
                        f"{sorted(assignments[key])}"
                    )


def _source_imports(
    units: list[Unit], exports: dict[str, list[str]], root: Path
) -> dict[str, tuple[str, int]]:
    imports: dict[str, tuple[str, int]] = {}
    for unit in units:
        if unit.item.parent_id is not None or not isinstance(
            unit.node, (ast.Import, ast.ImportFrom)
        ):
            continue
        node = unit.node
        for alias in node.names:
            if alias.name == "*":
                if not isinstance(node, ast.ImportFrom):
                    raise RelocationError(
                        f"star import has no source module: {unit.item.id}"
                    )
                context = module_context(unit.source, root)
                package = context.split(".")[:-1]
                if node.level > len(package):
                    raise RelocationError(
                        f"star import escapes source package: {unit.item.id}"
                    )
                base = package[: len(package) - node.level + 1] if node.level else []
                source_module = (
                    ".".join([*base, *(node.module or "").split(".")]).rstrip(".")
                    if node.level
                    else node.module
                )
                names = exports.get(source_module or "")
                if names is None:
                    raise RelocationError(
                        f"star import has no static exports: {unit.item.id}"
                    )
                for name in names:
                    imports[name] = (
                        f"from {'.' * node.level}{node.module or ''} import {name}",
                        unit.item.start_line,
                    )
                continue
            name = alias.asname or (
                alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name
            )
            if isinstance(node, ast.ImportFrom):
                prefix = "." * node.level + (node.module or "")
                statement = f"from {prefix} import {alias.name}"
            else:
                statement = f"import {alias.name}"
            if alias.asname:
                statement += f" as {alias.asname}"
            imports[name] = (statement, unit.item.start_line)
    return imports


def _defined_names(units: list[Unit]) -> dict[str, str]:
    definitions = {
        item.name: unit.target
        for unit in units
        if unit.item.parent_id is None and unit.action in {"move", "assemble"}
        for item in unit.items
        if item.kind in {"function", "class", "assignment", "export"}
    }
    for unit in units:
        for name in _module_writes(unit):
            definitions[name] = unit.target
    return definitions


def _references(node: ast.AST) -> set[str]:
    """Resolve globals in each lexical scope, not by unioning all local stores."""
    import symtable

    try:
        source = ast.unparse(node)
        table = symtable.symtable(source, "<relocation unit>", "exec")
    except (SyntaxError, ValueError) as error:
        raise RelocationError(f"cannot resolve unit names: {error}") from error
    required: set[str] = set()

    def walk(scope: symtable.SymbolTable) -> None:
        for symbol in scope.get_symbols():
            if symbol.is_referenced() and symbol.is_global():
                required.add(symbol.get_name())
        for child in scope.get_children():
            walk(child)

    walk(table)
    return required - set(dir(builtins))


def _imports_for(
    unit: Unit,
    imports: dict[str, tuple[str, int]],
    definitions: dict[str, str],
    present: set[str],
) -> list[tuple[str, int]]:
    required: list[tuple[str, int]] = []
    locally_imported = {
        alias.asname
        or (alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name)
        for node in ast.walk(unit.node)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
        if alias.name != "*"
    }
    for name in sorted(_references(unit.node)):
        if (
            name == "__file__"
            and unit.item.id == "app.config:Settings"
            and unit.target == "app.core.config"
        ):
            # DATA_PATH is adjusted when rendering the moved config module.
            continue
        if name in present or name in locally_imported:
            continue
        if (
            name == "DatabaseORM"
            and unit.target_class
            and unit.item.name.startswith("DatabaseORM.")
        ):
            # The reviewed self-reference rewrite resolves this name inside
            # its owning mixin. A leftover reference is rejected after rewrite.
            continue
        if name in imports:
            required.append(imports[name])
        elif name in definitions and definitions[name] != unit.target:
            required.append(
                (f"from {definitions[name]} import {name}", unit.item.start_line)
            )
        elif name not in definitions:
            raise RelocationError(f"unresolved name {name} in {unit.item.id}")
    return required


def _top_level_names(node: ast.stmt) -> set[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return {
            name.id
            for target in targets
            for name in ast.walk(target)
            if isinstance(name, ast.Name)
        }
    return set()


def _module_import_bindings(tree: ast.Module) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        for alias in node.names:
            name = alias.asname or (
                alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name
            )
            statement = ast.unparse(node)
            if name in bindings and bindings[name] != statement:
                raise RelocationError(
                    f"ambiguous import binding {name}: {bindings[name]} / {statement}"
                )
            bindings[name] = statement
    return bindings


def _merge_existing_destination(
    destination: Path, existing: str, generated: str
) -> str:
    existing_tree = ast.parse(existing, filename=str(destination))
    generated_tree = ast.parse(generated, filename=str(destination))
    # A future import is a module-wide compiler directive, not an ordinary
    # runtime import. Adding it after existing definitions is invalid Python;
    # moving it to the top would change their annotation/evaluation semantics.
    existing_future = {
        alias.name
        for node in existing_tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
        for alias in node.names
    }
    generated_future = {
        alias.name
        for node in generated_tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
        for alias in node.names
    }
    if generated_future - existing_future:
        raise RelocationError(
            f"new future directive would change existing module {destination}: "
            f"{sorted(generated_future - existing_future)}"
        )
    old_bindings = _module_import_bindings(existing_tree)
    new_bindings = _module_import_bindings(generated_tree)
    conflicting_bindings = {
        name: (old_bindings[name], new_bindings[name])
        for name in old_bindings.keys() & new_bindings.keys()
        if old_bindings[name] != new_bindings[name]
    }
    if conflicting_bindings:
        raise RelocationError(
            f"destination import binding collision in {destination}: {conflicting_bindings}"
        )
    existing_names = set().union(
        *(_top_level_names(node) for node in existing_tree.body)
    )
    generated_names = set().union(
        *(_top_level_names(node) for node in generated_tree.body)
    )
    conflicts = sorted(existing_names & generated_names)
    if conflicts:
        raise RelocationError(
            f"destination symbol collision in {destination}: {conflicts}"
        )
    unsupported = [
        type(node).__name__
        for node in existing_tree.body
        if not isinstance(
            node,
            (
                ast.Import,
                ast.ImportFrom,
                ast.Assign,
                ast.AnnAssign,
                ast.ClassDef,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.Expr,
            ),
        )
    ]
    if unsupported:
        raise RelocationError(
            f"cannot safely merge executable nodes into {destination}: {unsupported}"
        )
    existing_imports = {
        ast.unparse(node)
        for node in existing_tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    }
    imports = [
        ast.unparse(node)
        for node in generated_tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and not (isinstance(node, ast.ImportFrom) and node.module == "__future__")
        and ast.unparse(node) not in existing_imports
    ]
    generated_lines = generated.splitlines()
    definitions = []
    for node in generated_tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue
        definitions.append(
            "\n".join(generated_lines[node.lineno - 1 : node.end_lineno])
        )
    additions = [*imports, *definitions]
    if not additions:
        return existing
    return existing.rstrip() + "\n\n" + "\n\n".join(additions) + "\n"


def plan(
    root: Path, sources: list[Path], mapping: dict[str, dict]
) -> dict[Path, str | None]:
    """Return all staged file content after preflight; never write here."""
    root = root.resolve()
    source_paths = [
        (root / source).resolve() if not source.is_absolute() else source.resolve()
        for source in sources
    ]
    for path in source_paths:
        if not path.is_file() or not path.is_relative_to(root / "src" / "app"):
            raise RelocationError(f"source outside app package: {path}")
    all_units = [
        unit for path in sorted(source_paths) for unit in _units(path, root, mapping)
    ]
    if not all_units:
        raise RelocationError(
            "no inventoried statements; refusing to remove an empty package"
        )
    _validate_parents(all_units)
    _validate_target_bindings(all_units)
    _validate_globals(all_units)
    _moves, exports = reference_map(all_units)
    original_imports = {
        path: _source_imports(
            [unit for unit in all_units if unit.source == path], exports, root
        )
        for path in source_paths
    }
    definitions = {
        path: _defined_names([unit for unit in all_units if unit.source == path])
        for path in source_paths
    }
    present_imports: dict[tuple[Path, str], set[str]] = defaultdict(set)
    for unit in all_units:
        if unit.action == "move" and unit.item.kind in {"import", "package_import"}:
            present_imports[(unit.source, unit.target)].update(
                name
                for name, (_statement, line) in original_imports[unit.source].items()
                if line == unit.item.start_line
            )
    rendered: dict[str, list[tuple[int, str]]] = defaultdict(list)
    generated: dict[str, dict[str, int]] = defaultdict(dict)
    docstrings: dict[str, str] = {}

    def add_imports(module: str, pairs: list[tuple[str, int]]) -> None:
        for statement, line in pairs:
            current = generated[module].get(statement)
            generated[module][statement] = (
                min(line, current) if current is not None else line
            )

    for source in source_paths:
        source_units = [unit for unit in all_units if unit.source == source]
        futures = [
            (unit.text.strip(), unit.item.start_line)
            for unit in source_units
            if isinstance(unit.node, ast.ImportFrom)
            and unit.node.module == "__future__"
        ]
        for target in {unit.target for unit in source_units if unit.action != "delete"}:
            add_imports(target, futures)
    top_classes = {
        unit.item.id: unit for unit in all_units if unit.item.kind == "class"
    }
    split_members: dict[tuple[str, str], list[Unit]] = defaultdict(list)
    mixin_bases: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for unit in all_units:
        if unit.action == "delete":
            continue
        parent = unit.item.parent_id
        if (
            parent
            and top_classes.get(parent, None)
            and top_classes[parent].action == "move"
        ):
            continue  # copied exactly once with the whole class
        if (
            parent
            and top_classes.get(parent, None)
            and top_classes[parent].action == "assemble"
        ):
            if unit.action == "assemble":
                raise RelocationError(f"nested assembly not supported: {unit.item.id}")
            if unit.target_class:
                split_members[(unit.target, unit.target_class)].append(unit)
                base = (unit.target, unit.target_class)
                if base not in mixin_bases[parent]:
                    mixin_bases[parent].append(base)
                continue
            # Retained attributes and docstrings are rendered in the newly
            # assembled parent class, not as indented top-level statements.
            continue
        if unit.action == "assemble":
            if not isinstance(unit.node, ast.ClassDef) or unit.node.decorator_list:
                raise RelocationError(
                    f"decorated or non-class assembly: {unit.item.id}"
                )
            continue
        if unit.item.kind == "docstring":
            if unit.target in docstrings:
                raise RelocationError(
                    f"multiple module docstrings mapped to {unit.target}"
                )
            docstrings[unit.target] = unit.text.strip()
        else:
            rendered[unit.target].append((unit.item.start_line, unit.text))
        add_imports(
            unit.target,
            _imports_for(
                unit,
                original_imports[unit.source],
                definitions[unit.source],
                present_imports[(unit.source, unit.target)],
            ),
        )
    for (target, cls), members in split_members.items():
        members.sort(key=lambda item: item.item.start_line)
        body = "\n".join(unit.text.rstrip("\n") for unit in members)
        rendered[target].append((members[0].item.start_line, f"class {cls}:\n{body}\n"))
        for unit in members:
            add_imports(
                target,
                _imports_for(
                    unit,
                    original_imports[unit.source],
                    definitions[unit.source],
                    present_imports[(unit.source, unit.target)],
                ),
            )
    for parent, owner in top_classes.items():
        if owner.action == "assemble" and parent not in mixin_bases:
            raise RelocationError(f"assembled class has no mixins: {parent}")
    for parent, bases in mixin_bases.items():
        owner = top_classes[parent]
        if any(module == owner.target for module, _cls in bases):
            raise RelocationError(
                f"mixin cannot share its assembled class module: {parent}"
            )
        if not isinstance(owner.node, ast.ClassDef):
            raise RelocationError(f"assembled parent is not a class: {parent}")
        if any(
            not isinstance(base, (ast.Name, ast.Attribute)) for base in owner.node.bases
        ):
            raise RelocationError(f"assembled class has nontrivial bases: {parent}")
        imports = [
            f"from {module} import {cls}"
            for module, cls in bases
            if module != owner.target
        ]
        add_imports(
            owner.target, [(statement, owner.item.start_line) for statement in imports]
        )
        retained = [
            unit
            for unit in all_units
            if unit.item.parent_id == parent
            and unit.target == owner.target
            and unit.action == "move"
        ]
        body = [unit.text.rstrip("\n") for unit in retained]
        for unit in retained:
            add_imports(
                owner.target,
                _imports_for(
                    unit,
                    original_imports[unit.source],
                    definitions[unit.source],
                    present_imports[(unit.source, unit.target)],
                ),
            )
        original_bases = [ast.unparse(base) for base in owner.node.bases]
        keywords = [ast.unparse(keyword) for keyword in owner.node.keywords]
        header_names = _references(
            ast.Tuple(
                elts=[*owner.node.bases, *(word.value for word in owner.node.keywords)],
                ctx=ast.Load(),
            )
        )
        for name in header_names:
            if name in original_imports[owner.source]:
                add_imports(owner.target, [original_imports[owner.source][name]])
            elif name in definitions[owner.source]:
                source_module = definitions[owner.source][name]
                if source_module != owner.target:
                    add_imports(
                        owner.target,
                        [
                            (
                                f"from {source_module} import {name}",
                                owner.item.start_line,
                            )
                        ],
                    )
            else:
                raise RelocationError(
                    f"unresolved assembled class base {name}: {parent}"
                )
        header = ", ".join([*(cls for _, cls in bases), *original_bases, *keywords])
        text = f"class {owner.item.name}({header}):\n" + (
            "\n".join(body) + "\n" if body else "    pass\n"
        )
        rendered[owner.target].append((owner.item.start_line, text))
    staged: dict[Path, str | None] = {}
    for module in sorted(set(rendered) | set(docstrings)):
        chunks = rendered[module]
        destination = _target_path(root, module)
        existing = None
        if destination.exists() and destination not in source_paths:
            existing = destination.read_text(encoding="utf-8")
        ordered = [
            text.rstrip("\n") for _, text in sorted(chunks, key=lambda chunk: chunk[0])
        ]
        seen = {
            text.strip()
            for text in ordered
            if text.lstrip().startswith(("import ", "from "))
        }
        # Position generated imports by their original source order instead
        # of alphabetizing them above executable module initialization.
        additions = [
            (line, statement)
            for statement, line in generated[module].items()
            if statement not in seen
        ]
        merged = [(line, 1, text) for line, text in chunks]
        merged.extend((line, 0, statement) for line, statement in additions)
        ordered = [text.rstrip("\n") for _, _, text in sorted(merged)]
        future = [
            entry for entry in ordered if entry.startswith("from __future__ import ")
        ]
        ordered = [entry for entry in ordered if entry not in future]
        docstring = [docstrings[module]] if module in docstrings else []
        content = "\n\n".join([*docstring, *future, *ordered]) + "\n"
        if existing is not None:
            content = _merge_existing_destination(destination, existing, content)
        if module == "app.core.config":
            old_path = 'Path(__file__).parents[2] / "data"'
            if content.count(old_path) != 1:
                raise RelocationError(
                    "config DATA_PATH path anchor changed unexpectedly"
                )
            content = content.replace(old_path, 'Path(__file__).parents[3] / "data"', 1)
        try:
            ast.parse(content, filename=str(destination))
        except SyntaxError as error:
            raise RelocationError(
                f"rendered module is invalid: {destination}: {error}"
            ) from error
        staged[destination] = content
    for path in source_paths:
        if path not in staged:
            staged[path] = None
    try:
        staged = rewrite_staged(root, staged, all_units)
        staged = _remove_local_imports(root, staged)
    except ReferencePlanError as error:
        raise RelocationError(str(error)) from error
    moves, _exports = reference_map(all_units)
    introduced = new_cycles(project_modules(root), project_modules(root, staged), moves)
    if introduced:
        raise RelocationError(
            f"relocation creates an import cycle: {sorted(map(sorted, introduced))}"
        )
    return staged


def _remove_local_imports(
    root: Path, staged: dict[Path, str | None]
) -> dict[Path, str | None]:
    """Drop rewritten imports whose names are defined in their destination.

    This occurs when a previously separate module (e.g. models.Base and
    databases.session) is co-located. Never discard an import unless every
    requested symbol is visibly defined in the same module.
    """
    result = dict(staged)
    for path, content in staged.items():
        if content is None or not path.is_relative_to(root / "src"):
            continue
        module = module_name(path, root)
        tree = ast.parse(content, filename=str(path))
        bound: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                bound.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for target in targets:
                    bound.update(
                        n.id for n in ast.walk(target) if isinstance(n, ast.Name)
                    )
        removals: list[tuple[int, int]] = []
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom) or node.module != module:
                continue
            names = {alias.name for alias in node.names}
            if not names <= bound:
                raise RelocationError(
                    f"self import has no matching local definition: {path}: {names - bound}"
                )
            removals.append((node.lineno, node.end_lineno))
        if removals:
            lines = content.splitlines(keepends=True)
            for start, end in reversed(removals):
                del lines[start - 1 : end]
            result[path] = "".join(lines)
    return result


def apply(staged: dict[Path, str | None]) -> None:
    """Write staged files after all validation, restoring previous content on I/O errors."""
    originals = {path: path.read_bytes() if path.exists() else None for path in staged}
    temporary: dict[Path, Path] = {}
    try:
        for path, content in staged.items():
            if content is None:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as handle:
                handle.write(content)
                temporary[path] = Path(handle.name)
            if path.exists():
                os.chmod(temporary[path], stat.S_IMODE(path.stat().st_mode))
            else:
                os.chmod(temporary[path], 0o644)
        for path, temp in temporary.items():
            os.replace(temp, path)
        for path, content in staged.items():
            if content is None:
                path.unlink()
    except OSError:
        for path, original in originals.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(original)
        raise
    finally:
        for temp in temporary.values():
            temp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with args.mapping.open("rb") as handle:
        entries = tomllib.load(handle)["items"]
    mapping = {entry["id"]: entry for entry in entries}
    if len(mapping) != len(entries):
        parser.error("mapping has duplicate IDs")
    try:
        staged = plan(args.root, args.source, mapping)
    except RelocationError as error:
        parser.error(str(error))
    if args.apply:
        apply(staged)
    print(json.dumps([str(path) for path in sorted(staged)], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
