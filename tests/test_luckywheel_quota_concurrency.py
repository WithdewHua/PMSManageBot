"""Real independent connections; PostgreSQL is opt-in and container-guarded."""

from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.core import db
from app.domains.identity.models import Statistics
from app.domains.invitation.models import Invitation
from app.domains.luckywheel import config, repository, rules, service
from app.domains.luckywheel.models import WheelInviteAudit, WheelInviteQuotaWeek
from app.domains.luckywheel.repository import quotas
from app.domains.luckywheel.schemas import LuckyWheelConfig, LuckyWheelItem
from app.model_registry import metadata


@pytest.fixture(params=["sqlite", "sqlite-fk", "postgresql"])
def concurrent_db(request, monkeypatch, tmp_path, session_env):
    mode = request.param
    if mode == "postgresql":
        target = os.environ.get("PMS_QUOTA_TEST_DATABASE_URL")
        if not target:
            pytest.skip(
                "PMS_QUOTA_TEST_DATABASE_URL not set; disposable PostgreSQL only"
            )
        url = make_url(target)
        assert url.host == "127.0.0.1" and url.database == "pms_test_quota_runtime"
        port = subprocess.check_output(
            ["docker", "port", "pms-luckywheel-quota-verify", "5432"],
            text=True,
        ).strip()
        assert port == f"127.0.0.1:{url.port}", (
            "Target must be the dedicated disposable container"
        )
        engine = create_engine(url, pool_size=10, max_overflow=0)
        # This exact guarded test database is exclusively owned by this fixture.
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    else:
        engine = create_engine(
            f"sqlite:///{tmp_path / 'concurrency.db'}", connect_args={"timeout": 5}
        )
        if mode == "sqlite-fk":

            @event.listens_for(engine, "connect")
            def enable_fk(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")

    metadata.create_all(engine)
    previous_engine, previous_factory = db.engine, db.SessionLocal
    db.engine = engine
    db.SessionLocal = sessionmaker(bind=engine, autoflush=False)
    try:
        monkeypatch.setattr(rules, "pick_prize", lambda items, **kwargs: items[0])
        config.INVITE_QUOTA_CONFIG.invalidate()
        config.RANDOMNESS_CONFIG.invalidate()
        config.WHEEL_CONFIG.invalidate()
        with db.get_session() as session:
            session.add_all(
                Statistics(tg_id=i, credits=1000, donation=0) for i in range(1, 9)
            )
        report = quotas.initialization_report()
        quotas.initialize(report, history_verified=True, writers_stopped=True)
        config.RANDOMNESS_CONFIG.seed()
        yield mode
    finally:
        db.engine, db.SessionLocal = previous_engine, previous_factory
        engine.dispose()


def _race(mode: str, user_ids: list[int]) -> list[dict]:
    barrier = Barrier(len(user_ids))
    wheel = LuckyWheelConfig(
        items=[
            LuckyWheelItem(name="积分 +10", probability=99.92),
            LuckyWheelItem(name="邀请码 1 枚", probability=0.08),
        ],
        cost_credits=10,
        min_credits_required=30,
    )

    def worker(tg_id):
        barrier.wait(timeout=10)
        try:
            return repository.spin(
                tg_id=tg_id,
                config=wheel,
                winner_name="邀请码 1 枚",
                winner_probability=0.08,
                use_free_spin=False,
            )
        except OperationalError:
            if mode == "postgresql":
                raise
            return (
                None  # SQLite may reject a busy writer, but must roll back everything.
            )

    with ThreadPoolExecutor(max_workers=len(user_ids)) as pool:
        results = list(pool.map(worker, user_ids))
    successful = [result for result in results if result is not None]
    assert successful
    assert sum(result["invite_awarded"] for result in successful) == 1
    with db.get_session() as session:
        assert session.scalar(select(func.count()).select_from(Invitation)) == 1
        assert session.scalar(select(func.sum(WheelInviteAudit.issued))) == 1
        assert session.scalar(select(func.sum(Statistics.credits))) == 7990
    return successful


def test_competing_users_get_only_one_global_code(concurrent_db):
    service.update_invite_quota_config({"global_weekly_limit": 1})
    _race(concurrent_db, list(range(1, 9)))
    assert quotas.get_stats()["global_used"] == 1


def test_same_user_gets_only_one_personal_code(concurrent_db):
    service.update_invite_quota_config({"personal_weekly_limit": 1})
    _race(concurrent_db, [1] * 8)
    stats = quotas.get_stats()
    assert stats["global_used"] == 1
    assert stats["users"] == [{"tg_id": 1, "issued": 1}]


def test_new_week_creation_race_is_not_duplicate_budget(concurrent_db, monkeypatch):
    service.update_invite_quota_config({"global_weekly_limit": 1})
    later = quotas.time.time() + quotas.WEEK_MS / 1000
    monkeypatch.setattr(quotas.time, "time", lambda: later)
    _race(concurrent_db, list(range(1, 9)))
    with db.get_session() as session:
        assert (
            session.scalar(select(func.count()).select_from(WheelInviteQuotaWeek)) == 2
        )
    assert quotas.get_stats()["global_used"] == 1


def test_quota_reassignment_moves_usage_in_all_modes(concurrent_db):
    # Seed actual committed events rather than inventing counters.
    wheel = config.DEFAULT_WHEEL_CONFIG
    for tg_id in [1, 1, 1, 2, 2]:
        repository.spin(
            tg_id=tg_id,
            config=wheel,
            winner_name="邀请码 1 枚",
            winner_probability=0.08,
            use_free_spin=False,
        )
    with db.get_session() as session:
        moved = repository.reassign_tg_id_tx(session, 1, 2)
        assert moved["wheel_invite_audit.tg_id"] == 3
    assert quotas.get_stats()["users"] == [{"tg_id": 2, "issued": 5}]
    assert quotas.get_stats()["global_used"] == 5


def test_single_and_ten_share_one_global_budget(concurrent_db):
    service.update_invite_quota_config({"global_weekly_limit": 3})
    wheel = LuckyWheelConfig(
        items=[
            LuckyWheelItem(name="积分 +10", probability=99.92),
            LuckyWheelItem(name="邀请码 1 枚", probability=0.08),
        ],
        cost_credits=10,
        min_credits_required=30,
    )
    barrier = Barrier(2)

    def worker(ten):
        barrier.wait(timeout=10)
        try:
            if ten:
                return repository.spin_ten(
                    tg_id=1, config=wheel, winners=[("邀请码 1 枚", 0.08)] * 10
                )
            return [
                repository.spin(
                    tg_id=2,
                    config=wheel,
                    winner_name="邀请码 1 枚",
                    winner_probability=0.08,
                    use_free_spin=False,
                )
            ]
        except OperationalError:
            if concurrent_db == "postgresql":
                raise
            return []

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [row for batch in pool.map(worker, [True, False]) for row in batch]
    assert results
    issued = sum(row["invite_awarded"] for row in results)
    assert issued == min(3, len(results))
    with db.get_session() as session:
        assert session.scalar(
            select(func.count()).select_from(WheelInviteAudit)
        ) == len(results)
        assert session.scalar(select(func.count()).select_from(Invitation)) == issued
        assert (
            session.scalar(select(func.sum(Statistics.credits))) == 8000 - 10 * issued
        )
    assert quotas.get_stats()["global_used"] == issued
