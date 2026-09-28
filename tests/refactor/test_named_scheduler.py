"""Stable names protect APScheduler's persisted one-shot jobs from refactors."""

from datetime import UTC, datetime
from threading import get_ident
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.util import obj_to_ref

from app.core import scheduler as named


@pytest.fixture(autouse=True)
def isolated_task_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(named, "TASK_REGISTRY", {})


@pytest.mark.asyncio
async def test_named_task_registration_and_dispatch() -> None:
    calls = []

    async def async_task(*, value: int) -> int:
        calls.append(value)
        return value + 1

    worker_threads = []

    def sync_task(*, value: int) -> int:
        worker_threads.append(get_ident())
        return value * 2

    named.register_task("domain.async", async_task)
    named.register_task("domain.async", async_task)
    named.register_task("domain.sync", sync_task)
    assert await named.run_task("domain.async", value=3) == 4
    assert await named.run_task("domain.sync", value=3) == 6
    assert calls == [3]
    assert len(worker_threads) == 1
    assert worker_threads[0] != get_ident()
    assert obj_to_ref(named.run_task) == "app.core.scheduler:run_task"
    with pytest.raises(LookupError, match="unregistered task"):
        await named.run_task("domain.missing")
    with pytest.raises(ValueError, match="already registered"):
        named.register_task("domain.async", lambda: None)
    with pytest.raises(ValueError, match="nonempty"):
        named.register_task("", async_task)


def _isolated_scheduler() -> tuple[named.Scheduler, Mock]:
    instance = object.__new__(named.Scheduler)
    add_job = Mock(return_value="created")
    instance.scheduler = cast(AsyncIOScheduler, SimpleNamespace(add_job=add_job))
    instance.jobstores = {
        "default": MemoryJobStore(),
        "sqlalchemy": SQLAlchemyJobStore(url="sqlite:///:memory:"),
    }
    instance.named_persistent_only = False
    return instance, add_job


def test_persistent_store_guard_rejects_every_raw_job_entry_point() -> None:
    instance, add_job = _isolated_scheduler()

    async def raw_job() -> None:
        pass

    # Until 5.4 rewrites both legacy callers, the current B2 path stays usable.
    instance.add_async_job(raw_job, trigger="date", jobstore="sqlalchemy")
    instance.enable_named_persistent_tasks()
    for entry in (
        lambda: instance.add_async_job(raw_job, trigger="date", jobstore="sqlalchemy"),
        lambda: instance.add_sync_job(raw_job, trigger="date", jobstore="sqlalchemy"),
        lambda: instance.add_job(raw_job, trigger="date", jobstore="sqlalchemy"),
    ):
        with pytest.raises(ValueError, match="registered named task"):
            entry()
    assert add_job.call_count == 1
    # Memory jobstore semantics stay unchanged.
    instance.add_async_job(raw_job, trigger="date", jobstore="default")
    named.register_task("domain.timeout", raw_job)
    instance.add_async_job(
        named.run_task, trigger="date", jobstore="sqlalchemy", args=("domain.timeout",)
    )
    with pytest.raises(ValueError, match="registered named task"):
        instance.add_sync_job(
            named.run_task,
            trigger="date",
            jobstore="sqlalchemy",
            args=("domain.timeout",),
        )
    with pytest.raises(ValueError, match="registered named task"):
        instance.add_async_job(
            named.run_task,
            trigger="date",
            jobstore="sqlalchemy",
            executor="threadpool",
            args=("domain.timeout",),
        )
    with pytest.raises(ValueError, match="registered named task"):
        instance.add_async_job(
            named.run_task, trigger="date", jobstore="sqlalchemy", args=("missing",)
        )
    assert add_job.call_count == 3


