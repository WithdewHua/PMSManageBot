"""Smoke-test B3 persisted task migration before scheduler startup."""

from __future__ import annotations

import asyncio
import pickle
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update

from app.core.scheduler import (
    RUN_TASK_REF,
    register_task,
    rewrite_job_references,
    run_task,
)
from app.schedule import LEGACY_TASK_REFS


async def main() -> int:
    events: list[tuple[str, dict[str, object]]] = []

    async def blackjack(**kwargs: object) -> None:
        events.append(("blackjack.hand_timeout", kwargs))

    async def treasure(**kwargs: object) -> None:
        events.append(("treasure.open_next_issue", kwargs))

    register_task("blackjack.hand_timeout", blackjack)
    register_task("treasure.open_next_issue", treasure)

    with tempfile.TemporaryDirectory(prefix="pms-b3-jobs-") as directory:
        database = Path(directory) / "jobs.db"
        url = f"sqlite:///{database}"
        store = SQLAlchemyJobStore(url=url)
        writer = AsyncIOScheduler(jobstores={"sqlalchemy": store}, timezone=UTC)
        writer.start(paused=True)
        run_date = datetime.now(UTC) + timedelta(seconds=0.25)
        jobs = (
            ("blackjack", "blackjack.hand_timeout", {"hand_id": 42}),
            ("treasure", "treasure.open_next_issue", {"source_issue_id": 9}),
        )
        for job_id, task_name, kwargs in jobs:
            old_ref = next(
                ref for ref, name in LEGACY_TASK_REFS.items() if name == task_name
            )
            writer.add_job(
                run_task,
                "date",
                run_date=run_date,
                id=job_id,
                jobstore="sqlalchemy",
                args=(task_name,),
                kwargs=kwargs,
                misfire_grace_time=None if job_id == "blackjack" else 60,
            )
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
                    .values(
                        job_state=pickle.dumps(payload, protocol=store.pickle_protocol)
                    )
                )
        writer.shutdown(wait=False)

        migrated = rewrite_job_references(store, LEGACY_TASK_REFS)
        if migrated != 2:
            raise AssertionError(f"expected two migrated jobs, got {migrated}")

        with store.engine.connect() as connection:
            rows = connection.execute(select(store.jobs_t.c.job_state)).all()
            assert all(pickle.loads(row[0])["func"] == RUN_TASK_REF for row in rows)

        reader = AsyncIOScheduler(jobstores={"sqlalchemy": store}, timezone=UTC)
        reader.start()
        await asyncio.sleep(0.8)
        reader.shutdown(wait=False)

    expected = [
        ("blackjack.hand_timeout", {"hand_id": 42}),
        ("treasure.open_next_issue", {"source_issue_id": 9}),
    ]
    if sorted(events, key=lambda item: item[0]) != sorted(
        expected, key=lambda item: item[0]
    ):
        raise AssertionError(f"unexpected task events: {events!r}")
    print(f"B3_JOB_SMOKE_OK migrated=2 events={events!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
