"""Targeted B3 dependency changes preserve the B2 behavior and remove new cycles."""

from __future__ import annotations

import ast
from pathlib import Path

from scripts.refactor.smoke_b3_decycles import main as compare_traffic_behavior

ROOT = Path(__file__).resolve().parents[2] / "src/app/domains"


def test_b3_traffic_lookup_matches_b2_database_sessions_and_errors() -> None:
    assert compare_traffic_behavior() == 0


def test_b3_created_cycle_imports_are_not_baselined() -> None:
    import tomllib

    with (ROOT.parents[2] / "pyproject.toml").open("rb") as stream:
        contracts = tomllib.load(stream)["tool"]["importlinter"]["contracts"]
    acyclic = next(c for c in contracts if c["name"] == "Acyclic domain siblings")
    for item in acyclic.get("ignore_imports", []):
        assert "app.domains.premium.admin_router -> app.domains.lines.service" != item
        assert "app.domains.profile.router -> app.domains.accounts.jobs" != item
        assert (
            "app.domains.traffic.repository -> app.domains.custom_lines.models" != item
        )
        assert "app.domains.traffic.repository -> app.domains.lines.rules" != item


def test_custom_line_traffic_uses_independent_identity_sessions() -> None:
    tree = ast.parse((ROOT / "traffic/service.py").read_text())
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_get_line_monthly_traffic"
    )
    calls = [
        node.func.attr
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert "get_plex_info_by_tg_id" in calls
    assert "get_emby_info_by_tg_id" in calls
    assert "execute" in calls
