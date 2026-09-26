import asyncio
import pickle
import pickletools
from collections.abc import Callable, Mapping
from datetime import datetime
from inspect import isawaitable, iscoroutinefunction
from typing import Any, cast

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.core.log import logger
from app.core.singleton import SingletonMeta

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


class Scheduler(metaclass=SingletonMeta):
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
        # B3 5.4 enables enforcement after replacing both legacy call sites.
        # Until then, B2 persisted jobs must remain schedulable on restarts.
        self.named_persistent_only = False

    def start(self):
        if not self.scheduler.running:
            self.scheduler.start()

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown()

    def add_jobstore(self, jobstore, alias, **kwargs):
        self.jobstores.update({alias: jobstore})
        self.scheduler.add_jobstore(jobstore, alias=alias, **kwargs)

    def enable_named_persistent_tasks(self) -> None:
        """Turn on the persistent-store guard after B3 task registration."""
        self.named_persistent_only = True

    def _check_persisted_task(self, func: Any, options: dict[str, Any]) -> None:
        alias = options.get("jobstore", "default")
        store = self.jobstores.get(alias)
        if not self.named_persistent_only or not isinstance(store, SQLAlchemyJobStore):
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
    run_date: datetime,
    job_id: str,
    kwargs: dict[str, Any] | None = None,
    misfire_grace_time: int | None,
    **job_options: Any,
) -> Any:
    """Persist a named task; callers must choose their legacy misfire policy explicitly.

    Use ``None`` for blackjack timeouts and ``60`` for treasure auto-reopen.
    """
    if name not in TASK_REGISTRY:
        raise LookupError(f"unregistered task: {name}")
    if job_options.get("jobstore", "sqlalchemy") != "sqlalchemy":
        raise ValueError("named one-shot tasks require the persistent jobstore")
    if job_options.get("executor", "default") != "default":
        raise ValueError("named one-shot tasks require the asyncio executor")
    reserved = {"func", "trigger", "id", "args", "kwargs", "run_date"}
    if reserved.intersection(job_options):
        raise ValueError("named task arguments cannot override scheduler internals")
    return Scheduler().add_async_job(
        func=run_task,
        trigger="date",
        id=job_id,
        run_date=run_date,
        args=(name,),
        kwargs=dict(kwargs or {}),
        jobstore="sqlalchemy",
        misfire_grace_time=misfire_grace_time,
        **{key: value for key, value in job_options.items() if key != "jobstore"},
    )


RUN_TASK_REF = "app.core.scheduler:run_task"


def _state_field_opcodes(
    data: bytes, field: str
) -> tuple[list[tuple[Any, Any, int]], int]:
    """Locate a top-level APScheduler job-state field without re-pickling it."""
    # pickletools stubs mark opcode positions optional, but genops supplies
    # concrete integer offsets for every decoded opcode.
    ops = cast(list[tuple[Any, Any, int]], list(pickletools.genops(data)))
    matches = [
        index
        for index, (opcode, value, _pos) in enumerate(ops)
        if opcode.name == "SHORT_BINUNICODE" and value == field
    ]
    if len(matches) != 1:
        raise ValueError(f"unsupported job-state pickle: {field} key not unique")
    index = matches[0] + 1
    while index < len(ops) and ops[index][0].name in {
        "MEMOIZE",
        "BINPUT",
        "LONG_BINPUT",
    }:
        index += 1
    if index >= len(ops):
        raise ValueError(f"unsupported job-state pickle: missing {field} value")
    return ops, index


def _short_unicode(value: str) -> bytes:
    encoded = value.encode("utf-8")
    if len(encoded) >= 256:
        raise ValueError("job reference exceeds single-byte pickle string length")
    return b"\x8c" + bytes((len(encoded),)) + encoded


def _patch_single_frame(data: bytes, patches: list[tuple[int, int, bytes]]) -> bytes:
    """Replace only reviewed value opcodes, adjusting one pickle FRAME length."""
    if len(data) < 11 or data[:2] not in {b"\x80\x04", b"\x80\x05"} or data[2] != 0x95:
        raise ValueError("unsupported job-state pickle protocol or frame")
    if int.from_bytes(data[3:11], "little") != len(data) - 11:
        raise ValueError("unsupported multi-frame job-state pickle")
    payload = data[11:]
    last = len(data)
    for start, stop, replacement in sorted(patches, reverse=True):
        if start < 11 or stop > last or start >= stop:
            raise ValueError("overlapping or invalid job-state pickle patch")
        payload = payload[: start - 11] + replacement + payload[stop - 11 :]
        last = start
    return data[:3] + len(payload).to_bytes(8, "little") + payload


