"""Focused fixtures for the pure reference rewriter."""

from __future__ import annotations

import pytest

from scripts.refactor.rewrite_refs import (
    RewriteError,
    rewrite_database_orm_refs,
    rewrite_file,
    rewrite_moved_file,
)


def test_unchanged_source_is_returned_byte_for_byte() -> None:
    source = 'message = "app.old.Foo"\nprint(message)\n'
    assert rewrite_file(source, "app.consumer", {"app.other": "app.new"}) == source


def test_top_level_and_local_imports_keep_aliases() -> None:
    source = """from app.old import Foo, Bar as Renamed
import app.old as old, app.other as other

def load():
    from app.old import Baz as Local
    import app.old.sub as child
"""
    assert (
        rewrite_file(source, "app.consumer", {"app.old": "app.new"})
        == """from app.new import Foo, Bar as Renamed
import app.new as old
import app.other as other

def load():
    from app.new import Baz as Local
    import app.new.sub as child
"""
    )


def test_multiple_from_names_split_by_destination() -> None:
    source = "from app.old import Foo, Bar as Renamed, Baz\n"
    destinations = {
        "app.old.Foo": "app.domains.first",
        "app.old.Bar": "app.domains.second",
    }
    assert rewrite_file(source, "app.consumer", destinations) == (
        "from app.domains.first import Foo\n"
        "from app.domains.second import Bar as Renamed\n"
        "from app.old import Baz\n"
    )


def test_relative_imports_are_rendered_relative_to_the_source_module() -> None:
    source = "from .old import Foo\nfrom ..legacy import Bar\n"
    destinations = {
        "app.pkg.old": "app.pkg.new",
        "app.legacy": "app.replacement",
    }
    assert rewrite_file(source, "app.pkg.consumer", destinations) == (
        "from .new import Foo\nfrom ..replacement import Bar\n"
    )


def test_static_star_imports_expand_and_preserve_public_names() -> None:
    source = "from app.old import *\n"
    destinations = {
        "app.old": "app.new",
        "app.old.Bar": "app.other",
    }
    assert rewrite_file(
        source,
        "app.consumer",
        destinations,
        exports={"app.old": ["Foo", "Bar", "public_value"]},
    ) == (
        "from app.new import Foo\n"
        "from app.other import Bar\n"
        "from app.new import public_value\n"
    )


def test_star_import_without_static_exports_fails_closed() -> None:
    with pytest.raises(RewriteError, match="static exports"):
        rewrite_file(
            "from app.old import *\n",
            "app.consumer",
            {"app.old": "app.new"},
        )


def test_dynamic_export_metadata_is_rejected() -> None:
    with pytest.raises(RewriteError, match="static sequence"):
        rewrite_file(
            "from app.old import *\n",
            "app.consumer",
            {"app.old": "app.new"},
            exports={"app.old": "DYNAMIC"},  # type: ignore[arg-type]
        )


def test_recognized_string_paths_rewrite_but_prose_does_not() -> None:
    source = """
monkeypatch.setattr("app.old.Foo", replacement)
with patch("app.old.Bar"):
    importlib.import_module("app.old")
uvicorn.run("app.old:app")
scheduler.add_job("app.old.job")
scheduler.add_job(func="app.old:other")
ordinary = "app.old.Foo"
print("app.old.Bar")
"""
    rewritten = rewrite_file(
        source,
        "app.consumer",
        {"app.old": "app.new"},
    )
    assert (
        rewritten
        == """
monkeypatch.setattr("app.new.Foo", replacement)
with patch("app.new.Bar"):
    importlib.import_module("app.new")
uvicorn.run("app.new:app")
scheduler.add_job("app.new.job")
scheduler.add_job(func="app.new:other")
ordinary = "app.old.Foo"
print("app.old.Bar")
"""
    )


def test_colon_callable_and_module_symbol_destinations() -> None:
    source = 'scheduler.add_job("app.old:run")\npatch("app.old.Foo")\n'
    destinations = {
        "app.old.run": "app.jobs",
        "app.old.Foo": "app.domain",
    }
    assert rewrite_file(source, "app.consumer", destinations) == (
        'scheduler.add_job("app.jobs:run")\npatch("app.domain.Foo")\n'
    )


