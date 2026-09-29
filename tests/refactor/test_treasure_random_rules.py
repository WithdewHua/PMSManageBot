"""Regression tests for treasure-owned random-B mapping and RPC boundaries."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import hmac
from pathlib import Path

import pytest

from app.domains.treasure import rules as treasure_rules
from app.domains.treasure import service as treasure_service
from app.integrations import eth_rpc

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (None, None, None),
        (None, 7, 7),
        (0, None, 0),
        (-1, None, (1 << 63) - 1),
        ((1 << 63) + 3, None, 3),
        ((1 << 256) - 1, None, (1 << 63) - 1),
    ],
)
def test_treasure_random_b_mapping_preserves_legacy_semantics(value, default, expected):
    assert (
        treasure_rules.normalize_external_random_b(value, default=default) == expected
    )


def test_fallback_random_b_is_pure_and_secret_explicit():
    issue = {"total_shares": 10, "shares_sold": 8}
    kwargs = {
        "issue_id": 3,
        "issue": issue,
        "quantity": 2,
        "tg_id": 9,
        "timestamp_ms": 100,
        "secret": "secret",
    }
    actual = treasure_rules.fallback_external_random_b(**kwargs)
    message = b"treasure|fallback_b|issue_id=3|total=10|sold=8|qty=2|tg_id=9|ts_ms=100"
    expected = int.from_bytes(
        hmac.new(b"secret", message, hashlib.sha256).digest()[:8], "big"
    ) & ((1 << 63) - 1)
    assert actual == expected
    with pytest.raises(RuntimeError, match="TG_API_TOKEN not configured"):
        treasure_rules.fallback_external_random_b(**{**kwargs, "secret": ""})


def test_rules_do_not_import_settings_or_network_modules():
    tree = ast.parse(
        (ROOT / "src/app/domains/treasure/rules.py").read_text(encoding="utf-8")
    )
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert not any(name.startswith("app.core.config") for name in imported)
    assert not any(name in {"aiohttp", "requests"} for name in imported)


async def _raw_block_hash() -> int:
    return (1 << 256) - 1


async def _noop(*args, **kwargs) -> None:
    return None


def test_service_maps_raw_rpc_hash_before_repository_persistence(monkeypatch):
    captured = {}

    def join(**kwargs):
        captured.update(kwargs)
        return {
            "settled": False,
            "participations": [{"id": 1}],
            "issue": {"shares_sold": 1, "total_shares": 10},
        }

    monkeypatch.setattr(eth_rpc, "latest_block_hash_int", _raw_block_hash)
    monkeypatch.setattr(
        treasure_service.treasure_repository, "join_treasure_issue", join
    )
    monkeypatch.setattr(
        treasure_service.treasure_repository,
        "get_treasure_issue_by_id",
        lambda issue_id: {
            "title": "test",
            "shares_sold": 1,
            "total_shares": 10,
            "prize_credits": 10,
        },
    )
    monkeypatch.setattr(
        treasure_service.treasure_notifications,
        "notify_treasure_not_full_after_join",
        _noop,
    )

    asyncio.run(treasure_service.join_treasure_issue(issue_id=1, tg_id=2))
    assert captured["external_random_b"] == (1 << 63) - 1


def test_eth_rpc_source_returns_raw_hash_without_domain_mapping():
    source = (ROOT / "src/app/integrations/eth_rpc.py").read_text(encoding="utf-8")
    assert "app.core.number" not in source
    assert "return int(block_hash, 16)" in source
