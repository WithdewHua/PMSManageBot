import asyncio
import importlib.util
import pickle
import sys
from collections.abc import Callable
from datetime import datetime
from inspect import isawaitable, iscoroutinefunction
from typing import Any, ClassVar

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.core.log import logger


class _SchedulerSingletonMeta(type):
    """Private singleton metaclass used only by Scheduler."""

    _instances: ClassVar[dict[type, object]] = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


TASK_REGISTRY: dict[str, Callable[..., Any]] = {}


def register_task(name: str, func: Callable[..., Any]) -> None:
    """Register a stable one-shot task name; repeated registration is idempotent."""
    if not isinstance(name, str) or not name or not callable(func):
        raise ValueError("task name must be nonempty and handler must be callable")
    previous = TASK_REGISTRY.get(name)
    if previous is not None and previous is not func:
        raise ValueError(f"task already registered: {name}")
    TASK_REGISTRY[name] = func


async def run_task(name: str, /, **kwargs: Any) -> Any:
    """Resolve the stable task name at execution time (also for persisted jobs)."""
    try:
        func = TASK_REGISTRY[name]
    except KeyError as error:
        raise LookupError(f"unregistered task: {name}") from error
    if iscoroutinefunction(func):
        return await func(**kwargs)
    # Sync handlers must not block APScheduler's asyncio event loop.
    result = await asyncio.to_thread(func, **kwargs)
    return await result if isawaitable(result) else result


class Scheduler(metaclass=_SchedulerSingletonMeta):
    def __init__(self) -> None:
        self.jobstores = {
            "default": MemoryJobStore(),
            "sqlalchemy": SQLAlchemyJobStore(url=settings.DB_URL),
        }
        self.executors = {
            "default": AsyncIOExecutor(),
            "threadpool": ThreadPoolExecutor(100),
        }
        # 配置调度器参数
        job_defaults = {
            "coalesce": True,  # 合并错过的任务
            "max_instances": 1,  # 每个任务最多同时运行1个实例
            "misfire_grace_time": 60,  # 任务最多可以延迟60秒执行
        }
        self.scheduler = AsyncIOScheduler(
            jobstores=self.jobstores,
            executors=self.executors,
            job_defaults=job_defaults,
            timezone=settings.TZ,
        )

    def start(self):
        if not self.scheduler.running:
            store = self.jobstores.get("sqlalchemy")
            if isinstance(store, SQLAlchemyJobStore):
                assert_no_legacy_job_refs(store)
            self.scheduler.start()

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown()

    def add_jobstore(self, jobstore, alias, **kwargs):
        self.jobstores.update({alias: jobstore})
        self.scheduler.add_jobstore(jobstore, alias=alias, **kwargs)

    def enable_named_persistent_tasks(self) -> None:
        """Deprecated compatibility hook; persistent jobs are guarded by default."""

    def _check_persisted_task(self, func: Any, options: dict[str, Any]) -> None:
        alias = options.get("jobstore", "default")
        store = self.jobstores.get(alias)
        if not isinstance(store, SQLAlchemyJobStore):
            return
        args = options.get("args", ())
        if (
            func is not run_task
            or not args
            or not isinstance(args[0], str)
            or args[0] not in TASK_REGISTRY
            or options.get("executor", "default") != "default"
        ):
            raise ValueError("persistent jobs require a registered named task")

    def add_job(self, *args, **kwargs):
        func = args[0] if args else kwargs.get("func")
        self._check_persisted_task(func, kwargs)
        return self.scheduler.add_job(*args, **kwargs)

    def add_async_job(
        self, func, *args, jobstore="default", executor="default", **kwargs
    ):
        """添加异步任务，默认使用AsyncIOExecutor"""
        self._check_persisted_task(
            func, {**kwargs, "jobstore": jobstore, "executor": executor}
        )
        return self.scheduler.add_job(
            func, *args, jobstore=jobstore, executor=executor, **kwargs
        )

    def add_sync_job(
        self, func, *args, jobstore="default", executor="threadpool", **kwargs
    ):
        """添加同步任务，使用ThreadPoolExecutor"""
        self._check_persisted_task(
            func, {**kwargs, "jobstore": jobstore, "executor": executor}
        )
        return self.scheduler.add_job(
            func, *args, jobstore=jobstore, executor=executor, **kwargs
        )

    def remove_job(self, job_id, jobstore=None):
        """移除任务"""
        self.scheduler.remove_job(job_id, jobstore=jobstore)

    def get_jobs(self, jobstore=None):
        """获取所有任务"""
        return self.scheduler.get_jobs(jobstore=jobstore)

    def pause_job(self, job_id, jobstore=None):
        """暂停任务"""
        self.scheduler.pause_job(job_id, jobstore=jobstore)

    def resume_job(self, job_id, jobstore=None):
        """恢复任务"""
        self.scheduler.resume_job(job_id, jobstore=jobstore)