def test_moved_file_resolves_relative_imports_before_emitting_absolute_targets() -> (
    None
):
    source = """from .helpers import helper
from ..shared import shared
ordinary = ".helpers"
"""
    assert (
        rewrite_moved_file(
            source,
            source_module="app.old.service",
            target_module="app.new.service",
            destinations={},
        )
        == """from app.old.helpers import helper
from app.shared import shared
ordinary = ".helpers"
"""
    )


def test_moved_file_prefers_explicit_destination_for_relative_imports() -> None:
    source = "from .helpers import helper\n"
    assert (
        rewrite_moved_file(
            source,
            source_module="app.old.service",
            target_module="app.new.service",
            destinations={"app.old.helpers": "app.shared.helpers"},
        )
        == "from app.shared.helpers import helper\n"
    )


def test_database_orm_refs_require_same_reviewed_mixin() -> None:
    source = """class CreditMixin:
    class_value = DatabaseORM.grant()

    def grant(self):
        return DatabaseORM.grant()

    def unrelated(self):
        return DatabaseORM.other()

class OtherMixin:
    def grant(self):
        return DatabaseORM.grant()

value = DatabaseORM.grant()
"""
    assert (
        rewrite_database_orm_refs(
            source,
            {"grant": "CreditMixin"},
        )
        == """class CreditMixin:
    class_value = DatabaseORM.grant()

    def grant(self):
        return CreditMixin.grant()

    def unrelated(self):
        return DatabaseORM.other()

class OtherMixin:
    def grant(self):
        return DatabaseORM.grant()

value = DatabaseORM.grant()
"""
    )


def test_database_orm_owner_mismatch_is_rejected() -> None:
    with pytest.raises(RewriteError, match="owner mismatch"):
        rewrite_database_orm_refs(
            "class CreditMixin:\n    pass\n",
            {"OtherMixin.grant": "CreditMixin"},
        )


def test_colon_callable_symbol_mapping_overrides_module_mapping() -> None:
    assert (
        rewrite_file(
            'scheduler.add_job("app.old:run")\n',
            "app.consumer",
            {"app.old": "app.new", "app.old.run": "app.jobs"},
        )
        == 'scheduler.add_job("app.jobs:run")\n'
    )


def test_package_init_relative_import_uses_package_context() -> None:
    assert (
        rewrite_moved_file(
            "from .client import Client\n",
            source_module="app.old.__init__",
            target_module="app.new.__init__",
            destinations={"app.old.client": "app.new.client"},
        )
        == "from app.new.client import Client\n"
    )


def test_callable_class_member_path_preserves_class_on_move() -> None:
    assert (
        rewrite_file(
            'with patch("app.old.Widget.run"):\n    pass\n',
            "app.consumer",
            {"app.old.Widget": "app.new"},
            symbol_paths={"app.old.Widget"},
        )
        == 'with patch("app.new.Widget.run"):\n    pass\n'
    )


def test_bare_dotted_import_updates_attribute_use() -> None:
    source = "import app.old\nvalue = app.old.run()\n"
    assert rewrite_file(source, "app.consumer", {"app.old": "app.new"}) == (
        "import app.new\nvalue = app.new.run()\n"
    )


def test_bare_import_shadowing_fails_closed() -> None:
    with pytest.raises(RewriteError, match="shadowed"):
        rewrite_file(
            "import app.old\ndef use(app):\n    return app.old.run()\n",
            "app.consumer",
            {"app.old": "app.new"},
        )


def test_package_submodule_import_relocates_to_module_not_symbol() -> None:
    source = "from app import blackjack_engine as engine\n"
    assert (
        rewrite_file(
            source,
            "app.consumer",
            {"app.blackjack_engine": "app.domains.blackjack.rules"},
            symbol_paths=set(),
        )
        == "from app.domains.blackjack import rules as engine\n"
    )
