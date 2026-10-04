"""Isolated quota ledger, reroll and bootstrap regressions (no external effects)."""

from __future__ import annotations

import copy
from datetime import datetime

import pytest
from sqlalchemy import func, null, select

from app.core import kv
from app.core.config import settings
from app.core.db import get_session
from app.domains.identity.models import Statistics
from app.domains.invitation.models import Invitation
from app.domains.luckywheel import config, exceptions, repository, rules, service
from app.domains.luckywheel.models import (
    LuckywheelFreeSpin,
    WheelInviteAudit,
    WheelInviteQuotaWeek,
    WheelStats,
)
from app.domains.luckywheel.repository import quotas
from app.domains.luckywheel.schemas import LuckyWheelConfig, LuckyWheelItem
from tests.conftest import add_user, next_id

WHEEL = LuckyWheelConfig(
    items=[
        LuckyWheelItem(name="邀请码 1 枚", probability=0.08),
        LuckyWheelItem(name="积分 +10", probability=99.92),
    ],
    cost_credits=10,
    min_credits_required=30,
)


@pytest.fixture
def deterministic(monkeypatch):
    def pick(items, **kwargs):
        return next(
            (item for item in items if rules.prize_effects(item).invite_codes), items[0]
        )

    monkeypatch.setattr(rules, "pick_prize", pick)


def _bootstrap() -> dict:
    report = quotas.initialization_report()
    quotas.initialize(report, history_verified=True, writers_stopped=True)
    return report


def _history(users: int, per_user: int, *, start_id: int = 1) -> None:
    now = int(quotas.time.time())
    week = rules.natural_week_start_ms(now * 1000, settings.TZ) // 1000
    timestamp = max(now - 1, week)
    for tg_id in range(start_id, start_id + users):
        add_user(tg_id, credits=1000)
        with get_session() as session:
            for i in range(per_user):
                session.add(
                    WheelStats(
                        id=next_id(),
                        tg_id=tg_id,
                        item_name="邀请码 1 枚",
                        credits_change=0,
                        cost_credits=10,
                        timestamp=timestamp,
                        date="1999-01-01",
                        source="gift_pack_free" if i % 2 else null(),
                    )
                )


def _spin(tg_id: int = 1, *, use_free_spin: bool = False, wheel=WHEEL) -> dict:
    return repository.spin(
        tg_id=tg_id,
        config=wheel,
        winner_name="邀请码 1 枚",
        winner_probability=0.08,
        use_free_spin=use_free_spin,
    )


def _count(model) -> int:
    with get_session() as session:
        return int(session.scalar(select(func.count()).select_from(model)))


def _credits(tg_id: int = 1) -> float:
    with get_session() as session:
        return float(session.get(Statistics, tg_id).credits)


def test_week_boundary_is_beijing_monday():
    monday = datetime(2026, 10, 5, tzinfo=settings.TZ)
    start = int(monday.timestamp() * 1000)
    assert rules.natural_week_start_ms(start, settings.TZ) == start
    assert rules.natural_week_start_ms(start - 1, settings.TZ) == start - quotas.WEEK_MS
    assert rules.natural_week_start_ms(start + quotas.WEEK_MS - 1, settings.TZ) == start


def test_bootstrap_24_global_4_personal_and_reroll(deterministic):
    _history(6, 4)
    report = _bootstrap()
    assert report["issued"] == 24
    assert _count(Invitation) == 0  # Historical import must never create actual codes.
    first = _spin()
    second = _spin()
    assert first["invite_awarded"] is True
    assert second["item_name"] == "积分 +10"
    assert second["invite_awarded"] is False
    stats = quotas.get_stats()
    assert stats["global_used"] == 25
    assert stats["historical_issued"] == 24
    assert {row["source"]: row["issued"] for row in stats["sources"]}[None] == 12
    assert stats["new_issued"] == 1
    assert stats["users"][0] == {"tg_id": 1, "issued": 5}
    assert stats["personal_blocked_count"] == 1


