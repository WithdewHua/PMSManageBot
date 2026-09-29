"""AST-based architecture checks for both legacy and split layouts."""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .helpers import (
    class_member_names,
    dotted_name,
    make_violation,
    module_name,
    owner_for_domain,
    parse_python,
    python_files,
    relative_path,
)

LINE_BUDGET = 1000
LEGACY_DATABASE_MODULE = "app.databases.db"


@dataclass(frozen=True, slots=True)
class _ClassRecord:
    path: Path
    module: str
    domain: str | None
    node: ast.ClassDef


def _domain_for_module(module: str) -> str | None:
    parts = module.split(".")
    try:
        index = parts.index("domains")
    except ValueError:
        return None
    return parts[index + 1] if index + 1 < len(parts) else None


def _role_for_module(module: str) -> str | None:
    parts = module.split(".")
    if "domains" not in parts:
        return None
    if "repository" in parts:
        return "repository"
    role = parts[-1]
    return (
        role
        if role
        in {
            "admin_router",
            "bot",
            "config",
            "constants",
            "exceptions",
            "jobs",
            "models",
            "notifications",
            "repository",
            "router",
            "rules",
            "schemas",
            "service",
            "types",
        }
        else None
    )


def _module_from_relative_import(
    node: ast.ImportFrom,
    current_module: str,
    path: Path,
) -> str | None:
    if node.level == 0:
        return node.module

    package = (
        current_module
        if path.name == "__init__.py"
        else current_module.rsplit(".", 1)[0]
    )
    package_parts = package.split(".")
    parent_length = len(package_parts) - node.level + 1
    if parent_length <= 0:
        return None
    base = ".".join(package_parts[:parent_length])
    return f"{base}.{node.module}" if node.module else base


def _repository_classes(root: Path) -> list[_ClassRecord]:
    records: list[_ClassRecord] = []
    for path in python_files(root):
        module = module_name(path, root)
        is_legacy_database = module == LEGACY_DATABASE_MODULE
        if _role_for_module(module) != "repository" and not is_legacy_database:
            continue
        tree = parse_python(path)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if is_legacy_database and node.name != "DatabaseORM":
                continue
            if not is_legacy_database and not node.name.endswith(
                ("Repository", "Mixin")
            ):
                continue
            records.append(
                _ClassRecord(
                    path=path,
                    module=module,
                    domain=_domain_for_module(module),
                    node=node,
                )
            )
    return records


def _method_owners(root: Path) -> dict[str, set[str]]:
    owners: dict[str, set[str]] = defaultdict(set)
    for record in _repository_classes(root):
        domain = record.domain or "legacy"
        for name, _line in class_member_names(record.node):
            owners[name].add(domain)
    return owners


