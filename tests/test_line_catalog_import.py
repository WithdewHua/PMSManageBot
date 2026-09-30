"""Unit tests for one-time line catalog import from legacy sources."""

from __future__ import annotations

import pytest

from app.core import kv as core_kv
from app.core.legacy_env import LegacyEnvSource
from app.domains.lines import catalog


@pytest.fixture(autouse=True)
def clean_catalog(session_env):
    catalog.invalidate_cache()
    yield
    catalog.invalidate_cache()


def test_standard_import() -> None:
    # Set up legacy KV
    core_kv.upsert("line_tag", "line1", "4K, fast")
    core_kv.upsert("line_tag", "prem2", "VIP")
    core_kv.upsert("free_premium_line", "prem2", "1")

    legacy_source = LegacyEnvSource(
        defaults={
            "STREAM_BACKEND": ["line1", "line2"],
            "PREMIUM_STREAM_BACKEND": ["prem1", "prem2"],
        }
    )

    imported = catalog.import_legacy_line_catalog_if_needed(legacy_source)
    assert imported is True

    # Catalog state
    assert catalog.normal_lines() == ["line1", "line2"]
    assert catalog.premium_lines() == ["prem1", "prem2"]
    assert catalog.line_tags("line1") == ["4K", "fast"]
    assert catalog.line_tags("prem2") == ["VIP"]
    assert catalog.free_premium_lines() == ["prem2"]

    # Old KV deleted
    assert core_kv.get_all("line_tag") == {}
    assert core_kv.get_all("free_premium_line") == {}

    # Marker created
    marker = core_kv.get("lines", "catalog_imported")
    assert marker is not None
    assert "imported_at" in marker


def test_import_with_duplicates_and_orphans() -> None:
    # Orphan tag and orphan free premium mark
    core_kv.upsert("line_tag", "orphan_line", "orphan_tag")
    core_kv.upsert("free_premium_line", "orphan_free", "1")

    # Free premium on normal line
    core_kv.upsert("free_premium_line", "normal_line", "1")

    # Tag for shared line
    core_kv.upsert("line_tag", "shared_line", "shared_tag")

    legacy_source = LegacyEnvSource(
        defaults={
            # Duplicate in normal: "normal_line" appears twice
            "STREAM_BACKEND": ["normal_line", "normal_line", "shared_line"],
            # Duplicate across lists: "shared_line" appears in both normal and premium
            # Duplicate in premium: "prem_1" appears twice
            "PREMIUM_STREAM_BACKEND": ["shared_line", "prem_1", "prem_1"],
        }
    )

    imported = catalog.import_legacy_line_catalog_if_needed(legacy_source)
    assert imported is True

    # Deduplicated normal lines
    assert catalog.normal_lines() == ["normal_line", "shared_line"]

    # Shared line kept in normal, excluded from premium; duplicate prem_1 deduplicated
    assert catalog.premium_lines() == ["prem_1"]

    # Normal line free_open is 0 despite free_premium_line entry
    assert catalog.free_premium_lines() == []

    # Tags on valid lines imported
    assert catalog.line_tags("shared_line") == ["shared_tag"]

    # Old KV deleted
    assert core_kv.get_all("line_tag") == {}
    assert core_kv.get_all("free_premium_line") == {}


def test_repeated_import_skips_and_env_modifications_ignored() -> None:
    legacy_source = LegacyEnvSource(
        defaults={
            "STREAM_BACKEND": ["line-init"],
            "PREMIUM_STREAM_BACKEND": ["prem-init"],
        }
    )

    # First run imports
    assert catalog.import_legacy_line_catalog_if_needed(legacy_source) is True
    assert catalog.normal_lines() == ["line-init"]

    # Second run skips
    assert catalog.import_legacy_line_catalog_if_needed(legacy_source) is False

    # Modifying .env source afterward has NO effect on catalog
    changed_env = LegacyEnvSource(
        defaults={
            "STREAM_BACKEND": ["different-line-1", "different-line-2"],
            "PREMIUM_STREAM_BACKEND": ["different-prem"],
        }
    )
    assert catalog.import_legacy_line_catalog_if_needed(changed_env) is False
    assert catalog.normal_lines() == ["line-init"]
    assert catalog.premium_lines() == ["prem-init"]
