from __future__ import annotations

import inspect

from app.domains.blackjack import repository

PUBLIC_METHODS = tuple(
    name
    for name in repository.__all__
    if callable(getattr(repository, name, None))
    and not name.startswith("_")
    and name != "BlackjackRepository"
)


def test_module_level_blackjack_repository_exports_have_explicit_parameters() -> None:
    assert PUBLIC_METHODS
    for name in PUBLIC_METHODS:
        signature = inspect.signature(getattr(repository, name))
        assert all(
            parameter.name != "self" for parameter in signature.parameters.values()
        )
        assert getattr(repository, name).__module__ == repository.__name__


def test_legacy_repository_facade_subclass_is_removed() -> None:
    assert "BlackjackRepository" not in repository.__all__
    assert not hasattr(repository, "BlackjackRepository")