def _import_bindings(
    path: Path,
    root: Path,
    tree: ast.Module,
) -> tuple[dict[str, dict[str, str]], set[str], list[dict[str, Any]]]:
    """Return aliases, facade aliases, and cross-domain import violations."""
    current_module = module_name(path, root)
    current_domain = _domain_for_module(current_module)
    current_role = _role_for_module(current_module)
    bindings: dict[str, dict[str, str]] = {}
    facade_aliases: set[str] = set()
    violations: list[dict[str, Any]] = []

    # Imports inside handlers and methods are dependencies too, even when delayed
    # to avoid runtime import cycles.
    for statement in ast.walk(tree):
        if isinstance(statement, ast.ImportFrom):
            imported_module = _module_from_relative_import(
                statement, current_module, path
            )
            if imported_module is None:
                continue
            if imported_module in {"app.databases", "app.databases.db"}:
                for alias in statement.names:
                    if alias.name == "db":
                        facade_aliases.add(alias.asname or alias.name)
                continue

            for alias in statement.names:
                target_module = imported_module
                if alias.name == "*":
                    target_domain = _domain_for_module(target_module)
                    if (
                        current_domain
                        and target_domain
                        and target_domain != current_domain
                    ):
                        key = (
                            f"import|{relative_path(path, root)}|{statement.lineno}|"
                            f"{target_module}|*"
                        )
                        violations.append(
                            make_violation(
                                key,
                                owner_for_domain(current_domain),
                                path=relative_path(path, root),
                                line=statement.lineno,
                                kind="import",
                                source_domain=current_domain,
                                target_domain=target_domain,
                                target_module=target_module,
                                symbol="*",
                            )
                        )
                    continue
                if (
                    _domain_for_module(target_module) is not None
                    and _role_for_module(target_module) is None
                    and alias.name
                    in {
                        "admin_router",
                        "bot",
                        "config",
                        "constants",
                        "exceptions",
                        "jobs",
                        "models",
                        "notifications",
                        "repository",
                        "router",
                        "rules",
                        "schemas",
                        "service",
                        "types",
                    }
                ):
                    target_module = f"{imported_module}.{alias.name}"
                target_domain = _domain_for_module(target_module)
                if (
                    current_domain is None
                    or target_domain is None
                    or target_domain == current_domain
                ):
                    continue
                target_role = _role_for_module(target_module)
                symbol = alias.name
                local_name = alias.asname or alias.name
                bindings[local_name] = {
                    "domain": target_domain,
                    "module": target_module,
                    "role": target_role or "",
                    "symbol": symbol,
                }
                if not _import_allowed(
                    current_domain, current_role, target_domain, target_role, symbol
                ):
                    violations.append(
                        make_violation(
                            f"import|{relative_path(path, root)}|{statement.lineno}|"
                            f"{target_module}|{symbol}",
                            owner_for_domain(current_domain),
                            path=relative_path(path, root),
                            line=statement.lineno,
                            kind="import",
                            source_domain=current_domain,
                            target_domain=target_domain,
                            target_module=target_module,
                            symbol=symbol,
                        )
                    )
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                target_module = alias.name
                target_domain = _domain_for_module(target_module)
                if current_domain is None or target_domain is None:
                    continue
                if target_domain == current_domain:
                    continue
                local_name = alias.asname or alias.name
                target_role = _role_for_module(target_module)
                bindings[local_name] = {
                    "domain": target_domain,
                    "module": target_module,
                    "role": target_role or "",
                    "symbol": "",
                }
                if not _import_allowed(
                    current_domain, current_role, target_domain, target_role, ""
                ):
                    violations.append(
                        make_violation(
                            f"import|{relative_path(path, root)}|{statement.lineno}|"
                            f"{target_module}",
                            owner_for_domain(current_domain),
                            path=relative_path(path, root),
                            line=statement.lineno,
                            kind="import",
                            source_domain=current_domain,
                            target_domain=target_domain,
                            target_module=target_module,
                        )
                    )
    return bindings, facade_aliases, violations


def _import_allowed(
    source_domain: str,
    source_role: str | None,
    target_domain: str,
    target_role: str | None,
    symbol: str,
) -> bool:
    # Value types are shared vocabulary: any role may import another domain's
    # ``types`` module (purity is enforced by the import-linter contract).
    if target_role == "types":
        return True
    # Media-service labels are a reviewed pure identity vocabulary. Routers may
    # obtain the small presentation facade without creating a new baseline debt.
    if (
        source_role == "router"
        and target_domain == "identity"
        and target_role == "service"
        and symbol == "service"
    ):
        return True
    if source_role == "service":
        return target_role in {"service", "exceptions", "constants"}
    if source_role == "repository":
        return (
            (
                target_role == "repository"
                and (symbol == "repository" or not symbol or symbol.endswith("_tx"))
            )
            or (target_role == "models" and target_domain == "identity")
            or (
                source_domain in {"rankings", "reports", "profile"}
                and target_role == "models"
            )
        )
    return False