def test_history_over_limits_is_not_clipped_or_revoked(deterministic):
    _history(5, 8)
    _bootstrap()
    assert _spin()["item_name"] == "积分 +10"
    stats = quotas.get_stats()
    assert stats["global_used"] == stats["historical_issued"] == 40
    assert stats["users"][0]["issued"] == 8
    assert stats["both_blocked_count"] == 1
    assert stats["first_exhausted_at_ms"] is None
    assert _count(Invitation) == 0


def test_missing_initialization_fails_before_any_charge():
    add_user(1, credits=1000)
    with pytest.raises(exceptions.LuckywheelError, match="暂不可用"):
        _spin()
    assert _credits() == 1000
    assert _count(WheelStats) == _count(Invitation) == 0


@pytest.mark.parametrize(
    "raw", [None, "broken", '{"global_weekly_limit": "30", "personal_weekly_limit": 5}']
)
def test_missing_or_corrupt_config_never_fails_open(raw):
    add_user(1, credits=1000)
    _bootstrap()
    with get_session() as session:
        if raw is None:
            kv.delete_tx(session, config.CONFIG_TYPE, config.INVITE_QUOTA_CONFIG_KEY)
        else:
            kv.upsert_tx(
                session, config.CONFIG_TYPE, config.INVITE_QUOTA_CONFIG_KEY, raw
            )
    with pytest.raises(exceptions.LuckywheelError, match="暂不可用"):
        _spin()
    assert _credits() == 1000
    assert _count(Invitation) == 0


def test_zero_limit_reselects_without_consuming_privileged_toggle(deterministic):
    add_user(1, credits=1000)
    _bootstrap()
    service.update_invite_quota_config({"global_weekly_limit": 0})
    wheel = WHEEL.model_copy(update={"gen_privileged_code": True})
    config.save_wheel_config(wheel)
    result = _spin(wheel=wheel)
    assert result["item_name"] == "积分 +10"
    assert _credits() == 1000  # One fee of 10 and one reward of 10.
    assert config.get_wheel_config().gen_privileged_code is True
    assert _count(Invitation) == 0
    assert _count(WheelStats) == _count(WheelInviteAudit) == 1
    assert quotas.get_stats()["global_used"] == 0


def test_free_paid_and_ten_share_personal_limit(deterministic):
    add_user(1, credits=1000)
    _bootstrap()
    now = int(quotas.time.time() * 1000)
    repository.grant_free_spins(
        1, 2, source="gift_pack", granted_at_ms=now, expires_at_ms=now + 60000
    )
    assert _spin(use_free_spin=True)["used_free_spin"] is True
    assert _spin(use_free_spin=True)["used_free_spin"] is True
    assert _spin()["invite_awarded"] is True
    batch = repository.spin_ten(
        tg_id=1, config=WHEEL, winners=[("邀请码 1 枚", 0.08)] * 10
    )
    assert len(batch) == 10
    assert sum(row["invite_awarded"] for row in batch) == 2
    assert _count(Invitation) == 5
    assert _credits() == 970
    assert quotas.get_stats()["global_used"] == 5
    assert _count(WheelStats) == 13


def test_global_last_one_is_consumed_once_inside_ten(deterministic):
    add_user(1, credits=1000)
    _bootstrap()
    service.update_invite_quota_config({"global_weekly_limit": 1})
    results = repository.spin_ten(
        tg_id=1, config=WHEEL, winners=[("邀请码 1 枚", 0.08)] * 10
    )
    assert sum(result["invite_awarded"] for result in results) == 1
    assert _count(Invitation) == 1
    stats = quotas.get_stats()
    assert stats["global_used"] == 1
    assert stats["global_blocked_count"] == 9
    assert stats["first_exhausted_at_ms"] is not None


