"""Inventory and mapping-coverage fixture tests."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.refactor.inventory import coverage, inventory


def test_inventory_captures_comments_decorators_and_nested_members(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src/app/domains/sample/repository.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """# preliminary explanation
@wrapper
class Repository:
    # this belongs to the method
    @classmethod
    def run(cls):
        return True

    status: str = 'ready'

value, other = 1, 2
""",
        encoding="utf-8",
    )
    items = inventory([source], root=tmp_path)
    by_name = {item.name: item for item in items}
    assert by_name["Repository"].start_line == 1
    assert by_name["Repository.run"].start_line == 4
    assert by_name["Repository.run"].end_line == 7
    assert by_name["Repository.run"].kind == "method"
    assert by_name["Repository.run"].parent_id == by_name["Repository"].id
    assert by_name["Repository.status"].kind == "attribute"
    assert by_name["value"].kind == "assignment"
    assert by_name["other"].kind == "assignment"
    assert by_name["other"].unit_id == by_name["value"].unit_id
    assert "lineno" not in by_name["Repository.run"].ast
    assert items == inventory([source], root=tmp_path)
    assert json.dumps([item.id for item in items]) == json.dumps(
        [item.id for item in inventory([source], root=tmp_path)]
    )


def test_mapping_coverage_reports_missing_todo_and_deletion(tmp_path: Path) -> None:
    source = tmp_path / "src/app/sample.py"
    source.parent.mkdir(parents=True)
    source.write_text("x = 1\ny = 2\nz = 3\n", encoding="utf-8")
    items = inventory([source], root=tmp_path)
    mapping = tmp_path / "mapping.toml"
    mapping.write_text(
        """[[items]]
id = 'app.sample:x'
target = 'app.domains.sample.constants'

[[items]]
id = 'app.sample:y'
target = 'TODO'
""",
        encoding="utf-8",
    )
    assert coverage(items, mapping) == {
        "missing": ["app.sample:z"],
        "todo": ["app.sample:y"],
        "invalid": [],
        "stale": [],
    }
    with mapping.open("a", encoding="utf-8") as output:
        output.write(
            "\n[[items]]\nid = 'app.sample:z'\naction = 'delete'\nreason = 'dead compatibility layer'\n"
        )
    assert coverage(items, mapping) == {
        "missing": [],
        "todo": ["app.sample:y"],
        "invalid": [],
        "stale": [],
    }


def test_inventory_records_top_level_execution_and_import_only_packages(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src/app/log.py"
    cache = tmp_path / "src/app/databases/cache.py"
    package = tmp_path / "src/app/databases/__init__.py"
    for path in (source, cache, package):
        path.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        '"""Logging setup."""\nimport logging\nlogger = logging.getLogger()\n'
        "while logger.handlers:\n    logger.handlers.pop()\n",
        encoding="utf-8",
    )
    cache.write_text(
        "try:\n    from redis.exceptions import RedisError\nexcept ImportError:\n"
        "    RedisError = RuntimeError\n",
        encoding="utf-8",
    )
    package.write_text(
        "# package public API\nfrom .db import db\n__all__ = ['db']\n",
        encoding="utf-8",
    )
    items = inventory([source, cache, package], root=tmp_path)
    by_module: dict[str, list] = {}
    for item in items:
        by_module.setdefault(item.module, []).append(item)
    assert {item.kind for item in by_module["app.log"]} >= {
        "docstring",
        "import",
        "assignment",
        "statement",
    }
    assert any("While(" in item.ast for item in by_module["app.log"])
    assert any("Try(" in item.ast for item in by_module["app.databases.cache"])
    assert {item.kind for item in by_module["app.databases"]} == {
        "package_import",
        "export",
    }
    assert (
        next(
            item for item in by_module["app.databases"] if item.kind == "package_import"
        ).start_line
        == 1
    )
    assert items == inventory([source, cache, package], root=tmp_path)