def _call_allowed(
    source_role: str | None, target_role: str | None, symbol: str
) -> bool:
    if target_role == "types":
        return True
    if (
        source_role == "router"
        and target_role == "service"
        and symbol == "get_service_label"
    ):
        return True
    if source_role == "service":
        return target_role in {"service", "exceptions", "constants"}
    if source_role == "repository":
        # Model constructors and class methods are legal only when the import
        # itself is allowed; _import_allowed checks the identity/read-model rule.
        return target_role == "models" or (
            target_role == "repository" and symbol.endswith("_tx")
        )
    return False


def _binding_for_call(
    function: ast.AST,
    bindings: dict[str, dict[str, str]],
) -> tuple[dict[str, str], str] | None:
    name = dotted_name(function)
    if name is None:
        return None
    for alias in sorted(bindings, key=len, reverse=True):
        binding = bindings[alias]
        if name == alias:
            return binding, binding["symbol"]
        if name.startswith(f"{alias}."):
            remainder = name[len(alias) + 1 :]
            target_role = binding["role"]
            if not target_role:
                target_role = remainder.split(".")[0]
                binding = {**binding, "role": target_role}
            return binding, remainder.rsplit(".", 1)[-1]
    return None


def scan_cross_domain_calls(root: Path) -> list[dict[str, Any]]:
    """Scan cross-domain imports, direct calls, facade calls, and self calls."""
    method_owners = _method_owners(root)
    records = _repository_classes(root)
    violations: dict[str, dict[str, Any]] = {}

    for path in python_files(root):
        module = module_name(path, root)
        domain = _domain_for_module(module)
        if domain is None:
            continue
        role = _role_for_module(module)
        tree = parse_python(path)
        bindings, facade_aliases, import_violations = _import_bindings(path, root, tree)
        for violation in import_violations:
            violations[violation["key"]] = violation

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            binding_call = _binding_for_call(node.func, bindings)
            if binding_call is not None:
                binding, symbol = binding_call
                target_domain = binding["domain"]
                target_role = binding["role"] or None
                if not _call_allowed(role, target_role, symbol):
                    key = (
                        f"call|{relative_path(path, root)}|{node.lineno}|imported|"
                        f"{target_domain}|{symbol}"
                    )
                    violations[key] = make_violation(
                        key,
                        owner_for_domain(domain),
                        path=relative_path(path, root),
                        line=node.lineno,
                        kind="call",
                        source_domain=domain,
                        target_domain=target_domain,
                        target=symbol,
                    )

            if not isinstance(node.func, ast.Attribute):
                continue
            receiver = node.func.value
            method = node.func.attr
            if not (isinstance(receiver, ast.Name) and receiver.id in facade_aliases):
                continue
            target_domains = {
                item for item in method_owners.get(method, set()) if item != "legacy"
            }
            if len(target_domains) != 1:
                continue
            target_domain = next(iter(target_domains))
            if target_domain == domain:
                continue
            key = (
                f"call|{relative_path(path, root)}|{node.lineno}|"
                f"facade|{target_domain}|{method}"
            )
            violations[key] = make_violation(
                key,
                owner_for_domain(domain),
                path=relative_path(path, root),
                line=node.lineno,
                kind="facade_call",
                source_domain=domain,
                target_domain=target_domain,
                target=method,
            )

    for record in records:
        if record.domain is None:
            continue
        for node in ast.walk(record.node):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if (
                not isinstance(node.func.value, ast.Name)
                or node.func.value.id != "self"
            ):
                continue
            method = node.func.attr
            target_domains = {
                item for item in method_owners.get(method, set()) if item != "legacy"
            }
            if len(target_domains) != 1:
                continue
            target_domain = next(iter(target_domains))
            if target_domain == record.domain or method.endswith("_tx"):
                continue
            key = (
                f"call|{relative_path(record.path, root)}|{node.lineno}|self|"
                f"{target_domain}|{method}"
            )
            violations[key] = make_violation(
                key,
                owner_for_domain(record.domain),
                path=relative_path(record.path, root),
                line=node.lineno,
                kind="self_call",
                source_domain=record.domain,
                target_domain=target_domain,
                target=method,
            )

    return sorted(violations.values(), key=lambda item: item["key"])


