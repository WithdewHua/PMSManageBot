"""基线键改写脚本的单元测试（搬移 2.1 的验收）。"""

from __future__ import annotations

import pytest

from scripts.refactor.rewrite_baseline_keys import (
    BaselineMoveError,
    MoveRecord,
    enclosing_symbol,
    load_moves,
    rewrite_entries,
)

SOURCE = (
    "from app.databases import db\n"  # line 1: module level
    "\n"
    "class GiftPackRepository:\n"  # line 3
    "    def _grant_x(self):\n"  # line 4
    "        db.first()\n"  # line 5
    "\n"
    "    def _grant_y(self):\n"  # line 7
    "        db.second()\n"  # line 8
)

OLD_PATH = "src/app/domains/gift_pack/repository/part_1.py"
NEW_PATH = "src/app/domains/gift_pack/repository/rewards.py"
PACKS_PATH = "src/app/domains/gift_pack/repository/packs.py"


def _entry(
    *,
    path: str,
    line: int,
    target: str,
    kind: str = "facade_call",
    owner: str = "promote-gift-pack-domain",
    key: str | None = None,
    **extra,
) -> dict:
    return {
        "key": key or f"call|{path}|{line}|facade|identity|{target}",
        "owner": owner,
        "path": path,
        "line": line,
        "kind": kind,
        "source_domain": "gift_pack",
        "target_domain": "identity",
        "target": target,
        **extra,
    }


def _read_source(path: str) -> str:
    if path == OLD_PATH:
        return SOURCE
    raise AssertionError(f"unexpected source read: {path}")


MOVES = {
    OLD_PATH: MoveRecord(
        source=OLD_PATH,
        module_level=PACKS_PATH,
        symbols={"_grant_x": NEW_PATH, "_grant_y": NEW_PATH},
    )
}


def test_enclosing_symbol_picks_innermost_definition() -> None:
    assert enclosing_symbol(SOURCE, 1) is None
    assert enclosing_symbol(SOURCE, 5) == "_grant_x"
    assert enclosing_symbol(SOURCE, 8) == "_grant_y"
    assert enclosing_symbol(SOURCE, 3) == "GiftPackRepository"


def test_rewrites_moved_entries_and_preserves_review_metadata() -> None:
    old = [
        _entry(path=OLD_PATH, line=5, target="first", b3_source_id="legacy.py:f"),
        _entry(path=OLD_PATH, line=8, target="second"),
        _entry(path=OLD_PATH, line=1, target="imported_symbol", kind="import"),
    ]
    new = [
        _entry(path=NEW_PATH, line=42, target="first"),
        _entry(path=NEW_PATH, line=51, target="second"),
        _entry(path=PACKS_PATH, line=7, target="imported_symbol", kind="import"),
    ]

    rewritten = rewrite_entries(old, new, MOVES, _read_source)

    # 结果按新 key 排序：packs.py 在 rewards.py 之前
    assert [entry["path"] for entry in rewritten] == [PACKS_PATH, NEW_PATH, NEW_PATH]
    assert [entry["line"] for entry in rewritten] == [7, 42, 51]
    assert rewritten[1]["key"] == f"call|{NEW_PATH}|42|facade|identity|first"
    # 评审元数据保留：owner 与来源标记不随行号改写
    assert all(entry["owner"] == "promote-gift-pack-domain" for entry in rewritten)
    assert rewritten[1]["b3_source_id"] == "legacy.py:f"


def test_accepts_line_shift_in_unmoved_file() -> None:
    old = [_entry(path=PACKS_PATH, line=10, target="x")]
    new = [_entry(path=PACKS_PATH, line=14, target="x")]
    rewritten = rewrite_entries(old, new, MOVES, _read_source)
    assert rewritten[0]["line"] == 14


