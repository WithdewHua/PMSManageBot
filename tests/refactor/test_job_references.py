"""B3's SQLAlchemy jobstore migration must be atomic and byte-reversible."""

import pickle
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import inspect, select, update

from app.core.scheduler import run_task
from scripts.migrate_legacy_job_refs import (
    LEGACY_TASK_REFS,
    RUN_TASK_REF,
    rewrite_job_references,
)
from scripts.migrate_legacy_job_refs import (
    main as rewrite_cli,
)


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


def _rows(store: SQLAlchemyJobStore) -> dict[str, tuple[float | None, bytes]]:
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


@pytest.mark.asyncio
async def test_migrates_both_old_jobs_and_restores_original_bytes(
    tmp_path: Path,
) -> None:
    store = SQLAlchemyJobStore(url=f"sqlite:///{tmp_path / 'jobs.db'}")
    scheduler = AsyncIOScheduler(jobstores={"sqlalchemy": store}, timezone=UTC)
    scheduler.start(paused=True)
    run_date = datetime.now(UTC) + timedelta(days=4)
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
        original = _rows(store)
        assert rewrite_job_references(store, LEGACY_TASK_REFS) == 2
        assert rewrite_job_references(store, LEGACY_TASK_REFS) == 0
        migrated = _rows(store)
        for job_id, (task_name, kwargs, misfire) in expectations.items():
            old = pickle.loads(original[job_id][1])
            new = pickle.loads(migrated[job_id][1])
            assert original[job_id][0] == migrated[job_id][0]
            assert new["func"] == RUN_TASK_REF
            assert new["args"] == (task_name,)
            assert new["name"] == old["name"]
            assert new["id"] == job_id
            assert new["kwargs"] == kwargs
            assert new["next_run_time"] == old["next_run_time"]
            assert new["misfire_grace_time"] == misfire
            job = store.lookup_job(job_id)
            assert job is not None
            assert job.func is run_task
            assert job.args == (task_name,)
        assert (
            rewrite_cli(
                [
                    "--url",
                    f"sqlite:///{tmp_path / 'jobs.db'}",
                    "--reverse",
                    "--scheduler-stopped",
                ]
            )
            == 0
        )
        assert _rows(store) == original  # not merely equal unpickled dictionaries
        assert rewrite_job_references(store, LEGACY_TASK_REFS, reverse=True) == 0
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_forward_migration_fails_atomically_on_unmapped_old_job(
    tmp_path: Path,
) -> None:
    store = SQLAlchemyJobStore(url=f"sqlite:///{tmp_path / 'jobs.db'}")
    scheduler = AsyncIOScheduler(jobstores={"sqlalchemy": store}, timezone=UTC)
    scheduler.start(paused=True)
    try:
        old_ref = next(iter(LEGACY_TASK_REFS))
        for job_id in ("a_known", "z_unknown"):
            scheduler.add_job(
                run_task,
                "date",
                run_date=datetime.now(UTC) + timedelta(days=4),
                jobstore="sqlalchemy",
                id=job_id,
                args=("blackjack.hand_timeout",),
                kwargs={"hand_id": 1},
                misfire_grace_time=None,
            )
            _install_legacy_callable(store, job_id, old_ref)
        with store.engine.begin() as connection:
            unknown = connection.execute(
                select(store.jobs_t.c.job_state).where(store.jobs_t.c.id == "z_unknown")
            ).scalar_one()
            state = pickle.loads(unknown)
            state["func"] = "app.webapp.routers.activities.unknown:missing"
            connection.execute(
                update(store.jobs_t)
                .where(store.jobs_t.c.id == "z_unknown")
                .values(job_state=pickle.dumps(state, protocol=store.pickle_protocol))
            )
        original = _rows(store)
        with pytest.raises(ValueError, match="unmapped legacy persisted job"):
            rewrite_job_references(store, LEGACY_TASK_REFS)
        assert _rows(store) == original
    finally:
        scheduler.shutdown(wait=False)


def test_first_boot_without_jobstore_table_does_not_create_schema(
    tmp_path: Path,
) -> None:
    store = SQLAlchemyJobStore(url=f"sqlite:///{tmp_path / 'fresh.db'}")
    assert rewrite_job_references(store, LEGACY_TASK_REFS) == 0
    assert not inspect(store.engine).has_table(store.jobs_t.name)


def test_reverse_requires_scheduler_stop_confirmation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        rewrite_cli(["--reverse", "--url", "sqlite:///unused.db"])
    assert error.value.code == 2
    assert "scheduler-stopped" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_reverse_converts_jobs_created_after_b3(tmp_path: Path) -> None:
    store = SQLAlchemyJobStore(url=f"sqlite:///{tmp_path / 'new.db'}")
    scheduler = AsyncIOScheduler(jobstores={"sqlalchemy": store}, timezone=UTC)
    scheduler.start(paused=True)
    try:
        scheduler.add_job(
            run_task,
            "date",
            run_date=datetime.now(UTC) + timedelta(days=4),
            jobstore="sqlalchemy",
            id="new_treasure",
            args=("treasure.open_next_issue",),
            kwargs={"source_issue_id": 27},
            misfire_grace_time=60,
        )
        original_time = _rows(store)["new_treasure"][0]
        assert rewrite_job_references(store, LEGACY_TASK_REFS, reverse=True) == 1
        state = pickle.loads(_rows(store)["new_treasure"][1])
        assert state["func"] == next(
            ref
            for ref, name in LEGACY_TASK_REFS.items()
            if name == "treasure.open_next_issue"
        )
        assert state["args"] == ()
        assert state["kwargs"] == {"source_issue_id": 27}
        assert state["misfire_grace_time"] == 60
        assert _rows(store)["new_treasure"][0] == original_time
        assert rewrite_job_references(store, LEGACY_TASK_REFS, reverse=True) == 0
    finally:
        scheduler.shutdown(wait=False)
