"""HTTP ordering/schema, bot registrations and jobs stay frozen during promotion."""

import json
from pathlib import Path

from scripts.refactor.remaining_snapshot import build_remaining_snapshot


def test_remaining_public_surface_is_frozen() -> None:
    expected = json.loads(
        (Path(__file__).parent / "fixtures/remaining_surface.json").read_text()
    )
    first = build_remaining_snapshot()
    assert first == build_remaining_snapshot()
    differences = _differences(first, expected)
    assert not differences, "\n".join(differences)


def _differences(actual, expected, path="") -> list[str]:
    if isinstance(actual, dict) and isinstance(expected, dict):
        result = []
        for key in sorted(set(actual) | set(expected)):
            result.extend(
                _differences(actual.get(key), expected.get(key), f"{path}/{key}")
            )
        return result
    if (
        isinstance(actual, list)
        and isinstance(expected, list)
        and len(actual) == len(expected)
    ):
        return [
            difference
            for i, (a, b) in enumerate(zip(actual, expected))
            for difference in _differences(a, b, f"{path}/{i}")
        ]
    return (
        []
        if actual == expected
        else [f"{path}: {str(expected)[:100]!r} -> {str(actual)[:100]!r}"]
    )


def test_all_frozen_legacy_members_have_owner_mappings():
    import tomllib

    root = Path(__file__).resolve().parents[2]
    members = json.loads(
        (Path(__file__).parent / "fixtures/remaining_legacy_members.json").read_text()
    )["members"]
    mapped = {
        item["id"]: item
        for item in tomllib.loads((root / "scripts/refactor/mapping.toml").read_text())[
            "items"
        ]
    }
    for member in members:
        entry = mapped[f"remaining.legacy:{member['class']}.{member['method']}"]
        assert entry["target"].startswith("app.domains.")
        assert "TODO" not in entry["target"]
        path = root / "src" / entry["target"].replace(".", "/")
        assert path.with_suffix(".py").exists() or (path / "__init__.py").exists()


def test_identity_and_invitation_compatibility_have_no_runtime_consumers():
    import ast

    root = Path(__file__).resolve().parents[2]
    legacy_methods = set()
    for module, class_name in [
        ("identity/compat.py", "IdentityRepository"),
        ("invitation/repository.py", "InvitationRepository"),
    ]:
        tree = ast.parse((root / "src/app/domains" / module).read_text())
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                legacy_methods.update(
                    n.name
                    for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
    consumers = []
    for path in list((root / "src/app").rglob("*.py")) + list(
        (root / "scripts").rglob("*.py")
    ):
        if "databases" in path.parts or "refactor" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        facade_names = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("app.databases")
            ):
                facade_names.update(
                    n.asname or n.name for n in node.names if n.name == "db"
                )
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in facade_names
                and node.func.attr in legacy_methods
            ):
                consumers.append(
                    f"{path.relative_to(root)}:{node.lineno}:{node.func.attr}"
                )
    assert not consumers, consumers


def test_promoted_module_functions_have_no_leftover_method_receiver():
    import ast

    root = Path(__file__).resolve().parents[2] / "src/app/domains"
    for domain in (
        "donation",
        "crypto_donation",
        "vaultwarden",
        "rankings",
        "reports",
        "profile",
    ):
        for path in (root / domain).rglob("*.py"):
            for node in ast.parse(path.read_text()).body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    arguments = node.args.posonlyargs + node.args.args
                    assert not arguments or arguments[0].arg not in {"self", "cls"}, (
                        f"{path}:{node.lineno}:{node.name}"
                    )
