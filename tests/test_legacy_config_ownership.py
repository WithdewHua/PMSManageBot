"""Legacy configuration ownership and assembly-boundary tests."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.business_config import CONFIGS, LEGACY_ENV, _bind_legacy_sources
from app.core.domain_config import DomainConfig, FieldRows, LegacySource

ROOT = Path(__file__).resolve().parents[1]
assert (ROOT / "src/app").is_dir()

EXPECTED_LEGACY_DEFAULTS = {
    "CREDITS_COST_PER_10GB": 5,
    "CREDITS_TRANSFER_ENABLED": True,
    "DONATION_MULTIPLIER": 5,
    "DOWNLOAD_UNLOCK_CREDITS": 368,
    "EMBY_REGISTER": True,
    "INVITATION_CREDITS": 288,
    "LINE_SCHEDULE_UNLOCK_CREDITS": 264,
    "NSFW_LIBS": ["NSFW", "NC17 Movies", "Hentai"],
    "PREMIUM_DAILY_CREDITS": 15,
    "PREMIUM_FREE": False,
    "PREMIUM_UNLOCK_ENABLED": False,
    "PREMIUM_USER_TRAFFIC_LIMIT": 25769803776,
    "PLEX_REGISTER": False,
    "UNLOCK_CREDITS": 100,
    "UPAY_CRYPTO_TYPES": [
        "USDC-Polygon",
        "USDC-ArbitrumOne",
        "USDC-BSC",
        "USDC-ERC20",
        "USDT-Polygon",
        "USDT-ArbitrumOne",
        "USDT-BSC",
        "USDT-ERC20",
    ],
    "USER_TRAFFIC_LIMIT": 12884901888,
    "VAULTWARDEN_ENABLED": False,
    "VAULTWARDEN_REDEEM_CREDITS": 500,
}


def test_domain_declarations_reproduce_complete_legacy_defaults() -> None:
    declared = {
        source.key: source.default
        for config in CONFIGS
        for source in config.legacy.values()
        if isinstance(source, LegacySource)
    }
    assert declared == EXPECTED_LEGACY_DEFAULTS
    assert LEGACY_ENV.defaults == EXPECTED_LEGACY_DEFAULTS
    assert all(
        isinstance(source, LegacySource)
        and source.reader is not None
        and getattr(source.reader, "__self__", None) is LEGACY_ENV
        for config in CONFIGS
        for source in config.legacy.values()
    )


def test_legacy_source_conflicts_are_rejected_before_binding() -> None:
    class ConfigModel(BaseModel):
        value: int = 1

    first = DomainConfig(
        "first",
        ConfigModel,
        FieldRows("test.first"),
        legacy={"value": LegacySource("DUP", default=1)},
    )
    second = DomainConfig(
        "second",
        ConfigModel,
        FieldRows("test.second"),
        legacy={"value": LegacySource("DUP", default=2)},
    )
    with pytest.raises(ValueError, match="conflicting legacy default"):
        _bind_legacy_sources((first, second))


def test_unbound_domain_config_cannot_seed_silently() -> None:
    class ConfigModel(BaseModel):
        value: int = 1

    config = DomainConfig(
        "unbound",
        ConfigModel,
        FieldRows("test.unbound"),
        legacy={"value": LegacySource("VALUE", default=1)},
    )
    with pytest.raises(RuntimeError, match="legacy reader is not bound"):
        config.seed()


def test_core_legacy_env_has_no_business_registry_or_global_instance() -> None:
    path = ROOT / "src/app/core/legacy_env.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {
        node.targets[0].id
        for node in tree.body
        if isinstance(node, ast.Assign)
        and node.targets
        and isinstance(node.targets[0], ast.Name)
    }
    assert "MIGRATED_ENV_DEFAULTS" not in names
    assert "LEGACY_ENV" not in names
