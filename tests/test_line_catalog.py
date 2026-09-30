"""Unit tests for line catalog domain functions and specifications."""

from __future__ import annotations

import pytest

from app.domains.lines import catalog


@pytest.fixture(autouse=True)
def clean_catalog(session_env):
    """Ensure catalog cache is invalidated for every test."""
    catalog.invalidate_cache()
    yield
    catalog.invalidate_cache()


def test_add_and_list_normal_and_premium_lines() -> None:
    catalog.add_line("line-b", premium=False)
    catalog.add_line("line-a", premium=False)
    assert catalog.normal_lines() == ["line-b", "line-a"]

    catalog.add_line("prem-2", premium=True)
    catalog.add_line("prem-1", premium=True)
    assert catalog.premium_lines() == ["prem-2", "prem-1"]


def test_reject_duplicate_same_kind() -> None:
    catalog.add_line("line-1", premium=False)
    with pytest.raises(ValueError, match="该线路已存在"):
        catalog.add_line("line-1", premium=False)

    catalog.add_line("prem-1", premium=True)
    with pytest.raises(ValueError, match="该线路已存在"):
        catalog.add_line("prem-1", premium=True)


def test_reject_cross_type_duplicate() -> None:
    catalog.add_line("shared-line", premium=False)
    with pytest.raises(ValueError, match="该线路已存在于另一线路列表中"):
        catalog.add_line("shared-line", premium=True)

    catalog.add_line("prem-only", premium=True)
    with pytest.raises(ValueError, match="该线路已存在于另一线路列表中"):
        catalog.add_line("prem-only", premium=False)


def test_reject_illegal_names() -> None:
    with pytest.raises(ValueError, match="线路名称不能为空"):
        catalog.add_line("", premium=False)

    with pytest.raises(ValueError, match="线路名称不能为空"):
        catalog.add_line("   ", premium=True)

    with pytest.raises(ValueError, match="线路名称不能包含 / 或 ,"):
        catalog.add_line("line/slash", premium=False)

    with pytest.raises(ValueError, match="线路名称不能包含 / 或 ,"):
        catalog.add_line("line,comma", premium=True)


def test_delete_line_and_preserve_remaining_order() -> None:
    catalog.add_line("line-1", premium=False)
    catalog.add_line("line-2", premium=False)
    catalog.add_line("line-3", premium=False)

    catalog.delete_line("line-2", premium=False)
    assert catalog.normal_lines() == ["line-1", "line-3"]

    with pytest.raises(ValueError, match="该线路不存在"):
        catalog.delete_line("non-existent", premium=False)


def test_set_line_tags_normalization_and_order() -> None:
    catalog.add_line("line-1", premium=False)

    # Whitespace stripping, deduplication preserving submission order, empty dropped
    assert catalog.set_line_tags("line-1", ["低延迟", " 4K ", "低延迟", ""])
    assert catalog.line_tags("line-1") == ["低延迟", "4K"]

    # Comma separation
    assert catalog.set_line_tags("line-1", ["高速, 稳定", "4K,低延迟", ""])
    assert catalog.line_tags("line-1") == ["高速", "稳定", "4K", "低延迟"]

    # Non-existent line rejected
    assert not catalog.set_line_tags("non-existent", ["4K"])
    assert catalog.line_tags("non-existent") == []


def test_delete_line_tags() -> None:
    catalog.add_line("line-1", premium=False)
    catalog.set_line_tags("line-1", ["4K"])
    assert catalog.line_tags("line-1") == ["4K"]

    assert catalog.delete_line_tags("line-1")
    assert catalog.line_tags("line-1") == []

    assert not catalog.delete_line_tags("non-existent")


def test_all_line_tags_ordering() -> None:
    catalog.add_line("normal-2", premium=False)
    catalog.add_line("normal-1", premium=False)
    catalog.add_line("premium-2", premium=True)
    catalog.add_line("premium-1", premium=True)

    catalog.set_line_tags("normal-2", ["tag-n2"])
    catalog.set_line_tags("premium-1", ["tag-p1"])

    tags_map = catalog.all_line_tags()
    keys = list(tags_map.keys())
    assert keys == ["normal-2", "normal-1", "premium-2", "premium-1"]
    assert tags_map["normal-2"] == ["tag-n2"]
    assert tags_map["normal-1"] == []
    assert tags_map["premium-2"] == []
    assert tags_map["premium-1"] == ["tag-p1"]


def test_free_premium_lines_validation_and_ordering() -> None:
    catalog.add_line("normal-1", premium=False)
    catalog.add_line("prem-b", premium=True)
    catalog.add_line("prem-a", premium=True)
    catalog.add_line("prem-c", premium=True)

    # Valid setting
    assert catalog.set_free_premium_lines(["prem-a", "prem-b"])
    # Ordered by catalog position (prem-b was added first, then prem-a)
    assert catalog.free_premium_lines() == ["prem-b", "prem-a"]

    # Attempting to set normal line as free premium rejected
    assert not catalog.set_free_premium_lines(["prem-a", "normal-1"])
    # Free premium lines stay unchanged
    assert catalog.free_premium_lines() == ["prem-b", "prem-a"]

    # Attempting to set non-existent line rejected
    assert not catalog.set_free_premium_lines(["prem-a", "non-existent"])
    assert catalog.free_premium_lines() == ["prem-b", "prem-a"]

    # Updating to a single line
    assert catalog.set_free_premium_lines(["prem-c"])
    assert catalog.free_premium_lines() == ["prem-c"]


def test_cache_invalidation_on_writes() -> None:
    catalog.add_line("line-1", premium=False)
    assert catalog.normal_lines() == ["line-1"]

    # Cache hit
    assert catalog.normal_lines() == ["line-1"]

    # Invalidation on add
    catalog.add_line("line-2", premium=False)
    assert catalog.normal_lines() == ["line-1", "line-2"]

    # Invalidation on delete
    catalog.delete_line("line-1", premium=False)
    assert catalog.normal_lines() == ["line-2"]


def test_inflight_read_cannot_repopulate_cache_after_invalidation(monkeypatch):
    from types import SimpleNamespace

    old = SimpleNamespace(name="old", kind="normal")
    new = SimpleNamespace(name="new", kind="normal")
    reads = []

    def read_entries():
        reads.append(True)
        if len(reads) == 1:
            # Simulate a committed catalog mutation between read and cache fill.
            catalog.invalidate_cache()
            return [old]
        return [new]

    monkeypatch.setattr(
        catalog.repository_catalog, "get_all_catalog_entries", read_entries
    )
    assert catalog.normal_lines() == ["new"]
    assert catalog.normal_lines() == ["new"]
    assert len(reads) == 2
