"""Tests for scheduler startup guard (assert_no_legacy_job_refs)."""

from __future__ import annotations

import pickle
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update

from app.core.scheduler import (
    TASK_REGISTRY,
    Scheduler,
    assert_no_legacy_job_refs,
    run_task,
)
from scripts.migrate_legacy_job_refs import (
    LEGACY_TASK_REFS,
    rewrite_job_references,
)
from scripts.migrate_legacy_job_refs import (
    main as migrate_cli,
)


@pytest.fixture(autouse=True)
def isolate_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.scheduler.TASK_REGISTRY", dict(TASK_REGISTRY))


def _install_legacy_callable(
    store: SQLAlchemyJobStore, job_id: str, old_ref: str
) -> None:
    with store.engine.begin() as connection:
        state = connection.execute(
            select(store.jobs_t.c.job_state).where(store.jobs_t.c.id == job_id)
        ).scalar_one()
        payload = pickle.loads(state)
        payload["func"] = old_ref
        payload["args"] = ()
        connection.execute(
            update(store.jobs_t)
            .where(store.jobs_t.c.id == job_id)
            .values(job_state=pickle.dumps(payload, protocol=store.pickle_protocol))
        )


def _fetch_rows(store: SQLAlchemyJobStore) -> dict[str, tuple[float | None, bytes]]:
    with store.engine.connect() as connection:
        return {
            row.id: (row.next_run_time, row.job_state)
            for row in connection.execute(
                select(
                    store.jobs_t.c.id,
                    store.jobs_t.c.next_run_time,
                    store.jobs_t.c.job_state,
                )
            )
        }


def _seed_legacy_jobs(
    store: SQLAlchemyJobStore,
) -> tuple[
    dict[str, tuple[str, dict[str, Any], int | None]],
    dict[str, tuple[float | None, bytes]],
]:
    scheduler = AsyncIOScheduler(jobstores={"sqlalchemy": store}, timezone=UTC)
    scheduler.start(paused=True)
    run_date = datetime.now(UTC) + timedelta(days=2)
    expectations = {
        "blackjack_timeout_42": ("blackjack.hand_timeout", {"hand_id": 42}, None),
        "treasure_auto_reopen_9": (
            "treasure.open_next_issue",
            {"source_issue_id": 9},
            60,
        ),
    }
    try:
        for job_id, (task_name, kwargs, misfire) in expectations.items():
            old_ref = next(
                ref for ref, name in LEGACY_TASK_REFS.items() if name == task_name
            )
            scheduler.add_job(
                run_task,
                "date",
                run_date=run_date,
                id=job_id,
                jobstore="sqlalchemy",
                args=(task_name,),
                kwargs=kwargs,
                misfire_grace_time=misfire,
            )
            _install_legacy_callable(store, job_id, old_ref)
        return expectations, _fetch_rows(store)
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_guard_exits_on_legacy_records_and_preserves_rows(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = SQLAlchemyJobStore(url=f"sqlite:///{tmp_path / 'guard.db'}")
    _, original_rows = _seed_legacy_jobs(store)

    with caplog.at_level("CRITICAL"), pytest.raises(SystemExit) as exc_info:
        assert_no_legacy_job_refs(store)

    assert exc_info.value.code != 0
    assert "scripts.migrate_legacy_job_refs" in caplog.text
    assert "blackjack_timeout_42" in caplog.text
    assert "treasure_auto_reopen_9" in caplog.text

    # Verify rows in jobstore are unmodified and byte-identical
    current_rows = _fetch_rows(store)
    assert current_rows == original_rows


@pytest.mark.asyncio
async def test_startup_succeeds_after_migration_and_jobs_trigger(
    tmp_path: Path,
) -> None:
    store = SQLAlchemyJobStore(url=f"sqlite:///{tmp_path / 'migrated.db'}")
    _seed_legacy_jobs(store)

    # Run migration
    rewritten = rewrite_job_references(store)
    assert rewritten == 2

    # Guard now passes without raising
    assert_no_legacy_job_refs(store)

    executed: list[str] = []

    def mock_blackjack(**kwargs: Any) -> None:
        executed.append(f"blackjack:{kwargs.get('hand_id')}")

    def mock_treasure(**kwargs: Any) -> None:
        executed.append(f"treasure:{kwargs.get('source_issue_id')}")

    TASK_REGISTRY["blackjack.hand_timeout"] = mock_blackjack
    TASK_REGISTRY["treasure.open_next_issue"] = mock_treasure

    scheduler = AsyncIOScheduler(jobstores={"sqlalchemy": store}, timezone=UTC)
    scheduler.start(paused=True)
    try:
        job1 = store.lookup_job("blackjack_timeout_42")
        job2 = store.lookup_job("treasure_auto_reopen_9")
        assert job1 is not None and job1.func is run_task
        assert job2 is not None and job2.func is run_task
    finally:
        scheduler.shutdown(wait=False)


def test_guard_succeeds_when_table_does_not_exist(tmp_path: Path) -> None:
    store = SQLAlchemyJobStore(url=f"sqlite:///{tmp_path / 'empty.db'}")
    # Table has not been created yet
    assert_no_legacy_job_refs(store)


@pytest.mark.asyncio
async def test_scheduler_start_triggers_guard(tmp_path: Path) -> None:
    db_path = tmp_path / "app_scheduler.db"
    store = SQLAlchemyJobStore(url=f"sqlite:///{db_path}")
    _seed_legacy_jobs(store)

    scheduler = Scheduler()
    scheduler.jobstores["sqlalchemy"] = store

    with pytest.raises(SystemExit) as exc_info:
        scheduler.start()

    assert exc_info.value.code != 0


@pytest.mark.asyncio
async def test_cli_migration_then_guard_succeeds(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'cli_test.db'}"
    store = SQLAlchemyJobStore(url=db_url)
    _seed_legacy_jobs(store)

    # CLI migration
    exit_code = migrate_cli(["--url", db_url])
    assert exit_code == 0

    # Guard passes
    assert_no_legacy_job_refs(store)


def test_subprocess_startup_guard_exits_with_nonzero_and_critical_log(
    tmp_path: Path,
) -> None:
    import os
    import subprocess
    import sys

    db_path = tmp_path / "subproc.db"
    store = SQLAlchemyJobStore(url=f"sqlite:///{db_path}")
    store.jobs_t.create(store.engine, checkfirst=True)
    with store.engine.begin() as conn:
        conn.execute(
            store.jobs_t.insert().values(
                id="old_blackjack",
                next_run_time=9999999999.0,
                job_state=pickle.dumps(
                    {
                        "func": "app.webapp.routers.activities.blackjack:_settle_blackjack_hand_on_timeout"
                    }
                ),
            )
        )
        conn.execute(
            store.jobs_t.insert().values(
                id="old_treasure",
                next_run_time=9999999999.0,
                job_state=pickle.dumps(
                    {
                        "func": "app.webapp.routers.activities.treasure:_auto_create_next_treasure_issue_from"
                    }
                ),
            )
        )

    code = f"""
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from app.core.scheduler import assert_no_legacy_job_refs
store = SQLAlchemyJobStore(url='sqlite:///{db_path}')
assert_no_legacy_job_refs(store)
"""
    env = {**os.environ, "PYTHONPATH": "src"}
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode != 0
    assert "CRITICAL" in result.stderr or "CRITICAL" in result.stdout
    assert "scripts.migrate_legacy_job_refs" in (result.stderr + result.stdout)
    assert "old_blackjack" in (result.stderr + result.stdout)
    assert "old_treasure" in (result.stderr + result.stdout)
