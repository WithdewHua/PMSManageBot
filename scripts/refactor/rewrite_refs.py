"""Pure, fail-closed reference rewriting for the backend relocation tool.

The public :func:`rewrite_file` API accepts a Python source string and never
reads or writes files::

    rewrite_file(source, module, destinations, exports=None) -> str

``module`` is the fully-qualified name of the source module.  ``destinations``
is a mapping from an original qualified module or symbol to its destination
*module*.  Module entries rewrite module prefixes, while symbol entries rewrite
``from module import symbol`` and callable references to the destination
module while retaining the symbol name.  For example::

    {"app.old": "app.new", "app.old.Foo": "app.domains.new"}

maps ``from app.old import Bar`` to ``from app.new import Bar`` and
``from app.old import Foo`` to ``from app.domains.new import Foo``.

``exports`` is an optional mapping from absolute module names to a static list
of exported names.  It is required when a rewritten star import is encountered
and is used to expand ``from module import *`` into explicit imports.  Dynamic,
missing, duplicate, or invalid export lists raise :class:`RewriteError` rather
than being guessed.

String paths are rewritten only in these recognized call contexts:

* ``monkeypatch.setattr`` and ``unittest.mock.patch`` (dotted callable paths),
* ``importlib.import_module`` (module paths),
* ``uvicorn.run`` (module paths and ``module:attribute`` paths), and
* APScheduler-style ``*.add_job`` (dotted or colon callable paths).

Other strings, including prose and docstrings, are left byte-for-byte alone.
The separate :func:`rewrite_moved_file` helper accepts
``source_module`` and ``target_module``. It resolves relative imports against
``source_module`` and emits absolute paths; unchanged siblings stay in their
original package unless explicitly listed in the destination map.  The separate
:func:`rewrite_database_orm_refs` helper rewrites ``DatabaseORM.method`` only
when the containing class is the reviewed mixin for that method.  Its map is
``method name -> mixin class name`` (qualified ``Mixin.method`` keys are
accepted too).
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


class RewriteError(ValueError):
    """Raised when a reference cannot be rewritten without guessing."""


_PATH_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")
_STRING_PREFIX_RE = re.compile(r"^(?P<prefix>[rRuUbB]*)(?P<quote>'''|\"\"\"|'|\")")


@dataclass(frozen=True)
class _Edit:
    start: int
    end: int
    replacement: str


class _Destinations:
    """Validated destination lookup with longest-prefix matching."""

    def __init__(
        self, destinations: Mapping[str, str], symbol_paths: set[str] | None = None
    ) -> None:
        if not isinstance(destinations, Mapping):
            raise TypeError("destinations must be a mapping")
        normalized: dict[str, str] = {}
        for original, destination in destinations.items():
            if not isinstance(original, str) or not _is_path(original):
                raise RewriteError(f"invalid original path: {original!r}")
            if not isinstance(destination, str) or not _is_path(destination):
                raise RewriteError(f"invalid destination module: {destination!r}")
            normalized[original] = destination
        self.mapping = normalized
        self.has_explicit_symbol_paths = symbol_paths is not None
        self.symbol_paths = symbol_paths or set()
        if self.symbol_paths - normalized.keys():
            raise RewriteError("symbol paths are missing from destinations")
        self._keys = tuple(sorted(normalized, key=len, reverse=True))

    def exact(self, path: str) -> str | None:
        return self.mapping.get(path)

    def lookup(self, path: str) -> str | None:
        for original in self._keys:
            if path == original:
                return self.mapping[original]
            prefix = f"{original}."
            if path.startswith(prefix):
                suffix = path[len(prefix) :]
                return f"{self.mapping[original]}.{suffix}"
        return None

    def has_descendant(self, path: str) -> bool:
        prefix = f"{path}."
        return any(original.startswith(prefix) for original in self.mapping)


def _is_path(value: str) -> bool:
    return bool(_PATH_RE.fullmatch(value))


def _validate_exports(exports: Mapping[str, Sequence[str]] | None) -> None:
    if exports is None:
        return
    if not isinstance(exports, Mapping):
        raise TypeError("exports must be a mapping or None")
    for module, names in exports.items():
        if not isinstance(module, str) or not _is_path(module):
            raise RewriteError(f"invalid exports module: {module!r}")
        if isinstance(names, (str, bytes)) or not isinstance(names, Sequence):
            raise RewriteError(
                f"exports for {module!r} must be a static sequence of names"
            )
        seen: set[str] = set()
        for name in names:
            if not isinstance(name, str) or not _is_path(name) or "." in name:
                raise RewriteError(f"invalid export {name!r} from {module!r}")
            if name in seen:
                raise RewriteError(f"duplicate export {name!r} from {module!r}")
            seen.add(name)


def _line_starts(source: str) -> list[int]:
    starts = [0]
    for match in re.finditer("\\n", source):
        starts.append(match.end())
    return starts


def _byte_column_to_character(line: str, column: int) -> int:
    """Convert an AST UTF-8 byte column to a Python string column."""
    if column <= 0:
        return 0
    encoded = line.encode("utf-8")
    if column > len(encoded):
        raise RewriteError("AST column is outside the source line")
    try:
        return len(encoded[:column].decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise RewriteError("AST column splits a UTF-8 character") from exc


def _span(source: str, starts: list[int], node: ast.AST) -> tuple[int, int]:
    if not all(
        hasattr(node, attribute)
        for attribute in ("lineno", "col_offset", "end_lineno", "end_col_offset")
    ):
        raise RewriteError(f"node has no source span: {type(node).__name__}")
    start_line = source.splitlines(keepends=True)[node.lineno - 1]
    end_line = source.splitlines(keepends=True)[node.end_lineno - 1]
    start_col = _byte_column_to_character(start_line, node.col_offset)
    end_col = _byte_column_to_character(end_line, node.end_col_offset)
    return starts[node.lineno - 1] + start_col, starts[node.end_lineno - 1] + end_col


def _move_relative_module(
    resolved_module: str,
    source_module: str,
    target_module: str,
) -> str:
    """Keep unreviewed sibling imports at their original absolute location.

    The destination table handles siblings explicitly moved in the same batch;
    blindly relocating all siblings invents imports of nonexistent modules.
    """
    return resolved_module


def _absolute_from_module(module: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        if node.module is None:
            raise RewriteError("absolute import has no module")
        return node.module

    package = module.split(".")[:-1]
    levels_up = node.level - 1
    if levels_up > len(package):
        raise RewriteError(
            f"relative import escapes package: {module!r}, level={node.level}"
        )
    if levels_up:
        package = package[:-levels_up]
    if node.module:
        package.extend(node.module.split("."))
    if not package:
        raise RewriteError(f"relative import has no resolvable package: {module!r}")
    return ".".join(package)


def _relative_module(destination: str, current_module: str) -> str:
    package = current_module.split(".")[:-1]
    target = destination.split(".")
    common = 0
    for current_part, target_part in zip(package, target):
        if current_part != target_part:
            break
        common += 1
    if common == 0:
        return destination
    level = len(package) - common + 1
    remainder = target[common:]
    dots = "." * level
    return f"{dots}{'.'.join(remainder)}" if remainder else dots


def _from_module_text(destination: str, current_module: str, was_relative: bool) -> str:
    if not was_relative:
        return destination
    return _relative_module(destination, current_module)


def _symbol_destination(
    table: _Destinations,
    source_module: str,
    name: str,
    *,
    fallback_module: str | None = None,
) -> str:
    qualified = f"{source_module}.{name}" if source_module else name
    exact = table.exact(qualified)
    if exact is not None:
        return exact
    module_destination = table.lookup(source_module)
    if module_destination is not None:
        return module_destination
    return fallback_module if fallback_module is not None else source_module


def _group_contiguous(
    values: Sequence[tuple[str, str | None]],
) -> list[tuple[str, list[str | None]]]:
    groups: list[tuple[str, list[str | None]]] = []
    for destination, name in values:
        if groups and groups[-1][0] == destination:
            groups[-1][1].append(name)
        else:
            groups.append((destination, [name]))
    return groups


def _alias_text(name: str, alias: str | None) -> str:
    return f"{name} as {alias}" if alias else name


def _render_from(
    destination: str,
    names: Sequence[str],
    *,
    current_module: str,
    was_relative: bool,
) -> str:
    module_text = _from_module_text(destination, current_module, was_relative)
    return f"from {module_text} import {', '.join(names)}"


def _leading_indent(source: str, start: int) -> str:
    line_start = source.rfind("\n", 0, start) + 1
    line = source[line_start:]
    return line[: len(line) - len(line.lstrip())]


def _render_replacement_lines(
    statements: Sequence[str],
    *,
    indent: str,
    newline: str,
) -> str:
    if not statements:
        raise RewriteError("cannot render an empty import replacement")
    return newline.join(
        statement if index == 0 else f"{indent}{statement}"
        for index, statement in enumerate(statements)
    )


def _rewrite_import(
    source: str,
    starts: list[int],
    node: ast.Import | ast.ImportFrom,
    *,
    module: str,
    table: _Destinations,
    exports: Mapping[str, Sequence[str]] | None,
    newline: str,
    target_module: str | None,
) -> _Edit | None:
    start, end = _span(source, starts, node)
    indent = _leading_indent(source, start)

    if isinstance(node, ast.Import):
        rendered: list[str] = []
        changed = False
        for alias in node.names:
            destination = table.lookup(alias.name) or alias.name
            changed = changed or destination != alias.name
            rendered.append(_alias_text(destination, alias.asname))
        if not changed:
            return None
        statements = [f"import {alias}" for alias in rendered]
        return _Edit(
            start,
            end,
            _render_replacement_lines(statements, indent=indent, newline=newline),
        )

    source_module = _absolute_from_module(module, node)
    fallback_module = source_module
    force_absolute = False
    if target_module is not None and node.level > 0:
        fallback_module = _move_relative_module(
            source_module,
            module,
            target_module,
        )
        force_absolute = True
    values = node.names
    if len(values) == 1 and values[0].name == "*":
        module_destination = table.lookup(source_module) or fallback_module
        needs_rewrite = (
            module_destination != source_module
            or table.has_descendant(source_module)
            or force_absolute
        )
        if not needs_rewrite:
            return None
        names = _static_exports(exports, source_module)
        grouped = _group_contiguous(
            [
                (
                    _symbol_destination(
                        table,
                        source_module,
                        name,
                        fallback_module=fallback_module,
                    ),
                    name,
                )
                for name in names
            ]
        )
        statements = [
            _render_from(
                destination,
                [name for name in group_names if name is not None],
                current_module=module,
                was_relative=node.level > 0 and not force_absolute,
            )
            for destination, group_names in grouped
        ]
        return _Edit(
            start,
            end,
            _render_replacement_lines(statements, indent=indent, newline=newline),
        )

    destinations: list[tuple[str, str]] = []
    for alias in values:
        qualified = f"{source_module}.{alias.name}"
        destination = _symbol_destination(
            table, source_module, alias.name, fallback_module=fallback_module
        )
        if (
            table.has_explicit_symbol_paths
            and table.exact(qualified)
            and qualified not in table.symbol_paths
        ):
            # ``from app import blackjack_engine as engine`` imports a module,
            # not a symbol named blackjack_engine in the destination module.
            # Preserve its binding as ``from app.domains.blackjack import rules as engine``.
            parent, leaf = destination.rsplit(".", 1)
            binding = alias.asname or alias.name
            destinations.append((parent, _alias_text(leaf, binding)))
        else:
            destinations.append((destination, _alias_text(alias.name, alias.asname)))
    if (
        not any(destination != source_module for destination, _ in destinations)
        and not force_absolute
    ):
        return None
    grouped = _group_contiguous(destinations)
    statements = [
        _render_from(
            destination,
            [name for name in group_names if name is not None],
            current_module=module,
            was_relative=node.level > 0 and not force_absolute,
        )
        for destination, group_names in grouped
    ]
    return _Edit(
        start,
        end,
        _render_replacement_lines(statements, indent=indent, newline=newline),
    )


def _static_exports(
    exports: Mapping[str, Sequence[str]] | None, module: str
) -> list[str]:
    if exports is None or module not in exports:
        raise RewriteError(
            f"cannot expand star import from {module!r} without static exports"
        )
    names = list(exports[module])
    if not names:
        raise RewriteError(f"star import from {module!r} has no static exports")
    return names


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else None
    return None


def _call_kind(call: ast.Call) -> str | None:
    path = _dotted_name(call.func)
    if path is None:
        return None
    if path in {
        "monkeypatch.setattr",
        "mocker.setattr",
        "pytest.MonkeyPatch.setattr",
    }:
        return "callable"
    if path == "patch" or path.endswith((".mock.patch", ".patch")):
        return "callable"
    if path in {"importlib.import_module", "import_module"}:
        return "module"
    if path == "uvicorn.run":
        return "colon"
    if path == "add_job" or path.endswith(".add_job"):
        return "colon"
    return None


def _call_target(call: ast.Call, kind: str) -> ast.Constant | None:
    keyword_names = {
        "callable": {"target"},
        "module": {"name"},
        "colon": {"app", "func"},
    }[kind]
    for keyword in call.keywords:
        if keyword.arg in keyword_names and isinstance(keyword.value, ast.Constant):
            if isinstance(keyword.value.value, str):
                return keyword.value
            return None
    if (
        call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    ):
        return call.args[0]
    return None


def _rewrite_module_reference(value: str, table: _Destinations) -> str:
    if not _is_path(value):
        return value
    return table.lookup(value) or value


def _rewrite_colon_reference(value: str, table: _Destinations) -> str:
    if value.count(":") != 1:
        return value
    module_name, attribute = value.split(":")
    if not _is_path(module_name) or not _is_path(attribute):
        return value
    symbol_destination = table.exact(f"{module_name}.{attribute}")
    if symbol_destination is not None:
        return f"{symbol_destination}:{attribute}"
    module_destination = table.lookup(module_name)
    if module_destination is not None:
        return f"{module_destination}:{attribute}"
    return value


def _rewrite_callable_reference(value: str, table: _Destinations) -> str:
    if ":" in value:
        return _rewrite_colon_reference(value, table)
    if not _is_path(value):
        return value

    exact = table.exact(value)
    if exact is not None:
        leaf = value.rsplit(".", 1)[-1]
        if exact == value or exact.endswith(f".{leaf}"):
            return exact
        return f"{exact}.{leaf}"
    for original in sorted(table.mapping, key=len, reverse=True):
        if not value.startswith(original + "."):
            continue
        remainder = value[len(original) + 1 :]
        destination = table.exact(original)
        if destination is not None and original in table.symbol_paths:
            # Symbol mappings name the destination module; member lookups
            # still need the moved symbol before the rest of the path.
            leaf = original.rsplit(".", 1)[-1]
            return f"{destination}.{leaf}.{remainder}"
        mapped = table.lookup(original)
        if mapped is not None:
            return f"{mapped}.{remainder}"
    return value


def _rewrite_literal(
    source: str, starts: list[int], node: ast.Constant, value: str
) -> _Edit:
    start, end = _span(source, starts, node)
    literal = source[start:end]
    match = _STRING_PREFIX_RE.match(literal)
    if match is None:
        raise RewriteError("recognized path is not a plain string literal")
    prefix = match.group("prefix")
    quote = match.group("quote")
    quote_character = quote[0]
    body = value.replace("\\", "\\\\")
    body = body.replace(quote_character, f"\\{quote_character}")
    if "r" in prefix.lower() and ("\\" in value or quote_character in value):
        prefix = prefix.replace("r", "").replace("R", "")
    return _Edit(start, end, f"{prefix}{quote}{body}{quote}")


def _string_edits(
    source: str,
    starts: list[int],
    tree: ast.AST,
    table: _Destinations,
) -> list[_Edit]:
    edits: list[_Edit] = []
    for candidate in ast.walk(tree):
        if not isinstance(candidate, ast.Call):
            continue
        kind = _call_kind(candidate)
        if kind is None:
            continue
        literal = _call_target(candidate, kind)
        if literal is None:
            continue
        original = literal.value
        if not isinstance(original, str):
            continue
        if kind == "module":
            rewritten = _rewrite_module_reference(original, table)
        elif kind == "colon":
            rewritten = _rewrite_colon_reference(original, table)
            if rewritten == original and ":" not in original:
                rewritten = _rewrite_callable_reference(original, table)
        else:
            rewritten = _rewrite_callable_reference(original, table)
        if rewritten != original:
            edits.append(_rewrite_literal(source, starts, literal, rewritten))
    return edits


def _apply_edits(source: str, edits: Sequence[_Edit]) -> str:
    if not edits:
        return source
    ordered = sorted(edits, key=lambda edit: (edit.start, edit.end))
    previous_end = -1
    for edit in ordered:
        if edit.start < previous_end:
            raise RewriteError("overlapping reference rewrites")
        previous_end = edit.end
    output = source
    for edit in reversed(ordered):
        output = output[: edit.start] + edit.replacement + output[edit.end :]
    return output


def _bare_import_edits(
    source: str, starts: list[int], tree: ast.AST, table: _Destinations
) -> list[_Edit]:
    """Update bound attribute chains for bare dotted imports that changed path."""
    moved: dict[str, str] = {}
    roots: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import):
            continue
        for alias in node.names:
            if alias.asname:
                continue
            destination = table.lookup(alias.name)
            if destination is None or destination == alias.name:
                continue
            root = alias.name.split(".")[0]
            if root in roots and roots[root] != alias.name:
                raise RewriteError(f"ambiguous bare imports bound to {root!r}")
            roots[root] = alias.name
            moved[alias.name] = destination
    if not moved:
        return []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id in roots
        ):
            raise RewriteError(f"bare import binding is reassigned: {node.id}")
        if isinstance(node, ast.arg) and node.arg in roots:
            raise RewriteError(f"bare import binding is shadowed: {node.arg}")
    parents = {
        id(child): node
        for node in ast.walk(tree)
        for child in ast.iter_child_nodes(node)
    }
    edits: list[_Edit] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        parent = parents.get(id(node))
        if isinstance(parent, ast.Attribute) and parent.value is node:
            continue
        parts: list[str] = []
        cursor: ast.AST = node
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if not isinstance(cursor, ast.Name):
            continue
        full = ".".join([cursor.id, *reversed(parts)])
        for old in sorted(moved, key=len, reverse=True):
            if full == old or full.startswith(old + "."):
                start, end = _span(source, starts, node)
                edits.append(_Edit(start, end, moved[old] + full[len(old) :]))
                break
    return edits


def _rewrite_source(
    source: str,
    source_module: str,
    destinations: dict[str, str],
    exports: dict[str, list[str]] | None,
    *,
    target_module: str | None,
    symbol_paths: set[str] | None,
) -> str:
    if not isinstance(source, str):
        raise TypeError("source must be a string")
    if not isinstance(source_module, str) or not _is_path(source_module):
        raise RewriteError(f"invalid source module: {source_module!r}")
    if target_module is not None and not _is_path(target_module):
        raise RewriteError(f"invalid target module: {target_module!r}")
    table = _Destinations(destinations, symbol_paths)
    _validate_exports(exports)
    tree = ast.parse(source)
    starts = _line_starts(source)
    newline = "\r\n" if "\r\n" in source else "\n"
    edits: list[_Edit] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            edit = _rewrite_import(
                source,
                starts,
                node,
                module=source_module,
                table=table,
                exports=exports,
                newline=newline,
                target_module=target_module,
            )
            if edit is not None:
                edits.append(edit)
    edits.extend(_string_edits(source, starts, tree, table))
    edits.extend(_bare_import_edits(source, starts, tree, table))
    return _apply_edits(source, edits)


def rewrite_file(
    source: str,
    module: str,
    destinations: dict[str, str],
    exports: dict[str, list[str]] | None = None,
    *,
    symbol_paths: set[str] | None = None,
) -> str:
    """Rewrite reviewed imports and callable references in one Python source.

    The function is pure: it parses and returns source text, and does not touch
    the filesystem.  A :class:`RewriteError` is raised for invalid mappings,
    unresolved relative imports, and star imports whose static export set is
    unavailable.  Dynamic strings and unrecognized call contexts are left
    unchanged rather than guessed.
    """
    return _rewrite_source(
        source,
        module,
        destinations,
        exports,
        target_module=None,
        symbol_paths=symbol_paths,
    )


def rewrite_moved_file(
    source: str,
    source_module: str,
    target_module: str,
    destinations: dict[str, str],
    exports: dict[str, list[str]] | None = None,
    *,
    symbol_paths: set[str] | None = None,
) -> str:
    """Rewrite code after moving it from ``source_module`` to ``target_module``.

    Relative imports are resolved using the original source-module context
    and emitted as absolute paths. Only explicitly reviewed destination
    entries relocate siblings; other siblings remain at their old location.
    """
    return _rewrite_source(
        source,
        source_module,
        destinations,
        exports,
        target_module=target_module,
        symbol_paths=symbol_paths,
    )


def rewrite_database_orm_refs(
    source: str,
    reviewed_mixin_methods: Mapping[str, str],
) -> str:
    """Rewrite approved ``DatabaseORM.method`` self-references only.

    ``reviewed_mixin_methods`` maps ``method`` (or ``Mixin.method``) to the
    reviewed mixin class that owns it.  A reference is changed from
    ``DatabaseORM.method`` to ``Mixin.method`` only while traversing that same
    class.  References in another mixin, at module scope, or to an unreviewed
    method are deliberately unchanged.
    """
    if not isinstance(source, str):
        raise TypeError("source must be a string")
    if not isinstance(reviewed_mixin_methods, Mapping):
        raise TypeError("reviewed_mixin_methods must be a mapping")
    method_owners: dict[str, str] = {}
    for key, owner in reviewed_mixin_methods.items():
        if not isinstance(key, str) or not _is_path(key):
            raise RewriteError(f"invalid reviewed method: {key!r}")
        if not isinstance(owner, str) or not _is_path(owner):
            raise RewriteError(f"invalid reviewed mixin: {owner!r}")
        method = key.rsplit(".", 1)[-1]
        if "." in key and key.rsplit(".", 1)[0] != owner:
            raise RewriteError(f"reviewed method owner mismatch: {key!r} -> {owner!r}")
        previous = method_owners.get(method)
        if previous is not None and previous != owner:
            raise RewriteError(f"ambiguous reviewed method: {method!r}")
        method_owners[method] = owner

    tree = ast.parse(source)
    starts = _line_starts(source)
    edits: list[_Edit] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.classes: list[str] = []
            self.functions = 0

        def visit_ClassDef(self, node: ast.ClassDef) -> Any:
            self.classes.append(node.name)
            self.generic_visit(node)
            self.classes.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
            self.functions += 1
            self.generic_visit(node)
            self.functions -= 1

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
            self.functions += 1
            self.generic_visit(node)
            self.functions -= 1

        def visit_Attribute(self, node: ast.Attribute) -> Any:
            if (
                self.classes
                and self.functions
                and isinstance(node.value, ast.Name)
                and node.value.id == "DatabaseORM"
                and method_owners.get(node.attr) == self.classes[-1]
            ):
                start, end = _span(source, starts, node.value)
                edits.append(_Edit(start, end, self.classes[-1]))
            self.generic_visit(node)

    Visitor().visit(tree)
    return _apply_edits(source, edits)


__all__ = [
    "RewriteError",
    "rewrite_database_orm_refs",
    "rewrite_file",
    "rewrite_moved_file",
]
