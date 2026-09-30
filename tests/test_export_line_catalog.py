"""Unit tests for scripts/export_line_catalog.py rollback export."""

from __future__ import annotations

import pytest

from app.core import kv as core_kv
from app.domains.lines import catalog
from scripts.export_line_catalog import apply_kv_restore, generate_export_content


@pytest.fixture(autouse=True)
def clean_catalog(session_env):
    catalog.invalidate_cache()
    yield
    catalog.invalidate_cache()


def test_export_and_apply_preserves_legacy_compatibility() -> None:
    # Set up catalog
    catalog.add_line("line1", premium=False)
    catalog.add_line("line2", premium=False)
    catalog.add_line("prem1", premium=True)
    catalog.add_line("prem2", premium=True)

    catalog.set_line_tags("line1", ["4K", "fast"])
    catalog.set_line_tags("prem2", ["VIP"])
    catalog.set_free_premium_lines(["prem2"])

    # 1. Generate export content (read-only)
    env_lines, sql_statements = generate_export_content()

    assert "STREAM_BACKEND=line1,line2" in env_lines
    assert "PREMIUM_STREAM_BACKEND=prem1,prem2" in env_lines
    assert any("line_tag" in stmt for stmt in sql_statements)
    assert any("free_premium_line" in stmt for stmt in sql_statements)

    # 2. Apply KV restore directly
    result = apply_kv_restore()
    assert result["tags_restored"] == 2
    assert result["free_premium_restored"] == 1

    # 3. Verify reading with legacy code semantics gives identical results
    # Reading .env:
    for line in env_lines:
        if line.startswith("STREAM_BACKEND="):
            normal_from_env = [
                item.strip()
                for item in line.split("=", 1)[1].split(",")
                if item.strip()
            ]
        elif line.startswith("PREMIUM_STREAM_BACKEND="):
            premium_from_env = [
                item.strip()
                for item in line.split("=", 1)[1].split(",")
                if item.strip()
            ]

    assert normal_from_env == ["line1", "line2"]
    assert premium_from_env == ["prem1", "prem2"]

    # Reading KV with legacy semantics:
    raw_tags = core_kv.get_all("line_tag")
    legacy_tags_line1 = [
        tag.strip() for tag in raw_tags.get("line1", "").split(",") if tag.strip()
    ]
    legacy_tags_prem2 = [
        tag.strip() for tag in raw_tags.get("prem2", "").split(",") if tag.strip()
    ]
    assert legacy_tags_line1 == ["4K", "fast"]
    assert legacy_tags_prem2 == ["VIP"]

    raw_free = core_kv.get_all("free_premium_line")
    legacy_free_lines = [k for k, v in raw_free.items() if v == "1"]
    assert legacy_free_lines == ["prem2"]

    # Import marker removed for rollback
    assert core_kv.get("lines", "catalog_imported") is None
