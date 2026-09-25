"""Repository package splitting preserves methods, constants, and line limits."""

import ast
from pathlib import Path

import pytest

from scripts.refactor.split_repository import SplitError, split_repository


def _member_names(tree: ast.Module) -> list[str]:
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    return [node.name for node in cls.body if isinstance(node, ast.FunctionDef)]


def test_splits_all_repository_members_without_loss(tmp_path: Path) -> None:
    source = tmp_path / "repository.py"
    source.write_text(
        "CONST = 1\n\n\nclass ExampleRepository:\n"
        '    """Original class docstring."""\n'
        + "".join(
            f"    def method_{i}(self):\n        return CONST + {i}\n\n"
            for i in range(20)
        )
        + "    @staticmethod\n"
        "    def referenced():\n"
        "        return ExampleRepository.method_1\n",
        encoding="utf-8",
    )
    staged = split_repository(source, max_lines=200)
    old_tree = ast.parse(source.read_text())
    found: list[str] = []
    for destination, content in staged.items():
        assert len(content.splitlines()) <= 1000, destination
        found.extend(_member_names(ast.parse(content)))
    assert len(found) == len(set(found))
    assert set(found) == set(_member_names(old_tree))
    assembly = staged[tmp_path / "repository/__init__.py"]
    assert "CONST = 1" in assembly
    assert "Original class docstring." in assembly
    assert "def referenced()" in assembly
    assert any(path.name.startswith("part_") for path in staged)


def test_split_rejects_trailing_execution(tmp_path: Path) -> None:
    path = tmp_path / "repository.py"
    path.write_text("class Repository:\n    pass\n\nprint('side effect')\n")
    with pytest.raises(SplitError, match="trailing code"):
        split_repository(path)
