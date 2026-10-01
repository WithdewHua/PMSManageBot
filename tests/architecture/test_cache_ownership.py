"""Verify business Redis cache ownership and protocol preservation."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
assert (ROOT / "src/app").is_dir()

EXPECTED_BUSINESS_CACHES = {
    "emby_api_key_cache": {"db": 3, "cache_key_prefix": "emby_api_key:"},
    "emby_last_user_defined_line_cache": {
        "db": 2,
        "cache_key_prefix": "emby_last_user_defined_line:",
    },
    "emby_user_defined_line_cache": {
        "db": 2,
        "cache_key_prefix": "emby_user_defined_line:",
    },
    "plex_last_user_defined_line_cache": {
        "db": 2,
        "cache_key_prefix": "plex_last_user_defined_line:",
    },
    "plex_token_cache": {"db": 3, "cache_key_prefix": "plex_token_cache:"},
    "plex_user_defined_line_cache": {
        "db": 2,
        "cache_key_prefix": "plex_user_defined_line:",
    },
    "stream_traffic_cache": {"db": 15, "cache_key_prefix": ""},
    "user_credits_cache": {"db": 0, "cache_key_prefix": "user_credits:"},
    "user_info_cache": {"db": 2, "cache_key_prefix": "user_info:"},
}


def _redis_instances(path: Path) -> dict[str, dict[str, object]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if not isinstance(func, ast.Name) or func.id != "RedisCache":
            continue
        if not node.targets or not isinstance(node.targets[0], ast.Name):
            continue
        values = {
            keyword.arg: ast.literal_eval(keyword.value)
            for keyword in node.value.keywords
            if keyword.arg in {"db", "cache_key_prefix"}
        }
        result[node.targets[0].id] = {
            "db": values.get("db", 0),
            "cache_key_prefix": values["cache_key_prefix"],
        }
    return result


def test_business_cache_protocol_is_preserved_in_owning_modules() -> None:
    actual = {}
    for path in (
        ROOT / "src/app/domains/lines/gateway_cache.py",
        ROOT / "src/app/domains/lines/cache.py",
        ROOT / "src/app/domains/traffic/cache.py",
        ROOT / "src/app/domains/credits/cache.py",
        ROOT / "src/app/domains/identity/cache.py",
        ROOT / "src/app/integrations/media_tokens.py",
    ):
        actual.update(_redis_instances(path))
    actual = {
        name.removeprefix("_"): value
        for name, value in actual.items()
        if name in {"_emby_api_key_cache", "_plex_token_cache"}
        or name in EXPECTED_BUSINESS_CACHES
    }
    actual["emby_api_key_cache"] = actual.pop("emby_api_key_cache")
    actual["plex_token_cache"] = actual.pop("plex_token_cache")
    assert actual == EXPECTED_BUSINESS_CACHES


def test_core_cache_contains_only_mechanism_and_no_business_instances() -> None:
    source = (ROOT / "src/app/core/cache.py").read_text(encoding="utf-8")
    assert "RedisCache(" not in source
    assert "user_credits_cache" not in source
    assert "user_info_cache" not in source
    assert "stream_traffic_cache" not in source
    assert "invalidate_user_credits" not in source


def test_business_instances_are_not_imported_from_core_cache() -> None:
    violations = []
    for path in sorted((ROOT / "src/app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module != "app.core.cache":
                continue
            names = {alias.name for alias in node.names}
            if names != {"RedisCache"}:
                violations.append((path.relative_to(ROOT).as_posix(), sorted(names)))
    assert violations == []
