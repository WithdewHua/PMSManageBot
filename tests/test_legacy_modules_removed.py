"""The pre-promotion application namespaces must not reappear."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize("module_name", ["app.databases", "app.webapp", "app.models"])
def test_legacy_application_modules_are_removed(module_name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)
