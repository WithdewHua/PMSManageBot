"""Freeze the four activity domains' behavior surfaces.

``promote-activity-domains`` promotes luckywheel / treasure / prediction /
auction. This test pins the fixture that the promotion must not change: routes
and OpenAPI paths, scheduler jobs, named task ids, owned tables, and the
repository surface (class members plus module-level functions).
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from scripts.refactor.activity_snapshot import build_activity_snapshot

FIXTURE = Path(__file__).parent / "fixtures/activity_surface.json"
MAPPING = Path(__file__).parents[2] / "scripts/refactor/mapping.toml"
DOMAINS = ("luckywheel", "treasure", "prediction", "auction")

#: 四个 mixin 的成员在提升后允许落到哪些模块。repository 不再拆分时
#: planned_target 与 target 相同；prediction 按子主题拆分；纯计算进 rules。
ALLOWED_DESTINATIONS = {
    "app.domains.luckywheel.repository",
    "app.domains.luckywheel.config",
    "app.domains.treasure.repository",
    "app.domains.auction.repository",
    "app.domains.prediction.repository.markets",
    "app.domains.prediction.repository.bets",
    "app.domains.prediction.repository.settlement",
    "app.domains.prediction.repository.analytics",
    "app.domains.prediction.rules",
}


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _dump(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def test_activity_surface_matches_frozen_fixture() -> None:
    first = build_activity_snapshot()
    second = build_activity_snapshot()
    assert _dump(first) == _dump(second), "快照必须可重复生成"
    assert first == _fixture()


def test_activity_surface_covers_every_domain() -> None:
    snapshot = _fixture()
    assert set(snapshot["domains"]) == set(DOMAINS)
    for domain in DOMAINS:
        section = snapshot["domains"][domain]
        assert section["routes"], domain
        assert section["openapi_paths"], domain
        assert section["repository_members"], domain
        assert section["metadata_tables"], domain
        assert section["references"], domain


def test_named_tasks_are_frozen_until_the_auction_promotion() -> None:
    snapshot = _fixture()
    ids = [item["task_id"] for item in snapshot["named_tasks"]]
    # 竞拍的具名任务由本变更新增（design D5），其余保持不变
    assert ids == [
        "auction.finish",
        "blackjack.hand_timeout",
        "treasure.open_next_issue",
        "treasure.reopen_overdue",
    ]
    assert snapshot["legacy_task_refs"]


def test_scheduler_jobs_stay_within_the_four_domains() -> None:
    snapshot = _fixture()
    jobs = {
        domain: [job["kwargs"].get("id") for job in section["scheduler_jobs"]]
        for domain, section in snapshot["domains"].items()
    }
    assert jobs["auction"] == ["finish_expired_auctions_fallback"]
    assert jobs["prediction"] == ["check_prediction_markets_closing_soon_job"]
    assert jobs["luckywheel"] == []
    assert jobs["treasure"] == ["treasure_reopen_overdue"]


@pytest.mark.parametrize("domain", DOMAINS)
def test_repository_surface_is_populated(domain: str) -> None:
    section = _fixture()["domains"][domain]
    assert section["repository_members"] or section["repository_functions"]


def test_every_repository_member_has_a_reviewed_destination() -> None:
    """每个 mixin 成员都要在 mapping.toml 里写明目标位置。"""
    snapshot = _fixture()
    mapping = tomllib.loads(MAPPING.read_text(encoding="utf-8"))
    planned = {
        item["id"].split("DatabaseORM.", 1)[1]: item["planned_target"]
        for item in mapping["items"]
        if item["id"].startswith("app.databases.db:DatabaseORM.")
        and "planned_target" in item
    }

    members = {
        name
        for domain in DOMAINS
        for name in snapshot["domains"][domain]["repository_members"]
    }
    assert sorted(name for name in members if name not in planned) == []
    assert {planned[name] for name in members} <= ALLOWED_DESTINATIONS
