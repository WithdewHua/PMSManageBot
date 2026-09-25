"""Small-package safety fixtures for the mechanical source relocator."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.refactor.inventory import inventory
from scripts.refactor.relocate import RelocationError, apply, plan


def _source(root: Path, module: str, code: str) -> Path:
    path = root / "src" / (module.replace(".", "/") + ".py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")
    return path


def _mapping(path: Path, target: str, root: Path) -> dict[str, dict]:
    return {
        item.id: {"target": target, "kind": item.kind, "reason": "fixture"}
        for item in inventory([path], root=root)
    }


def test_source_slices_include_comment_decorator_import_and_execution(
    tmp_path: Path,
) -> None:
    original = _source(
        tmp_path,
        "app.old",
        '"""Module docstring."""\nfrom math import sqrt\nvalue = 9\n'
        "while value < 10:\n    value += 1\n\n"
        "def decorate(fn):\n    return fn\n\n"
        "# keep this comment\n@decorate\ndef calculate():\n    return sqrt(value)\n",
    )
    staged = plan(tmp_path, [original], _mapping(original, "app.new", tmp_path))
    destination = tmp_path / "src/app/new.py"
    result = staged[destination]
    assert result.index("Module docstring") < result.index("while value")
    assert "# keep this comment\n@decorate\ndef calculate" in result
    assert "from math import sqrt" in result
    assert not destination.exists()
    apply(staged)
    assert destination.read_text(encoding="utf-8") == result
    assert not original.exists()


def test_global_rebinding_split_refuses_without_changes(tmp_path: Path) -> None:
    original = _source(
        tmp_path,
        "app.old",
        "counter = 0\ndef tick():\n    global counter\n    counter += 1\n",
    )
    mapping = _mapping(original, "app.new", tmp_path)
    mapping["app.old:counter"]["target"] = "app.state"
    with pytest.raises(RelocationError, match="global rebinding"):
        plan(tmp_path, [original], mapping)
    assert original.exists() and not (tmp_path / "src/app/new.py").exists()


def test_unreviewed_and_conflicting_parent_child_mapping_refuse(tmp_path: Path) -> None:
    original = _source(
        tmp_path,
        "app.old",
        "class Store:\n    def get(self):\n        return 1\n",
    )
    mapping = _mapping(original, "app.new", tmp_path)
    mapping["app.old:Store.get"]["target"] = "TODO"
    with pytest.raises(RelocationError, match="unreviewed"):
        plan(tmp_path, [original], mapping)
    mapping["app.old:Store.get"]["target"] = "app.other"
    with pytest.raises(RelocationError, match="overlapping class"):
        plan(tmp_path, [original], mapping)
    assert original.read_text().startswith("class Store")


def test_atomic_multi_name_assignment_cannot_split(tmp_path: Path) -> None:
    original = _source(tmp_path, "app.old", "left, right = 1, 2\n")
    mapping = _mapping(original, "app.new", tmp_path)
    mapping["app.old:left"]["target"] = "app.other"
    with pytest.raises(RelocationError, match="conflicting destinations"):
        plan(tmp_path, [original], mapping)


def test_new_import_cycle_refuses_before_writing(tmp_path: Path) -> None:
    first = _source(tmp_path, "app.first", "from app.two import b\na = 1\n")
    second = _source(tmp_path, "app.second", "from app.one import a\nb = 2\n")
    mapping = {
        **_mapping(first, "app.one", tmp_path),
        **_mapping(second, "app.two", tmp_path),
    }
    with pytest.raises(RelocationError, match="cycle"):
        plan(tmp_path, [first, second], mapping)
    assert first.exists() and second.exists()


def test_split_facade_assembles_mixins_without_duplicate_members(
    tmp_path: Path,
) -> None:
    source = _source(
        tmp_path,
        "app.db",
        "from math import sqrt\n"
        "class DatabaseORM:\n"
        "    # class documentation\n"
        "    VALUE = 4\n\n"
        "    def square_root(self):\n        return sqrt(self.VALUE)\n\n"
        "    def another(self):\n        return self.square_root()\n\n"
        "db = DatabaseORM()\n",
    )
    mapping = _mapping(source, "app.db", tmp_path)
    mapping["app.db:DatabaseORM"]["action"] = "assemble"
    mapping["app.db:DatabaseORM.square_root"].update(
        target="app.first.repository", **{"class": "FirstRepository"}
    )
    mapping["app.db:DatabaseORM.another"].update(
        target="app.second.repository", **{"class": "SecondRepository"}
    )
    staged = plan(tmp_path, [source], mapping)
    facade = staged[source]
    assert facade is not None
    assert "class DatabaseORM(FirstRepository, SecondRepository):" in facade
    assert "    VALUE = 4" in facade
    assert "    def square_root" not in facade
    assert "class FirstRepository:" in staged[tmp_path / "src/app/first/repository.py"]
    assert (
        "class SecondRepository:" in staged[tmp_path / "src/app/second/repository.py"]
    )
    assert "from math import sqrt" in staged[tmp_path / "src/app/first/repository.py"]


def test_package_exports_and_try_block_are_not_dropped(tmp_path: Path) -> None:
    package = tmp_path / "src/app/old/__init__.py"
    package.parent.mkdir(parents=True)
    package.write_text(
        "from .client import Client\n__all__ = ['Client']\n",
        encoding="utf-8",
    )
    cache = _source(
        tmp_path,
        "app.cache",
        "try:\n    from redis.exceptions import RedisError\n"
        "except ImportError:\n    RedisError = RuntimeError\n",
    )
    mapping = {
        **_mapping(package, "app.old", tmp_path),
        **_mapping(cache, "app.core.cache", tmp_path),
    }
    staged = plan(tmp_path, [package, cache], mapping)
    assert "from .client import Client" in staged[package]
    assert "__all__ = ['Client']" in staged[package]
    assert "except ImportError:" in staged[tmp_path / "src/app/core/cache.py"]
    assert staged[cache] is None


def test_existing_destination_is_not_overwritten(tmp_path: Path) -> None:
    source = _source(tmp_path, "app.old", "value = 1\n")
    destination = _source(tmp_path, "app.new", "valuable = 2\n")
    with pytest.raises(RelocationError, match="already exists"):
        plan(tmp_path, [source], _mapping(source, "app.new", tmp_path))
    assert source.read_text() == "value = 1\n"
    assert destination.read_text() == "valuable = 2\n"


def test_moved_module_keeps_docstring_and_future_import_first(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "app.old",
        '"""Original docstring."""\nfrom __future__ import annotations\n'
        "from math import sqrt\n\ndef compute(number: float) -> float:\n"
        "    return sqrt(number)\n",
    )
    mapping = _mapping(source, "app.old", tmp_path)
    mapping["app.old:compute"]["target"] = "app.new"
    staged = plan(tmp_path, [source], mapping)
    moved = staged[tmp_path / "src/app/new.py"]
    assert moved.startswith("from __future__ import annotations\n")
    assert moved.index("from math import sqrt") < moved.index("def compute")
    assert staged[source].startswith('"""Original docstring."""\n')


def test_reference_rewrites_cover_all_roots_and_moved_relative_imports(
    tmp_path: Path,
) -> None:
    helper = _source(tmp_path, "app.legacy.helpers", "def helper():\n    return 42\n")
    old = _source(
        tmp_path,
        "app.legacy.old",
        "from .helpers import helper\n__all__ = ['run']\n"
        "def run():\n    return helper()\n",
    )
    mapping = {
        **_mapping(old, "app.domains.jobs", tmp_path),
        **_mapping(helper, "app.domains.helpers", tmp_path),
    }
    for directory in ("tests", "scripts", "alembic"):
        consumer = tmp_path / directory / "consumer.py"
        consumer.parent.mkdir(parents=True)
        consumer.write_text(
            "from app.legacy.old import *\n"
            "from app.legacy.old import run as renamed\n"
            "def invoke():\n    from app.legacy.helpers import helper\n"
            "    return helper()\n"
            'scheduler.add_job("app.legacy.old:run")\n'
            'prose = "app.legacy.old:run"\n',
            encoding="utf-8",
        )
    staged = plan(tmp_path, [old, helper], mapping)
    moved = staged[tmp_path / "src/app/domains/jobs.py"]
    assert "from app.domains.helpers import helper" in moved
    assert "from app.legacy.helpers" not in moved
    for directory in ("tests", "scripts", "alembic"):
        consumer = staged[tmp_path / directory / "consumer.py"]
        assert "from app.domains.jobs import run" in consumer
        assert "from app.domains.helpers import helper" in consumer
        assert 'scheduler.add_job("app.domains.jobs:run")' in consumer
        assert 'prose = "app.legacy.old:run"' in consumer
    assert staged[old] is None and staged[helper] is None


def test_reviewed_database_orm_self_reference_uses_own_mixin(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "app.db",
        "class DatabaseORM:\n"
        "    def get(self):\n        return DatabaseORM.get(self)\n"
        "db = DatabaseORM()\n",
    )
    mapping = _mapping(source, "app.db", tmp_path)
    mapping["app.db:DatabaseORM"]["action"] = "assemble"
    mapping["app.db:DatabaseORM.get"].update(
        target="app.domains.sample.repository", **{"class": "SampleRepository"}
    )
    staged = plan(tmp_path, [source], mapping)
    mixin = staged[tmp_path / "src/app/domains/sample/repository.py"]
    assert "return SampleRepository.get(self)" in mixin
    assert "DatabaseORM.get" not in mixin


def test_unreviewed_database_orm_reference_refuses_without_writes(
    tmp_path: Path,
) -> None:
    source = _source(
        tmp_path,
        "app.db",
        "class DatabaseORM:\n"
        "    def get(self):\n        return DatabaseORM.unknown(self)\n"
        "db = DatabaseORM()\n",
    )
    mapping = _mapping(source, "app.db", tmp_path)
    mapping["app.db:DatabaseORM"]["action"] = "assemble"
    mapping["app.db:DatabaseORM.get"].update(
        target="app.domains.sample.repository", **{"class": "SampleRepository"}
    )
    with pytest.raises(RelocationError, match="unresolved DatabaseORM"):
        plan(tmp_path, [source], mapping)
    assert not (tmp_path / "src/app/domains/sample/repository.py").exists()


def test_nested_function_local_does_not_hide_outer_import(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "app.old",
        "from math import sqrt\n"
        "def calculate():\n"
        "    def nested():\n        sqrt = 99\n        return sqrt\n"
        "    return sqrt(4)\n",
    )
    mapping = _mapping(source, "app.old", tmp_path)
    mapping["app.old:calculate"]["target"] = "app.new"
    staged = plan(tmp_path, [source], mapping)
    moved = staged[tmp_path / "src/app/new.py"]
    assert "from math import sqrt" in moved


def test_split_module_import_without_single_destination_refuses(tmp_path: Path) -> None:
    source = _source(
        tmp_path, "app.old", "def one():\n    pass\ndef two():\n    pass\n"
    )
    consumer = tmp_path / "tests/test_consumer.py"
    consumer.parent.mkdir(parents=True)
    consumer.write_text("import app.old\n", encoding="utf-8")
    mapping = _mapping(source, "app.first", tmp_path)
    mapping["app.old:two"]["target"] = "app.second"
    with pytest.raises(RelocationError, match="removed module"):
        plan(tmp_path, [source], mapping)
    assert consumer.read_text() == "import app.old\n"
    assert source.exists()


def test_unrewritable_dynamic_callable_path_refuses(tmp_path: Path) -> None:
    source = _source(tmp_path, "app.old", "def run():\n    pass\n")
    consumer = tmp_path / "scripts/caller.py"
    consumer.parent.mkdir(parents=True)
    consumer.write_text('scheduler.add_job(f"app.old:{name}")\n', encoding="utf-8")
    with pytest.raises(RelocationError, match="callable path still points"):
        plan(tmp_path, [source], _mapping(source, "app.new", tmp_path))
    assert consumer.read_text() == 'scheduler.add_job(f"app.old:{name}")\n'


def test_import_cycle_through_untouched_module_is_rejected(tmp_path: Path) -> None:
    original = _source(
        tmp_path,
        "app.old",
        "from app.consumer import value\ndef calculate():\n    return value\n",
    )
    _source(tmp_path, "app.consumer", "from app.new import calculate\nvalue = 42\n")
    with pytest.raises(RelocationError, match="import cycle"):
        plan(tmp_path, [original], _mapping(original, "app.new", tmp_path))
    assert not (tmp_path / "src/app/new.py").exists()


def test_preexisting_unrelated_cycle_does_not_block_move(tmp_path: Path) -> None:
    _source(tmp_path, "app.a", "import app.b\n")
    _source(tmp_path, "app.b", "import app.a\n")
    old = _source(tmp_path, "app.old", "value = 1\n")
    assert tmp_path / "src/app/new.py" in plan(
        tmp_path, [old], _mapping(old, "app.new", tmp_path)
    )


def test_explicit_deletion_requires_reason_and_no_target(tmp_path: Path) -> None:
    source = _source(tmp_path, "app.old", "unused = 1\nkept = 2\n")
    mapping = _mapping(source, "app.new", tmp_path)
    mapping["app.old:unused"] = {"action": "delete", "reason": "confirmed dead"}
    staged = plan(tmp_path, [source], mapping)
    assert "unused" not in staged[tmp_path / "src/app/new.py"]
    mapping["app.old:unused"]["reason"] = ""
    with pytest.raises(RelocationError, match="deletion without reason"):
        plan(tmp_path, [source], mapping)


def test_assembly_without_any_mixin_cannot_drop_parent(tmp_path: Path) -> None:
    source = _source(
        tmp_path, "app.old", "class Store:\n    def get(self):\n        return 1\n"
    )
    mapping = _mapping(source, "app.old", tmp_path)
    mapping["app.old:Store"]["action"] = "assemble"
    with pytest.raises(RelocationError, match="no mixins"):
        plan(tmp_path, [source], mapping)
    assert source.exists()


def test_assembled_class_preserves_original_base_and_rejects_local_mixin(
    tmp_path: Path,
) -> None:
    source = _source(
        tmp_path,
        "app.old",
        "class Base:\n    def inherited(self):\n        return 1\n"
        "class Store(Base):\n    def get(self):\n        return 2\n",
    )
    mapping = _mapping(source, "app.old", tmp_path)
    mapping["app.old:Store"]["action"] = "assemble"
    mapping["app.old:Store.get"].update(target="app.mixin", **{"class": "StoreMixin"})
    staged = plan(tmp_path, [source], mapping)
    assert "class Store(StoreMixin, Base):" in staged[source]
    mapping["app.old:Store.get"]["target"] = "app.old"
    with pytest.raises(RelocationError, match="cannot share"):
        plan(tmp_path, [source], mapping)


def test_two_sources_cannot_shadow_same_target_definition(tmp_path: Path) -> None:
    first = _source(tmp_path, "app.a", "def run():\n    return 1\n")
    second = _source(tmp_path, "app.b", "def run():\n    return 2\n")
    mapping = {
        **_mapping(first, "app.new", tmp_path),
        **_mapping(second, "app.new", tmp_path),
    }
    with pytest.raises(RelocationError, match="target name collision"):
        plan(tmp_path, [first, second], mapping)
    assert not (tmp_path / "src/app/new.py").exists()


def test_top_level_if_rebinding_across_targets_refuses(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "app.old",
        "counter = 0\nif True:\n    counter = 1\ndef value():\n    return counter\n",
    )
    mapping = _mapping(source, "app.one", tmp_path)
    statement = next(key for key in mapping if key.startswith("app.old:@statement:"))
    mapping[statement]["target"] = "app.two"
    with pytest.raises(RelocationError, match="module-level rebinding"):
        plan(tmp_path, [source], mapping)
    assert not (tmp_path / "src/app/one.py").exists()


def test_relative_import_preserves_unchanged_sibling(tmp_path: Path) -> None:
    _source(tmp_path, "app.legacy.helpers", "def helper():\n    return 1\n")
    old = _source(
        tmp_path,
        "app.legacy.service",
        "from .helpers import helper\ndef run():\n    return helper()\n",
    )
    staged = plan(tmp_path, [old], _mapping(old, "app.new.service", tmp_path))
    moved = staged[tmp_path / "src/app/new/service.py"]
    assert "from app.legacy.helpers import helper" in moved
    assert "from app.new.helpers" not in moved


def test_export_cannot_outlive_moved_import_binding(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "app.old",
        "from app.helper import Foo\n__all__ = ['Foo']\n",
    )
    mapping = _mapping(source, "app.old", tmp_path)
    import_item = next(key for key in mapping if "@import:" in key)
    mapping[import_item]["target"] = "app.new"
    with pytest.raises(RelocationError, match="export Foo"):
        plan(tmp_path, [source], mapping)
    assert not (tmp_path / "src/app/new.py").exists()


def test_importlib_call_adds_cycle_edge(tmp_path: Path) -> None:
    old = _source(
        tmp_path,
        "app.old",
        "import importlib\nvalue = importlib.import_module('app.dep').value\n",
    )
    _source(tmp_path, "app.dep", "from app.new import value\n")
    with pytest.raises(RelocationError, match="import cycle"):
        plan(tmp_path, [old], _mapping(old, "app.new", tmp_path))
    assert old.exists() and not (tmp_path / "src/app/new.py").exists()


def test_generated_import_only_includes_used_name(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "app.old",
        "from math import sqrt, cos\ndef run():\n    return sqrt(9)\n",
    )
    mapping = _mapping(source, "app.old", tmp_path)
    mapping["app.old:run"]["target"] = "app.new"
    staged = plan(tmp_path, [source], mapping)
    moved = staged[tmp_path / "src/app/new.py"]
    assert "from math import sqrt" in moved
    assert "cos" not in moved


def test_static_star_import_is_expanded_for_moved_function(tmp_path: Path) -> None:
    provider = _source(
        tmp_path,
        "app.old.provider",
        "__all__ = ['foo']\ndef foo():\n    return 1\n",
    )
    consumer = _source(
        tmp_path,
        "app.old.consumer",
        "from .provider import *\ndef use():\n    return foo()\n",
    )
    mapping = {
        **_mapping(provider, "app.new.provider", tmp_path),
        **_mapping(consumer, "app.new.consumer", tmp_path),
    }
    staged = plan(tmp_path, [provider, consumer], mapping)
    moved = staged[tmp_path / "src/app/new/consumer.py"]
    assert "import *" not in moved
    assert moved.count("from app.new.provider import foo") == 1


def test_colocated_import_removed_only_for_defined_symbol(tmp_path: Path) -> None:
    from scripts.refactor.relocate import _remove_local_imports

    path = tmp_path / "src/app/core/db.py"
    path.parent.mkdir(parents=True)
    source = "from app.core.db import Base\nclass Base:\n    pass\n"
    assert (
        _remove_local_imports(tmp_path, {path: source})[path]
        == "class Base:\n    pass\n"
    )
    with pytest.raises(RelocationError, match="self import has no matching"):
        _remove_local_imports(tmp_path, {path: "from app.core.db import Missing\n"})