def _line_budget_owner(path: str) -> str:
    if path.endswith("blackjack_tournament.py"):
        return "promote-blackjack-domain"
    return "restructure-backend-architecture"


def scan_line_budgets(root: Path) -> list[dict[str, Any]]:
    """Find every source file over the hard 1,000-line budget."""
    violations: list[dict[str, Any]] = []
    for path in python_files(root):
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines <= LINE_BUDGET:
            continue
        stable_path = relative_path(path, root)
        violations.append(
            make_violation(
                stable_path,
                _line_budget_owner(stable_path),
                path=stable_path,
                lines=lines,
                budget=LINE_BUDGET,
            )
        )
    return sorted(violations, key=lambda item: item["key"])


def _is_model_subclass(node: ast.ClassDef) -> bool:
    return any(
        dotted_name(base).split(".")[-1] == "Base"
        for base in node.bases
        if dotted_name(base)
    )


def _model_classes(root: Path) -> list[tuple[Path, str, ast.ClassDef]]:
    models: list[tuple[Path, str, ast.ClassDef]] = []
    for path in python_files(root):
        module = module_name(path, root)
        if not (module.endswith(".models") or module == "app.core.kv"):
            continue
        tree = parse_python(path)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and _is_model_subclass(node):
                models.append((path, module, node))
    return models


def _registry_imported_modules(root: Path, registry: Path) -> set[str]:
    imported: set[str] = set()
    tree = parse_python(registry)
    current_module = module_name(registry, root)
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                if alias.name.endswith(".models") or alias.name == "app.core.kv":
                    imported.add(alias.name)
        elif isinstance(statement, ast.ImportFrom):
            module = _module_from_relative_import(statement, current_module, registry)
            if module is None:
                continue
            for alias in statement.names:
                target = f"{module}.{alias.name}"
                if target.endswith(".models") or target == "app.core.kv":
                    imported.add(target)
                elif module.endswith(".models") or module == "app.core.kv":
                    imported.add(module)
    return imported


def scan_model_registry(root: Path) -> list[dict[str, Any]]:
    """Ensure every ``Base`` subclass is covered by the model registry."""
    models = _model_classes(root)
    registry = root / "src" / "app" / "model_registry.py"
    if not registry.exists():
        if models and all(module == "app.models.models" for _, module, _ in models):
            return []
        return [
            make_violation(
                "missing|app.model_registry",
                "restructure-backend-architecture",
                target="app.model_registry",
            )
        ]

    imported_modules = _registry_imported_modules(root, registry)
    violations: list[dict[str, Any]] = []
    for path, module, node in models:
        if module in imported_modules:
            continue
        key = f"model|{module}|{node.name}"
        violations.append(
            make_violation(
                key,
                owner_for_domain(_domain_for_module(module)),
                path=relative_path(path, root),
                line=node.lineno,
                model=node.name,
                module=module,
            )
        )
    return sorted(violations, key=lambda item: item["key"])


def scan_mixin_duplicates(root: Path) -> list[dict[str, Any]]:
    """Find duplicate direct members across repository mixins."""
    records = _repository_classes(root)
    members: dict[str, list[tuple[_ClassRecord, int]]] = defaultdict(list)
    for record in records:
        for name, line in class_member_names(record.node):
            members[name].append((record, line))

    violations: list[dict[str, Any]] = []
    for name, definitions in members.items():
        classes = sorted(
            f"{record.module}.{record.node.name}" for record, _line in definitions
        )
        if len(definitions) < 2:
            continue
        key = f"member|{name}|{','.join(classes)}"
        first_record, first_line = definitions[0]
        domains = {record.domain for record, _line in definitions}
        owner_domain = next(iter(domains)) if len(domains) == 1 else None
        violations.append(
            make_violation(
                key,
                owner_for_domain(owner_domain),
                path=relative_path(first_record.path, root),
                line=first_line,
                member=name,
                classes=classes,
            )
        )
    return sorted(violations, key=lambda item: item["key"])