def schedule_task(
    name: str,
    *,
    run_date: datetime | None = None,
    job_id: str,
    kwargs: dict[str, Any] | None = None,
    misfire_grace_time: int | None,
    **job_options: Any,
) -> Any:
    """Schedule a registered named task, choosing its misfire policy explicitly.

    ``jobstore="sqlalchemy"`` (the default) persists the job across restarts;
    ``jobstore="default"`` keeps it in memory and is rebuilt by startup recovery.
    Task parameters travel through ``kwargs``; the task name itself is the
    positional argument ``run_task`` resolves at execution time.

    Use ``None`` for blackjack timeouts, ``60`` for treasure auto-reopen and
    auction finishes.
    """
    if name not in TASK_REGISTRY:
        raise LookupError(f"unregistered task: {name}")
    scheduler = Scheduler()
    jobstore = job_options.get("jobstore", "sqlalchemy")
    if jobstore not in ("sqlalchemy", "default"):
        raise ValueError(f"unknown jobstore: {jobstore}")
    if job_options.get("executor", "default") != "default":
        raise ValueError("named one-shot tasks require the asyncio executor")
    trigger = job_options.pop("trigger", "date")
    if trigger not in {"date", "interval"}:
        raise ValueError(f"unsupported named task trigger: {trigger}")
    reserved = {"func", "id", "args", "kwargs", "run_date", "start_date"}
    if reserved.intersection(job_options):
        raise ValueError("named task arguments cannot override scheduler internals")
    trigger_options: dict[str, Any]
    if trigger == "date":
        if run_date is None:
            raise ValueError("date named tasks require run_date")
        trigger_options = {
            "run_date": run_date,
            **{
                key: value
                for key, value in job_options.items()
                if key not in {"jobstore", "executor"}
            },
        }
    else:
        if run_date is not None and "start_date" not in job_options:
            job_options["start_date"] = run_date
        trigger_options = {
            key: value
            for key, value in job_options.items()
            if key not in {"jobstore", "executor"}
        }
    return scheduler.add_async_job(
        func=run_task,
        trigger=trigger,
        id=job_id,
        args=(name,),
        kwargs=dict(kwargs or {}),
        jobstore=jobstore,
        misfire_grace_time=misfire_grace_time,
        **trigger_options,
    )


RUN_TASK_REF = "app.core.scheduler:run_task"


def _is_resolvable(func_ref: str) -> bool:
    """Check if a callable reference string can resolve to an importable module without importing the function."""
    if func_ref.startswith("app.webapp."):
        return False
    if ":" in func_ref:
        mod_name = func_ref.split(":", 1)[0]
    else:
        mod_name = func_ref.rsplit(".", 1)[0]
    try:
        spec = importlib.util.find_spec(mod_name)
        if spec is None:
            return False
        return spec.origin is not None or bool(spec.submodule_search_locations)
    except Exception:
        return False


def assert_no_legacy_job_refs(jobstore: SQLAlchemyJobStore) -> None:
    """Ensure no unmigrated or unresolvable legacy job references exist in jobstore.

    Must run before scheduler.start() to prevent APScheduler from silently
    deleting jobs whose module references no longer resolve.
    """
    table = jobstore.jobs_t
    with jobstore.engine.connect() as conn:
        if not jobstore.engine.dialect.has_table(conn, table.name, schema=table.schema):
            return
        rows = conn.execute(table.select()).all()

    legacy_jobs: list[tuple[str, str]] = []
    for row in rows:
        try:
            state = pickle.loads(row.job_state)
            func_ref = state.get("func") if isinstance(state, dict) else None
        except Exception:
            legacy_jobs.append((row.id, "<corrupted>"))
            continue

        if not isinstance(func_ref, str):
            legacy_jobs.append((row.id, str(func_ref)))
            continue

        if func_ref == RUN_TASK_REF:
            continue

        if not _is_resolvable(func_ref):
            legacy_jobs.append((row.id, func_ref))

    if legacy_jobs:
        job_details = ", ".join(f"{jid} ({fn})" for jid, fn in legacy_jobs)
        logger.critical(
            f"Found {len(legacy_jobs)} unresolvable legacy job reference(s) in persisted jobstore: "
            f"{job_details}. "
            "APScheduler will silently delete unresolvable jobs on startup. "
            "Please run 'python -m scripts.migrate_legacy_job_refs' to migrate legacy job references before starting."
        )
        sys.exit(1)
