"""Legacy configuration ownership and assembly-boundary tests."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.business_config import CONFIGS, LEGACY_ENV, _bind_legacy_sources
from app.core.domain_config import DomainConfig, FieldRows, LegacySource

ROOT = Path(__file__).parents[2]


def test_domain_declarations_reproduce_complete_legacy_defaults() -> None:
    expected = json.loads(
        (ROOT / "scripts/refactor/core_legacy_defaults_baseline.json").read_text(
            encoding="utf-8"
        )
    )
    declared = {
        source.key: source.default
        for config in CONFIGS
        for source in config.legacy.values()
        if isinstance(source, LegacySource)
    }
    assert declared == expected
    assert LEGACY_ENV.defaults == expected
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