def test_schedule_task_persists_name_as_first_arg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, add_job = _isolated_scheduler()
    instance.enable_named_persistent_tasks()
    monkeypatch.setattr(named, "Scheduler", lambda: instance)
    named.register_task("blackjack.hand_timeout", lambda *, hand_id: None)
    run_date = datetime(2026, 9, 27, tzinfo=UTC)
    options = {"hand_id": 42}
    assert (
        named.schedule_task(
            "blackjack.hand_timeout",
            run_date=run_date,
            job_id="blackjack_timeout_42",
            kwargs=options,
            misfire_grace_time=None,
            replace_existing=True,
        )
        == "created"
    )
    assert options == {"hand_id": 42}
    add_job.assert_called_once_with(
        named.run_task,
        trigger="date",
        jobstore="sqlalchemy",
        executor="default",
        run_date=run_date,
        id="blackjack_timeout_42",
        args=("blackjack.hand_timeout",),
        kwargs={"hand_id": 42},
        misfire_grace_time=None,
        replace_existing=True,
    )
    with pytest.raises(TypeError, match="misfire_grace_time"):
        # Deliberately omit the required option at runtime despite static typing.
        cast(Any, named.schedule_task)(
            "blackjack.hand_timeout", run_date=run_date, job_id="unsafe"
        )
    with pytest.raises(LookupError, match="unregistered task"):
        named.schedule_task(
            "missing", run_date=run_date, job_id="missing", misfire_grace_time=60
        )
    # 未注册的任务在哪个 jobstore 都拒绝
    with pytest.raises(LookupError, match="unregistered task"):
        named.schedule_task(
            "missing",
            run_date=run_date,
            job_id="missing",
            misfire_grace_time=60,
            jobstore="default",
        )
    with pytest.raises(ValueError, match="unknown jobstore"):
        named.schedule_task(
            "blackjack.hand_timeout",
            run_date=run_date,
            job_id="invalid",
            misfire_grace_time=None,
            jobstore="elsewhere",
        )
    with pytest.raises(ValueError, match="asyncio executor"):
        named.schedule_task(
            "blackjack.hand_timeout",
            run_date=run_date,
            job_id="invalid",
            misfire_grace_time=None,
            executor="threadpool",
        )
    with pytest.raises(ValueError, match="cannot override"):
        named.schedule_task(
            "blackjack.hand_timeout",
            run_date=run_date,
            job_id="invalid",
            misfire_grace_time=None,
            args=("wrong",),
        )


@pytest.mark.asyncio
async def test_memory_jobstore_named_task_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """具名任务在内存 jobstore 中的调度：执行、按 id 替换、按 jobstore 删除。"""
    jobstores = {
        "default": MemoryJobStore(),
        "sqlalchemy": SQLAlchemyJobStore(url="sqlite:///:memory:"),
    }
    async_scheduler = AsyncIOScheduler(jobstores=jobstores, timezone=UTC)
    async_scheduler.start()

    instance = object.__new__(named.Scheduler)
    instance.scheduler = async_scheduler
    instance.jobstores = jobstores
    # 内存 jobstore 不受持久化守卫约束，只要求任务是注册过的具名任务
    instance.named_persistent_only = True
    monkeypatch.setattr(named, "Scheduler", lambda: instance)

    calls: list[int] = []

    async def finish_auction(*, auction_id: int) -> None:
        calls.append(auction_id)

    named.register_task("auction.finish", finish_auction)
    run_date = datetime(2026, 9, 27, tzinfo=UTC)

    try:
        named.schedule_task(
            "auction.finish",
            run_date=run_date,
            job_id="finish_auction_1",
            kwargs={"auction_id": 1},
            misfire_grace_time=60,
            jobstore="default",
            replace_existing=True,
        )
        job = async_scheduler.get_job("finish_auction_1", jobstore="default")
        assert job is not None
        assert job.func is named.run_task
        assert job.args == ("auction.finish",)
        assert job.kwargs == {"auction_id": 1}
        assert job.misfire_grace_time == 60

        # 执行：run_task 解析具名任务并把 kwargs 交给处理函数
        await named.run_task(*job.args, **job.kwargs)
        assert calls == [1]

        # 按 id 替换：同一个 id 只留一个任务，参数已更新
        named.schedule_task(
            "auction.finish",
            run_date=run_date,
            job_id="finish_auction_1",
            kwargs={"auction_id": 2},
            misfire_grace_time=60,
            jobstore="default",
            replace_existing=True,
        )
        jobs = [
            item
            for item in async_scheduler.get_jobs(jobstore="default")
            if item.id == "finish_auction_1"
        ]
        assert len(jobs) == 1
        assert jobs[0].kwargs == {"auction_id": 2}

        # 按 jobstore 删除：内存中的删除不影响持久化存储
        instance.remove_job("finish_auction_1", jobstore="default")
        assert async_scheduler.get_job("finish_auction_1", jobstore="default") is None
        assert (
            async_scheduler.get_job("finish_auction_1", jobstore="sqlalchemy") is None
        )
    finally:
        async_scheduler.shutdown()
