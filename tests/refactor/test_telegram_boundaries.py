"""Telegram integration split and profile orchestration boundaries."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from app.domains.profile import service as profile_service
from app.integrations.telegram import init_data
from app.integrations.telegram import profiles as telegram_profiles

ROOT = Path(__file__).parents[2]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_init_data_validation_is_explicit_and_has_no_settings_dependency() -> None:
    imports = _imports(ROOT / "src/app/integrations/telegram/init_data.py")
    assert "app.core.config" not in imports
    result = init_data.verify_telegram_data(
        {"auth_date": "1000", "user": "{}", "hash": "invalid"},
        "token",
        86400,
        now=1000,
    )
    assert result.reason == "invalid_signature"


def test_profile_cache_is_local_and_does_not_import_network_clients() -> None:
    imports = _imports(ROOT / "src/app/integrations/telegram/profile_cache.py")
    assert not imports.intersection({"aiohttp", "requests", "telegram"})


def test_profile_service_only_prepares_ids_and_delegates_refresh(monkeypatch) -> None:
    captured = {}

    def ids():
        return [7, 8]

    async def refresh(values, *, token):
        captured["ids"] = list(values)
        captured["token"] = token

    monkeypatch.setattr(profile_service.identity_service, "list_statistics_tg_ids", ids)
    monkeypatch.setattr(telegram_profiles, "refresh_tg_user_info", refresh)

    asyncio.run(profile_service.refresh_tg_user_info(token="test-token"))
    assert captured == {"ids": [7, 8], "token": "test-token"}


def test_live_sources_no_longer_import_deleted_core_telegram_module() -> None:
    violations = []
    for root in (ROOT / "src", ROOT / "tests", ROOT / "scripts"):
        for path in root.rglob("*.py"):
            modules = _imports(path)
            if "app.core.telegram" in modules:
                violations.append(path.relative_to(ROOT).as_posix())
    assert violations == []


def test_telegram_modules_are_split_by_role() -> None:
    profiles_imports = _imports(ROOT / "src/app/integrations/telegram/profiles.py")
    cache_imports = _imports(ROOT / "src/app/integrations/telegram/profile_cache.py")
    messaging_imports = _imports(ROOT / "src/app/integrations/telegram/messaging.py")
    assert "app.integrations.telegram.profile_cache" in profiles_imports
    assert "app.integrations.telegram.client" in profiles_imports
    assert "filelock" not in messaging_imports
    assert "aiohttp" in messaging_imports
    assert "aiohttp" not in cache_imports