def _numbered_module_owner(path: str) -> str:
    parts = path.split("/")
    domain = parts[3] if len(parts) > 3 and parts[0] == "src" else None
    return owner_for_domain(domain)


def scan_numbered_modules(root: Path) -> list[dict[str, Any]]:
    """Find numbered ``domains/*/repository/part_<digit>.py`` modules.

    Design D1 forbids numbered modules: repository packages are split by
    sub-topic, so a ``part_N`` file is either unfinished debt (registered here)
    or a regression.
    """
    violations: list[dict[str, Any]] = []
    for path in python_files(root):
        stable_path = relative_path(path, root)
        parts = path.stem.split("_")
        if "/domains/" not in f"/{stable_path}" or path.parent.name != "repository":
            continue
        if len(parts) != 2 or parts[0] != "part" or not parts[1].isdigit():
            continue
        violations.append(
            make_violation(
                f"numbered|{stable_path}",
                _numbered_module_owner(stable_path),
                path=stable_path,
            )
        )
    return sorted(violations, key=lambda item: item["key"])


def scan_config_access(root: Path) -> list[dict[str, Any]]:
    """Enforce ownership and layer rules for DomainConfig calls."""
    violations: list[dict[str, Any]] = []
    methods = {"get", "get_tx", "update", "seed"}
    for path in python_files(root):
        module = module_name(path, root)
        source_domain = _domain_for_module(module)
        source_role = _role_for_module(module)
        if module.startswith("app.integrations"):
            source_role = "integrations"
        if source_domain is None and source_role != "integrations":
            continue
        tree = parse_python(path)
        bindings: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                if len(parts) >= 4 and parts[:3] == ["app", "domains", parts[2]]:
                    target_domain = parts[2]
                    if parts[-1] == "config":
                        for alias in node.names:
                            bindings[alias.asname or alias.name] = target_domain
                elif len(parts) == 3 and parts[:2] == ["app", "domains"]:
                    target_domain = parts[2]
                    for alias in node.names:
                        if alias.name == "config":
                            bindings[alias.asname or alias.name] = target_domain
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app.domains.") and alias.name.endswith(
                        ".config"
                    ):
                        target_domain = alias.name.split(".")[2]
                        bindings[alias.asname or alias.name.split(".")[1]] = (
                            target_domain
                        )

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            if node.func.attr not in methods:
                continue
            value = node.func.value
            binding_name = None
            if isinstance(value, ast.Name):
                binding_name = value.id
            elif isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name):
                binding_name = value.value.id
            if binding_name not in bindings:
                continue
            target_domain = bindings[binding_name]
            method = node.func.attr
            allowed = False
            if method in {"get", "get_tx"}:
                allowed = source_role in {"service", "repository"}
            else:
                allowed = source_domain == target_domain and source_role in {
                    "service",
                    "repository",
                    "router",
                    "admin_router",
                    "jobs",
                }
            if allowed:
                continue
            relative = relative_path(path, root)
            key = f"config|{relative}|{node.lineno}|{target_domain}|{method}"
            violations.append(
                make_violation(
                    key,
                    owner_for_domain(source_domain),
                    path=relative,
                    line=node.lineno,
                    source_domain=source_domain,
                    source_role=source_role,
                    target_domain=target_domain,
                    operation=method,
                )
            )
    return sorted(violations, key=lambda item: item["key"])


def scan_all(root: Path) -> dict[str, list[dict[str, Any]]]:
    """Run all architecture scanners without reading or writing the baseline."""
    return {
        "cross_domain_calls": scan_cross_domain_calls(root),
        "config_access": scan_config_access(root),
        "line_budgets": scan_line_budgets(root),
        "model_registry": scan_model_registry(root),
        "mixin_duplicates": scan_mixin_duplicates(root),
        "numbered_modules": scan_numbered_modules(root),
    }
