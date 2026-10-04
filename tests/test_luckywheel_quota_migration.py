"""SQLite migration rehearsal against legacy BIGINT wheel-stat primary keys."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.domains.luckywheel.models import (
    WheelInviteAudit,
    WheelInviteQuotaWeek,
    WheelStats,
)


@pytest.mark.parametrize("foreign_keys", [False, True])
def test_sqlite_upgrade_downgrade_upgrade_preserves_ids(tmp_path, foreign_keys):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    if foreign_keys:

        @sa.event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    old_metadata = sa.MetaData()
    old_stats = WheelStats.__table__.to_metadata(old_metadata)
    old_stats.c.id.type = sa.BigInteger()  # Actual pre-change SQLite declaration.
    old_metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            old_stats.insert(),
            {
                "id": 41,
                "tg_id": 1001,
                "item_name": "邀请码 1 枚",
                "cost_credits": 10,
                "credits_change": 0,
                "timestamp": 1000,
                "date": "1970-01-01",
                "source": None,
            },
        )
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/6c54e137c19b_add_luckywheel_invite_quotas.py"
    )
    spec = importlib.util.spec_from_file_location("quota_migration_under_test", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    for operation in (migration.upgrade, migration.downgrade, migration.upgrade):
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                operation()
            assert connection.scalar(sa.text("SELECT id FROM wheel_stats")) == 41
            if operation == migration.upgrade:
                assert (
                    connection.scalar(
                        sa.text("SELECT count(*) FROM wheel_invite_audit")
                    )
                    == 0
                )
                assert (
                    connection.scalar(
                        sa.text("SELECT count(*) FROM wheel_invite_quota_week")
                    )
                    == 0
                )

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO wheel_stats(tg_id,item_name,cost_credits,credits_change,timestamp,date) "
                "VALUES (1001,'积分 +10',10,10,1001,'1970-01-01')"
            )
        )
        assert connection.scalar(sa.text("SELECT max(id) FROM wheel_stats")) == 42
        connection.execute(
            WheelInviteQuotaWeek.__table__.insert(),
            {
                "week_start_ms": 0,
                "issued": 1,
                "initialized_at_ms": 1000,
                "is_baseline": True,
            },
        )
        inserted = connection.execute(
            WheelInviteAudit.__table__.insert(),
            {
                "wheel_stats_id": 41,
                "week_start_ms": 0,
                "tg_id": 1001,
                "issued": 1,
                "candidate_name": "邀请码 1 枚",
                "final_name": "邀请码 1 枚",
                "recorded_at_ms": 1000,
            },
        )
        assert inserted.inserted_primary_key[0] == 1
    engine.dispose()
