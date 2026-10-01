"""Verify user credits cache ownership, isolation, and invalidation semantics."""

from __future__ import annotations

import ast
from pathlib import Path

from app.domains.credits import cache

ROOT = Path(__file__).resolve().parents[1]
assert (ROOT / "src/app").is_dir()


def test_credits_cache_instance_is_isolated_to_credits_domain() -> None:
    """user_credits_cache must only be defined and imported in app.domains.credits."""
    violations: list[tuple[str, int, str]] = []
    for path in sorted((ROOT / "src/app").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("src/app/domains/credits/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    if alias.name == "user_credits_cache":
                        violations.append((rel, node.lineno, node.module))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "user_credits_cache" in alias.name:
                        violations.append((rel, node.lineno, alias.name))
    assert violations == [], (
        f"Foreign modules must not import user_credits_cache directly: {violations}"
    )


def test_user_credits_cache_configuration() -> None:
    """Verify user_credits_cache key prefix and mechanism."""
    assert cache.user_credits_cache._cache_key_prefix == "user_credits:"


def test_invalidate_user_credits_deletes_expected_keys(monkeypatch) -> None:
    """invalidate_user_credits must delete unique keys in order."""
    deleted: list[str] = []
    monkeypatch.setattr(
        cache.user_credits_cache, "delete", lambda key: deleted.append(key)
    )

    cache.invalidate_user_credits(
        ["tg:123", "plex:aliceuser", "emby:bobuser", "tg:123"]
    )
    assert deleted == ["tg:123", "plex:aliceuser", "emby:bobuser"]


def test_invalidate_user_credits_handles_empty_iterable(monkeypatch) -> None:
    deleted: list[str] = []
    monkeypatch.setattr(
        cache.user_credits_cache, "delete", lambda key: deleted.append(key)
    )

    cache.invalidate_user_credits([])
    assert deleted == []