@pytest.mark.parametrize("ten", [False, True])
def test_audit_failure_rolls_back_fee_codes_counts_and_stats(
    monkeypatch, deterministic, ten
):
    add_user(1, credits=1000)
    _bootstrap()
    original = quotas.record_tx
    calls = 0

    def fail(session, **kwargs):
        nonlocal calls
        original(session, **kwargs)
        calls += 1
        if calls == (3 if ten else 1):
            raise RuntimeError("audit failed")

    monkeypatch.setattr(quotas, "record_tx", fail)
    with pytest.raises(RuntimeError, match="audit failed"):
        if ten:
            repository.spin_ten(
                tg_id=1, config=WHEEL, winners=[("邀请码 1 枚", 0.08)] * 10
            )
        else:
            _spin()
    assert _credits() == 1000
    assert _count(Invitation) == _count(WheelStats) == _count(WheelInviteAudit) == 0
    assert quotas.get_stats()["global_used"] == 0


def test_storage_failure_is_not_a_reroll(monkeypatch, deterministic):
    add_user(1, credits=1000)
    _bootstrap()

    def fail(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(quotas, "reserve_tx", fail)
    with pytest.raises(RuntimeError, match="database unavailable"):
        _spin()
    assert _credits() == 1000
    assert _count(Invitation) == _count(WheelStats) == 0


def test_repeat_bootstrap_keeps_new_issuance():
    add_user(1, credits=1000)
    report = _bootstrap()
    _spin()
    result = quotas.initialize(report, history_verified=True, writers_stopped=True)
    assert result["already_initialized"] is True
    assert quotas.get_stats()["global_used"] == 1
    assert _count(WheelInviteAudit) == 1


def test_bootstrap_changed_source_and_tampered_report_refused():
    _history(1, 1)
    report = quotas.initialization_report()
    tampered = copy.deepcopy(report)
    tampered["rows"][0]["tg_id"] = 2
    with pytest.raises(ValueError, match="已变化"):
        quotas.initialize(tampered, history_verified=True, writers_stopped=True)
    _history(1, 1, start_id=2)
    with pytest.raises(ValueError, match="已变化"):
        quotas.initialize(report, history_verified=True, writers_stopped=True)
    assert _count(WheelInviteQuotaWeek) == _count(WheelInviteAudit) == 0


@pytest.mark.parametrize("verified,stopped", [(False, True), (True, False)])
def test_bootstrap_requires_both_operator_confirmations(verified, stopped):
    report = quotas.initialization_report()
    with pytest.raises(ValueError, match="必须确认"):
        quotas.initialize(report, history_verified=verified, writers_stopped=stopped)
    assert _count(WheelInviteQuotaWeek) == 0


def test_limit_updates_preserve_usage_and_zero_semantics(deterministic):
    _history(1, 4)
    _bootstrap()
    service.update_invite_quota_config({"global_weekly_limit": 3})
    assert _spin()["invite_awarded"] is False
    assert quotas.get_stats()["global_used"] == 4
    service.update_invite_quota_config({"global_weekly_limit": 6})
    assert _spin()["invite_awarded"] is True
    service.update_invite_quota_config({"personal_weekly_limit": 0})
    assert _spin()["invite_awarded"] is False
    assert quotas.get_stats()["global_used"] == 5


def test_invalid_fallback_fails_without_consuming_free_spin():
    add_user(1, credits=1000)
    _bootstrap()
    now = int(quotas.time.time() * 1000)
    repository.grant_free_spins(
        1, 1, source="gift_pack", granted_at_ms=now, expires_at_ms=now + 60000
    )
    wheel = WHEEL.model_copy(
        update={"items": [LuckyWheelItem(name="特权邀请码", probability=100)]}
    )
    with pytest.raises(exceptions.LuckywheelError):
        _spin(use_free_spin=True, wheel=wheel)
    with get_session() as session:
        assert session.scalar(select(LuckywheelFreeSpin.used_at_ms)) is None
    assert _credits() == 1000


def test_reassign_sums_history_without_changing_global():
    _history(1, 3)
    _history(1, 2, start_id=2)
    _bootstrap()
    with get_session() as session:
        moved = repository.reassign_tg_id_tx(session, 1, 2)
        assert moved["wheel_invite_audit.tg_id"] == 3
    stats = quotas.get_stats()
    assert stats["global_used"] == 5
    assert stats["users"] == [{"tg_id": 2, "issued": 5}]


def test_ten_uses_one_period_when_clock_crosses_week(monkeypatch, deterministic):
    add_user(1, credits=1000)
    monday = int(datetime(2026, 10, 5, tzinfo=settings.TZ).timestamp() * 1000)
    clock = {"now": monday - 1000}
    monkeypatch.setattr(quotas.time, "time", lambda: clock["now"] / 1000)
    _bootstrap()
    original = quotas.record_tx

    def advance(session, **kwargs):
        original(session, **kwargs)
        clock["now"] = monday + 1000

    monkeypatch.setattr(quotas, "record_tx", advance)
    repository.spin_ten(tg_id=1, config=WHEEL, winners=[("邀请码 1 枚", 0.08)] * 10)
    with get_session() as session:
        weeks = set(session.scalars(select(WheelInviteAudit.week_start_ms)).all())
    assert weeks == {monday - quotas.WEEK_MS}
    assert quotas.get_stats()["global_used"] == 0
    assert _spin()["invite_awarded"] is True  # New request receives the new week.


def test_repeat_bootstrap_detects_untracked_old_writer():
    report = _bootstrap()
    _history(1, 1)
    with pytest.raises(ValueError, match="账本不一致"):
        quotas.initialize(report, history_verified=True, writers_stopped=True)
    assert quotas.get_stats()["global_used"] == 0


def test_year_boundary_and_millisecond_week_key():
    january = int(datetime(2027, 1, 1, tzinfo=settings.TZ).timestamp() * 1000)
    december_monday = int(datetime(2026, 12, 28, tzinfo=settings.TZ).timestamp() * 1000)
    assert rules.natural_week_start_ms(january, settings.TZ) == december_monday
    assert (
        rules.natural_week_start_ms(december_monday + quotas.WEEK_MS, settings.TZ)
        == december_monday + quotas.WEEK_MS
    )


def test_fallback_excludes_all_invites_and_preserves_protection(monkeypatch):
    items = [
        LuckyWheelItem(name="普通邀请码", probability=5),
        LuckyWheelItem(name="特权邀请码奖励", probability=4),
        LuckyWheelItem(name="积分 +1", probability=1),
        LuckyWheelItem(name="积分 -10", probability=90),
        LuckyWheelItem(name="谢谢参与", probability=0),
    ]
    pool = rules.non_invite_items(items)
    assert [item.name for item in pool] == ["积分 +1", "积分 -10"]
    totals = []

    class FixedRandom:
        def uniform(self, low, high):
            totals.append(high)
            return 1.1

    monkeypatch.setattr(rules.secrets, "SystemRandom", FixedRandom)
    options = {"use_time_seed_mixing": False, "use_user_seed_mixing": False}
    assert rules.pick_prize(pool, randomness=options).name == "积分 +1"
    assert totals[-1] == pytest.approx(91.2)
    assert (
        rules.pick_prize(
            pool, randomness={**options, "use_weighted_protection": False}
        ).name
        == "积分 -10"
    )
    assert totals[-1] == 91
    assert pool[0].probability == 1  # No in-place weight mutation.


def test_reroll_does_not_guarantee_positive_credits(deterministic):
    add_user(1, credits=1000)
    _bootstrap()
    service.update_invite_quota_config({"global_weekly_limit": 0})
    wheel = WHEEL.model_copy(
        update={
            "items": [
                LuckyWheelItem(name="邀请码 1 枚", probability=99),
                LuckyWheelItem(name="积分 -10", probability=1),
            ]
        }
    )
    assert _spin(wheel=wheel)["credits_change"] == -10
    assert _credits() == 980
    assert _count(Invitation) == 0


def test_history_custom_names_and_week_filter():
    _history(1, 1)
    now = int(quotas.time.time() * 1000)
    week = rules.natural_week_start_ms(now, settings.TZ)
    with get_session() as session:
        row = session.scalar(select(WheelStats))
        row.item_name = "特权邀请码奖励"
        for timestamp in (week // 1000 - 1, (week + quotas.WEEK_MS) // 1000):
            session.add(
                WheelStats(
                    id=next_id(),
                    tg_id=1,
                    item_name="邀请码 1 枚",
                    cost_credits=10,
                    credits_change=0,
                    timestamp=timestamp,
                    date="2026-01-01",
                    source="paid",
                )
            )
    report = _bootstrap()
    assert report["issued"] == report["scanned_count"] == 1
    with get_session() as session:
        assert session.scalar(select(WheelInviteAudit)).privileged is None


def test_initialization_report_cannot_cross_week(monkeypatch):
    report = quotas.initialization_report()
    later = quotas.time.time() + quotas.WEEK_MS / 1000
    monkeypatch.setattr(quotas.time, "time", lambda: later)
    with pytest.raises(ValueError, match="自然周已变化"):
        quotas.initialize(report, history_verified=True, writers_stopped=True)
    assert _count(WheelInviteQuotaWeek) == 0


def test_ten_reads_one_quota_snapshot(monkeypatch, deterministic):
    add_user(1, credits=1000)
    _bootstrap()
    service.update_invite_quota_config({"global_weekly_limit": 1})
    original = quotas._config_tx
    calls = 0

    def counted(session, **kwargs):
        nonlocal calls
        calls += 1
        return original(session, **kwargs)

    monkeypatch.setattr(quotas, "_config_tx", counted)
    rows = repository.spin_ten(
        tg_id=1, config=WHEEL, winners=[("邀请码 1 枚", 0.08)] * 10
    )
    assert calls == 1
    assert sum(row["invite_awarded"] for row in rows) == 1


def test_new_settlement_reads_committed_value_not_cached_config(deterministic):
    add_user(1, credits=1000)
    _bootstrap()
    config.INVITE_QUOTA_CONFIG.get()  # Prime this process's ordinary configuration cache.
    with get_session() as session:
        kv.upsert_tx(
            session,
            config.CONFIG_TYPE,
            config.INVITE_QUOTA_CONFIG_KEY,
            '{"global_weekly_limit":0,"personal_weekly_limit":5}',
        )
    assert _spin()["invite_awarded"] is False
    assert _count(Invitation) == 0


def test_lost_restrictive_config_is_not_repaired_by_reads_or_startup(deterministic):
    from app import business_config

    add_user(1, credits=1000)
    report = _bootstrap()
    service.update_invite_quota_config(
        {"global_weekly_limit": 0, "personal_weekly_limit": 0}
    )
    with get_session() as session:
        kv.delete_tx(session, config.CONFIG_TYPE, config.INVITE_QUOTA_CONFIG_KEY)
    for read in (service.get_invite_quota_config, service.get_invite_quota_stats):
        with pytest.raises(exceptions.LuckywheelError):
            read()
    assert quotas.initialize(report, history_verified=True, writers_stopped=True)[
        "already_initialized"
    ]
    business_config.seed_all()
    with get_session() as session:
        assert (
            kv.get_tx(session, config.CONFIG_TYPE, config.INVITE_QUOTA_CONFIG_KEY)
            is None
        )
    with pytest.raises(exceptions.LuckywheelError):
        _spin()
    assert _credits() == 1000
    assert _count(Invitation) == _count(WheelInviteAudit) == 0


def test_quota_defaults_are_seeded_only_by_owner_before_initialization():
    from app import business_config

    business_config.seed_all()
    with get_session() as session:
        assert (
            kv.get_tx(session, config.CONFIG_TYPE, config.INVITE_QUOTA_CONFIG_KEY)
            is None
        )
    assert service.get_invite_quota_config() == {
        "global_weekly_limit": 30,
        "personal_weekly_limit": 5,
    }
    assert service.get_invite_quota_stats()["initialized"] is False
