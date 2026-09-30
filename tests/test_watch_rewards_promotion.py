"""Frozen post-fix watch settlement amounts and byte-exact notifications."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import get_session
from app.domains.identity.models import EmbyUser
from app.domains.watch_rewards import notifications, service
from tests import test_watch_settlement_consistency as legacy


@pytest.fixture
def external_stubs(monkeypatch):
    legacy._install(monkeypatch, durations={101: 24.0})
    monkeypatch.setattr(
        service.premium_service,
        "get_premium_config",
        lambda: SimpleNamespace(credits_cost_per_10gb=5),
    )
    monkeypatch.setattr(
        service.traffic_service,
        "get_traffic_config",
        lambda: SimpleNamespace(user_traffic_limit=10, premium_user_traffic_limit=20),
    )
    monkeypatch.setattr(
        service.traffic_service, "get_user_daily_traffic", lambda **kwargs: 0
    )
    monkeypatch.setattr(
        service,
        "_settle_premium_traffic_usage",
        lambda **kwargs: {
            **legacy._no_traffic_settlement(),
            "traffic_cost_credits": 3.0,
            "next_debt_bytes": 42,
            "next_debt_updated_date": "2026-09-27",
            "chargeable_bytes": 1024,
        },
    )
    monkeypatch.setattr(service, "_get_settled_through_date", lambda: "2026-09-26")
    monkeypatch.setattr(service, "_set_settled_through_date", lambda value: None)
    monkeypatch.setattr(
        service.invitation_service, "get_inviter_tg_id_by_plex_id", lambda value: 99
    )
    monkeypatch.setattr(
        service.invitation_service, "get_inviter_tg_id_by_emby_id", lambda value: 99
    )
    monkeypatch.setattr(
        service.badges_service, "active_bonus_percentage", lambda tg: 0.25
    )
    monkeypatch.setattr(
        service,
        "Emby",
        lambda: SimpleNamespace(get_user_total_play_time=lambda: {"101": 24 * 3600}),
    )


def test_plex_freeze_cap_penalty_badge_inviter_debt(session_env, external_stubs):
    legacy._seed_plex_user(101, tg_id=11, credits=0, watched=1)
    legacy._seed_stats(11, credits=10)
    legacy._seed_stats(99, credits=100)
    tasks, deductions = service.update_plex_credits()
    assert legacy._tg_credits(11) == 8.0  # award .8 + badge .2 - fee 3
    assert legacy._tg_credits(99) == 100.08
    row = legacy._plex_row(101)
    assert float(row.watched_time) == 25
    assert row.premium_traffic_debt_bytes == 42
    assert row.premium_traffic_debt_updated_date == "2026-09-27"
    assert tasks[0] == (
        11,
        "Plex 观看积分更新通知\n====================\n\n新增观看时长: 24.00 小时\n基础观看积分: 8.00\n观看惩罚: -7.20\nPremium 流量消耗积分: 3.00\n积分变化: -2.00\n\n当前总积分: 8.00\n当前总观看时长: 25.00 小时\n====================",
    )
    day = (datetime.now(settings.TZ).date()).toordinal() - 1
    date = datetime.fromordinal(day).strftime("%Y-%m-%d")
    assert tasks[1] == (
        99,
        f"Plex 邀请奖励通知\n====================\n\n{date} 共 1 位被邀请用户有新增观看记录:\n  · plex101: 基础积分 0.8 → 奖励 +0.08\n\n本次邀请奖励积分: +0.08\n\n--------------------\n\n当前总积分: 100.08\n\n====================",
    )
    assert deductions == [
        {
            "service": "Plex",
            "username": "plex101",
            "tg_id": 11,
            "deducted_credits": 3.0,
            "chargeable_bytes": 1024,
        }
    ]


def test_emby_freeze_increment_penalty_and_notification(session_env, external_stubs):
    with get_session() as session:
        session.add(
            EmbyUser(
                emby_id="101",
                emby_username="alice",
                tg_id=11,
                emby_credits=0,
                emby_watched_time=1,
            )
        )
    legacy._seed_stats(11, credits=10)
    legacy._seed_stats(99, credits=100)
    tasks, deductions = service.update_emby_credits()
    assert legacy._tg_credits(11) == 8.62
    assert legacy._tg_credits(99) == 100.13
    assert tasks[0] == (
        11,
        "Emby 观看积分更新通知\n====================\n\n新增观看时长: 23.00 小时\n基础观看积分: 8.00\n观看惩罚: -6.70\nPremium 流量消耗积分: 3.00\n积分变化: -1.38\n\n当前总积分: 8.62\n当前总观看时长: 24.00 小时\n====================",
    )
    assert "基础积分 1.3 → 奖励 +0.13" in tasks[1][1]
    with get_session() as session:
        row = session.execute(select(EmbyUser)).scalar_one()
        assert float(row.emby_watched_time) == 24
        assert row.premium_traffic_debt_bytes == 42
    assert deductions[0]["service"] == "Emby"


def test_admin_notification_freeze(monkeypatch):
    monkeypatch.setattr(
        notifications, "get_user_name_from_tg_id", lambda value: "Alice"
    )
    date = (datetime.now(settings.TZ).date()).toordinal() - 1
    date = datetime.fromordinal(date).strftime("%Y-%m-%d")
    assert notifications._format_premium_traffic_deduction_summary(
        [
            {
                "service": "Plex",
                "username": "alice",
                "tg_id": 11,
                "deducted_credits": 3,
                "chargeable_bytes": 1024,
            }
        ]
    ) == (
        f"💳 Premium 流量扣分汇总\n⏰ 结算日期: {date}\n"
        + "─" * 40
        + "\n\n🎬 Plex 扣分用户:\n  • alice | TG: Alice | 扣除积分: 3.00 | 扣费流量: 1.00 KB\n\n📋 总计:\n扣分用户: 1 人\n扣除积分: 3.00\n扣费流量: 1.00 KB"
    )


def test_penalty_boundary_and_nonnegative_award():
    assert service._watch_daily_award(8, 9.6, 0) == (8, 0, 0)
    assert service._watch_daily_award(2, 2, 40 * 1024**3) == (1.2, 0, 0.8)
    assert service._watch_daily_award(-1, -1, 0) == (0, 0, 0)


@pytest.mark.parametrize(
    "test_name",
    [
        "test_rerun_same_day_does_not_double_pay",
        "test_premium_traffic_overdraft_continues",
        "test_single_user_failure_isolates",
        "test_failed_user_keeps_ghost_compensation",
        "test_inviter_notification_shows_actual_balance",
        "test_deduction_summary_lists_committed_only",
        "test_normal_settlement_pays_credits",
    ],
)
def test_post_fix_consistency_at_promoted_boundary(session_env, monkeypatch, test_name):
    """Reuse post-fix freezes with their service-boundary traffic stub."""
    getattr(legacy, test_name)(session_env, monkeypatch)


def test_missing_statistics_plex_is_created(session_env, external_stubs):
    legacy._seed_plex_user(101, tg_id=11, credits=90, watched=0)
    legacy._seed_stats(99, credits=100)
    service.update_plex_credits()
    assert legacy._tg_credits(11) == -2
    # Plex retains its historical media balance; only Emby missing-stat binding migrates it.
    assert legacy._plex_credits(101) == 90


def test_missing_statistics_emby_transfers_balance_once(session_env, external_stubs):
    with get_session() as session:
        session.add(
            EmbyUser(
                emby_id="101",
                emby_username="alice",
                tg_id=11,
                emby_credits=10,
                emby_watched_time=1,
            )
        )
    service.update_emby_credits()
    assert legacy._tg_credits(11) == 8.62
    with get_session() as session:
        assert float(session.execute(select(EmbyUser)).scalar_one().emby_credits) == 0
    service.update_emby_credits()
    assert legacy._tg_credits(11) == 8.62


def test_settlement_failure_rolls_back_every_write(
    session_env, external_stubs, monkeypatch
):
    from app.domains.watch_rewards import repository
    from app.domains.watch_rewards.models import GhostSessionLog, WatchRewardSettlement

    legacy._seed_plex_user(101, tg_id=11, credits=0, watched=1)
    legacy._seed_stats(11, credits=10)
    legacy._seed_stats(99, credits=100)
    legacy._seed_ghost(101, 1)
    invalidations = []
    monkeypatch.setattr(
        repository.credits_repository, "invalidate_user_credits", invalidations.append
    )

    def fail(*args, **kwargs):
        raise RuntimeError("injected debt write failure")

    monkeypatch.setattr(repository.premium_repository, "update_traffic_debt_tx", fail)
    tasks, deductions = service.update_plex_credits()
    assert legacy._tg_credits(11) == 10
    assert legacy._tg_credits(99) == 100
    assert float(legacy._plex_row(101).watched_time) == 1
    with get_session() as session:
        assert session.execute(select(WatchRewardSettlement)).first() is None
        assert session.execute(select(GhostSessionLog)).scalar_one().compensated == 0
    assert invalidations == []
    assert deductions == []
    assert tasks == [
        (
            settings.TG_ADMIN_CHAT_ID[0],
            "Plex 观看结算部分用户失败（这些用户未提交，可在下次重试）:\n- Plex plex101 (101): injected debt write failure",
        )
    ]


def test_ghost_hours_capped_once_and_watermark_advances(
    session_env, external_stubs, monkeypatch
):
    legacy._seed_plex_user(101, tg_id=11)
    legacy._seed_stats(11)
    legacy._seed_ghost(101, 3)
    advances = []
    monkeypatch.setattr(service, "_set_settled_through_date", advances.append)
    tasks, _ = service.update_plex_credits()
    assert float(legacy._plex_row(101).watched_time) == 24
    assert "新增观看时长: 24.00 小时" in tasks[0][1]
    assert len(advances) == 1
    service.update_plex_credits()
    assert float(legacy._plex_row(101).watched_time) == 24


def test_ghost_summary_byte_freeze():
    assert (
        notifications._format_ghost_session_summary(
            {
                "scanned": 4,
                "deleted": 1,
                "retried": 1,
                "ghosts": [
                    {
                        "friendly_name": "Alice",
                        "title": "Movie",
                        "play_date": "2026-09-27",
                        "raw_seconds": 36000,
                        "compensated_seconds": 3600,
                        "media_seconds": None,
                        "percent_complete": 50,
                    }
                ],
                "undetermined": [
                    {"friendly_name": "Bob", "title": "Show", "raw_seconds": 7200}
                ],
                "failed": [7],
            }
        )
        == "Tautulli 幽灵会话清理报告\n====================\n\n扫描记录: 4 条\n清理删除: 1 条\n补删遗留: 1 条\n\n--- 已删除并补偿时长 ---\n· Alice《Movie》\n  2026-09-27 原始 10.00h → 补偿 1.00h (媒体 0.00h, 进度 50%)\n\n--- 无法判定，需人工确认 ---\n· Bob《Show》 2.00h (媒体元数据缺失)\n\n--- 处理失败 1 条 ---\nrow_ids: [7]\n\n===================="
    )


def test_jobs_worker_order_and_async_delivery(monkeypatch):
    import asyncio
    import threading

    from app.domains.watch_rewards import jobs

    main_thread = threading.get_ident()
    calls = []

    def clean():
        calls.append(("clean", threading.get_ident()))
        return {"ghosts": [], "undetermined": [], "failed": []}

    def plex():
        calls.append(("plex", threading.get_ident()))
        return [(11, "plex")], []

    def emby():
        calls.append(("emby", threading.get_ident()))
        return [(12, "emby")], []

    async def send(**kwargs):
        calls.append((kwargs["text"], threading.get_ident()))
        assert kwargs["disable_notification"] is True

    async def sleep(seconds):
        assert seconds == 1

    monkeypatch.setattr(jobs.service, "clean_tautulli_ghost_sessions", clean)
    monkeypatch.setattr(jobs.service, "update_plex_credits", plex)
    monkeypatch.setattr(jobs.service, "update_emby_credits", emby)
    monkeypatch.setattr(jobs, "send_message_by_url", send)
    monkeypatch.setattr(jobs.asyncio, "sleep", sleep)
    asyncio.run(jobs.update_credits())
    assert [name for name, _ in calls] == ["clean", "plex", "emby", "plex", "emby"]
    assert all(thread != main_thread for _, thread in calls[:3])
    assert all(thread == main_thread for _, thread in calls[3:])