def _rewrite_job_blob(
    data: bytes, legacy_refs: Mapping[str, str], *, reverse: bool
) -> bytes | None:
    """Rewrite the two known one-shot callables, preserving old bytes for rollback.

    Existing jobs are edited at pickle opcode boundaries, not reconstructed with
    ``pickle.dumps``: a decode/re-encode round trip changes memoization and is not
    byte-identical even if the resulting dictionary has the same values.
    """
    state = pickle.loads(data)
    if not isinstance(state, dict) or not isinstance(state.get("func"), str):
        raise TypeError("unsupported APScheduler job state")
    original_ref = state["func"]
    if reverse:
        if original_ref != RUN_TASK_REF:
            return None
        by_name = {name: ref for ref, name in legacy_refs.items()}
        if len(by_name) != len(legacy_refs):
            raise ValueError("multiple legacy refs mapped to the same task name")
        args = state.get("args")
        if not isinstance(args, tuple) or not args or args[0] not in by_name:
            raise ValueError("persisted named job has no reversible legacy reference")
        old_ref = by_name[args[0]]
        old_args = args[1:]
    else:
        if original_ref not in legacy_refs:
            if original_ref.startswith("app.webapp.routers.activities."):
                raise ValueError(f"unmapped legacy persisted job: {original_ref}")
            return None
        old_ref = original_ref
        if state.get("args") != ():
            raise ValueError(
                f"legacy job has unexpected positional arguments: {old_ref}"
            )
        args = (legacy_refs[old_ref],)
        old_args = ()

    ops, func_index = _state_field_opcodes(data, "func")
    opcode, value, func_pos = ops[func_index]
    if opcode.name != "SHORT_BINUNICODE" or value != original_ref:
        raise ValueError("unsupported job-state function encoding")
    func_end = ops[func_index + 1][2]
    arg_ops, args_index = _state_field_opcodes(data, "args")
    arg_op, arg_value, arg_pos = arg_ops[args_index]
    if reverse:
        if (
            arg_op.name == "SHORT_BINUNICODE"
            and arg_value == args[0]
            and arg_ops[args_index + 1][0].name == "TUPLE1"
        ):
            # Our original-byte rewrite emitted no MEMOIZE for the new string,
            # so all later memo indexes still match the original pickle.
            args_end = arg_ops[args_index + 2][2]
            return _patch_single_frame(
                data,
                [
                    (func_pos, func_end, _short_unicode(old_ref)),
                    (arg_pos, args_end, b")"),
                ],
            )
        # A job created after B3 has no original bytes to restore. Restore its
        # callable semantics while leaving id, schedule, kwargs, and name intact.
        state["func"] = old_ref
        state["args"] = old_args
        return pickle.dumps(state, protocol=data[1])
    if arg_op.name != "EMPTY_TUPLE":
        raise ValueError("unsupported legacy job argument encoding")
    args_end = arg_ops[args_index + 1][2]
    return _patch_single_frame(
        data,
        [
            (func_pos, func_end, _short_unicode(RUN_TASK_REF)),
            (arg_pos, args_end, _short_unicode(args[0]) + b"\x85"),
        ],
    )


def rewrite_job_references(
    jobstore: SQLAlchemyJobStore,
    legacy_refs: Mapping[str, str],
    *,
    reverse: bool = False,
) -> int:
    """Atomically migrate job blobs before APScheduler tries loading old paths.

    The store's table may not exist on a first boot; APScheduler creates it in
    ``scheduler.start()`` after this migration. Unknown old jobs fail closed.
    """
    if not legacy_refs or len(set(legacy_refs.values())) != len(legacy_refs):
        raise ValueError("legacy job references must map to distinct task names")
    from app.core import db as core_db

    updated = core_db.rewrite_scheduler_rows(
        jobstore,
        lambda blob: _rewrite_job_blob(blob, legacy_refs, reverse=reverse),
    )
    logger.info(f"Persisted job reference migration: {updated} rewritten")
    return updated