def test_rejects_multiset_change_on_removal() -> None:
    old = [
        _entry(path=OLD_PATH, line=5, target="first"),
        _entry(path=OLD_PATH, line=8, target="second"),
    ]
    new = [_entry(path=NEW_PATH, line=42, target="first")]

    with pytest.raises(BaselineMoveError, match="多重集合变化"):
        rewrite_entries(old, new, MOVES, _read_source)


def test_rejects_multiset_change_on_addition() -> None:
    old = [_entry(path=OLD_PATH, line=5, target="first")]
    new = [
        _entry(path=NEW_PATH, line=42, target="first"),
        _entry(path=NEW_PATH, line=43, target="surprise"),
    ]

    with pytest.raises(BaselineMoveError, match="多出条目"):
        rewrite_entries(old, new, MOVES, _read_source)


def test_rejects_missing_mapping_for_a_moved_symbol() -> None:
    old = [_entry(path=OLD_PATH, line=8, target="second")]
    new = [_entry(path=NEW_PATH, line=51, target="second")]
    partial = {
        OLD_PATH: MoveRecord(
            source=OLD_PATH, module_level=None, symbols={"_grant_x": NEW_PATH}
        )
    }

    with pytest.raises(BaselineMoveError, match="映射缺失"):
        rewrite_entries(old, new, partial, _read_source)


def test_rejects_undeclared_move() -> None:
    old = [_entry(path=OLD_PATH, line=5, target="first")]
    new = [_entry(path=NEW_PATH, line=42, target="first")]

    with pytest.raises(BaselineMoveError, match="未登记搬移"):
        rewrite_entries(old, new, {}, _read_source)


def test_rejects_target_mismatch() -> None:
    old = [_entry(path=OLD_PATH, line=5, target="first")]
    new = [_entry(path=PACKS_PATH, line=42, target="first")]

    with pytest.raises(BaselineMoveError, match="映射不一致"):
        rewrite_entries(old, new, MOVES, _read_source)


def test_rejects_disagreement_with_mapping_toml_plan() -> None:
    old = [_entry(path=OLD_PATH, line=5, target="first")]
    new = [_entry(path=NEW_PATH, line=42, target="first")]

    with pytest.raises(BaselineMoveError, match="planned_target 不一致"):
        rewrite_entries(
            old,
            new,
            MOVES,
            _read_source,
            planned_targets={"_grant_x": "app.domains.gift_pack.repository.packs"},
        )


def test_accepts_matching_mapping_toml_plan() -> None:
    old = [_entry(path=OLD_PATH, line=5, target="first")]
    new = [_entry(path=NEW_PATH, line=42, target="first")]

    rewritten = rewrite_entries(
        old,
        new,
        MOVES,
        _read_source,
        planned_targets={"_grant_x": "app.domains.gift_pack.repository.rewards"},
    )

    assert rewritten[0]["path"] == NEW_PATH


def test_load_moves_reads_the_declared_mapping(tmp_path) -> None:
    path = tmp_path / "moves.toml"
    path.write_text(
        """
[[move]]
source = "src/app/domains/x/repository/part_1.py"
module_level = "src/app/domains/x/repository/notes.py"

[move.symbols]
do_thing = "src/app/domains/x/repository/things.py"
""",
        encoding="utf-8",
    )

    moves = load_moves(path)

    assert moves["src/app/domains/x/repository/part_1.py"].symbols == {
        "do_thing": "src/app/domains/x/repository/things.py"
    }
    assert moves["src/app/domains/x/repository/part_1.py"].module_level.endswith(
        "notes.py"
    )


def test_load_moves_rejects_duplicates_and_empty_files(tmp_path) -> None:
    duplicate = tmp_path / "dup.toml"
    duplicate.write_text(
        """
[[move]]
source = "a.py"

[[move]]
source = "a.py"
""",
        encoding="utf-8",
    )
    with pytest.raises(BaselineMoveError, match="重复登记"):
        load_moves(duplicate)

    empty = tmp_path / "empty.toml"
    empty.write_text("# nothing here\n", encoding="utf-8")
    with pytest.raises(BaselineMoveError, match="没有登记"):
        load_moves(empty)
