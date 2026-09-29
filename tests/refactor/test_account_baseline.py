"""Freeze the accounts / identity / invitation promotion surface."""

from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path

from scripts.refactor.account_snapshot import build_account_snapshot

FIXTURE = Path(__file__).parent / "fixtures/account_surface.json"
ROOT = Path(__file__).parents[2]


def _dump(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def test_account_surface_is_repeatable_and_frozen() -> None:
    first = build_account_snapshot()
    second = build_account_snapshot()
    assert _dump(first) == _dump(second)
    assert first == json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_account_surface_contains_all_entry_points() -> None:
    snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
    paths = {route["path"] for route in snapshot["routes"]}
    assert "/api/user/bind/plex" in paths
    assert "/api/user/bind/emby" in paths
    assert "/api/invite/redeem/plex" in paths
    assert "/api/invite/redeem/emby" in paths
    assert "/api/invite/redeem-for-credits" in paths
    assert "/api/admin/invite-codes/generate" in paths
    assert {item["task_id"] for item in snapshot["named_tasks"]} == {
        "invitation.resolve_plex_id"
    }


def test_account_mapping_covers_identity_invitation_and_accounts_moves() -> None:
    mapping = {
        item["id"]: item
        for item in tomllib.loads(
            (ROOT / "scripts/refactor/mapping.toml").read_text(encoding="utf-8")
        )["items"]
    }
    identity_methods = (
        "add_plex_user",
        "add_emby_user",
        "get_plex_info_by_tg_id",
        "get_plex_info_by_plex_email",
        "get_emby_info_by_tg_id",
        "get_emby_info_by_emby_username",
        "get_stats_by_tg_id",
        "get_overseerr_info_by_tg_id",
    )
    for name in identity_methods:
        assert mapping[f"app.databases.db:DatabaseORM.{name}"]["target"] == (
            "app.domains.identity.repository"
        )
    assert mapping["app.databases.db_func:update_plex_info"]["target"] == (
        "app.domains.accounts.service"
    )
    assert mapping["app.databases.db_func:add_redeem_code"]["target"] == (
        "app.domains.invitation.service"
    )


def test_account_entry_points_do_not_import_legacy_facade_or_models() -> None:
    roots = (
        ROOT / "src/app/domains/accounts",
        ROOT / "src/app/domains/invitation",
    )
    layers = {"router.py", "admin_router.py", "bot.py", "jobs.py", "service.py"}
    for path in sorted(
        path for root in roots for path in root.rglob("*.py") if path.name in layers
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    not alias.name.startswith(("app.databases", "sqlalchemy"))
                    for alias in node.names
                ), path
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(
                    ("app.databases", "app.domains.identity.models", "sqlalchemy")
                ), path
