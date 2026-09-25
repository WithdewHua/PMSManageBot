"""Detect newly introduced import cycles, including untouched app modules."""

from __future__ import annotations

import ast
from pathlib import Path

from scripts.refactor.relocation_refs import module_context


def _dependencies(module: str, source: str, known: set[str]) -> set[str]:
    dependencies: set[str] = set()
    for node in ast.walk(ast.parse(source, filename=module)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name in known:
                    dependencies.add(name)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "importlib"
            and node.func.attr == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            if node.args[0].value in known:
                dependencies.add(node.args[0].value)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package = module.split(".")[:-1]
                if node.level > len(package):
                    continue
                prefix = package[: len(package) - node.level + 1]
                name = ".".join([*prefix, *(node.module or "").split(".")]).rstrip(".")
            else:
                name = node.module or ""
            if name in known:
                dependencies.add(name)
            for alias in node.names:
                child = f"{name}.{alias.name}"
                if child in known:
                    dependencies.add(child)
    return dependencies


def cycles(modules: dict[str, str]) -> set[frozenset[str]]:
    """Find all cyclic strongly connected components in a module graph."""
    graph = {
        module: _dependencies(module, text, set(modules))
        for module, text in modules.items()
    }
    index = 0
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    result: set[frozenset[str]] = set()

    def visit(module: str) -> None:
        nonlocal index
        indexes[module] = lowlinks[module] = index
        index += 1
        stack.append(module)
        on_stack.add(module)
        for neighbor in sorted(graph[module]):
            if neighbor not in indexes:
                visit(neighbor)
                lowlinks[module] = min(lowlinks[module], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[module] = min(lowlinks[module], indexes[neighbor])
        if lowlinks[module] == indexes[module]:
            component: set[str] = set()
            while stack:
                neighbor = stack.pop()
                on_stack.remove(neighbor)
                component.add(neighbor)
                if neighbor == module:
                    break
            if len(component) > 1 or module in graph[module]:
                result.add(frozenset(component))

    for module in sorted(graph):
        if module not in indexes:
            visit(module)
    return result


def project_modules(
    root: Path, staged: dict[Path, str | None] | None = None
) -> dict[str, str]:
    """Build an app graph from disk with optional staged replacements/deletions."""
    staged = staged or {}
    modules: dict[str, str] = {}
    for path in (root / "src/app").rglob("*.py"):
        if path in staged and staged[path] is None:
            continue
        modules[module_context(path, root).removesuffix(".__init__")] = (
            staged[path] if path in staged else path.read_text(encoding="utf-8")
        )
    for path, text in staged.items():
        if text is not None and path.is_relative_to(root / "src/app"):
            modules[module_context(path, root).removesuffix(".__init__")] = text
    return modules


def new_cycles(
    before: dict[str, str],
    after: dict[str, str],
    moves: dict[str, str],
) -> set[frozenset[str]]:
    """Compare post-move cycles to the projected names of existing cycles."""
    projected = {
        frozenset(moves.get(module, module) for module in component)
        for component in cycles(before)
    }
    return cycles(after) - projected
