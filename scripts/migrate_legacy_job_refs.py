"""Rewrite persisted APScheduler callable references before deployment or rollback.

Run ``python -m scripts.migrate_legacy_job_refs`` before starting the application
when upgrading from a pre-B3 release.

Run ``python -m scripts.migrate_legacy_job_refs --reverse --scheduler-stopped``
*before* rolling back to a pre-B3 image; otherwise APScheduler would delete jobs
whose new function reference no longer exists in the old code.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import pickletools
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from sqlalchemy import inspect, select, update

LEGACY_TASK_REFS: dict[str, str] = {
    "app.webapp.routers.activities.blackjack:_settle_blackjack_hand_on_timeout": "blackjack.hand_timeout",
    "app.webapp.routers.activities.treasure:_auto_create_next_treasure_issue_from": "treasure.open_next_issue",
}

RUN_TASK_REF = "app.core.scheduler:run_task"


def default_db_url() -> str:
    """Resolve database URL without importing application code."""
    if url := os.environ.get("DATABASE_URL"):
        return url
    env_file = Path("data/.env")
    if env_file.is_file():
        values: dict[str, str] = {}
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip("\"'")
        if values.get("DATABASE_URL"):
            return values["DATABASE_URL"]
        if values.get("DATABASE_TYPE", "").lower() == "postgresql":
            user = values.get("POSTGRES_USER", "postgres")
            password = values.get("POSTGRES_PASSWORD", "")
            host = values.get("POSTGRES_HOST", "localhost")
            port = values.get("POSTGRES_PORT", "5432")
            db = values.get("POSTGRES_DB", "pms_bot")
            return f"postgresql://{user}:{password}@{host}:{port}/{db}"
    return "sqlite:///data/data.db"


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


def _state_field_opcodes(
    data: bytes, field: str
) -> tuple[list[tuple[Any, Any, int]], int]:
    """Locate a top-level APScheduler job-state field without re-pickling it."""
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


def _rewrite_job_blob(
    data: bytes, legacy_refs: Mapping[str, str], *, reverse: bool
) -> bytes | None:
    """Rewrite known one-shot callables, preserving old bytes for rollback."""
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
            args_end = arg_ops[args_index + 2][2]
            return _patch_single_frame(
                data,
                [
                    (func_pos, func_end, _short_unicode(old_ref)),
                    (arg_pos, args_end, b")"),
                ],
            )
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


def rewrite_scheduler_rows(
    jobstore: SQLAlchemyJobStore,
    transform: Callable[[bytes], bytes | None],
) -> int:
    """Apply an atomic compare-and-swap transformation to stored job states."""
    table = jobstore.jobs_t
    if not inspect(jobstore.engine).has_table(table.name, schema=table.schema):
        return 0
    updated = 0
    with jobstore.engine.begin() as connection:
        rows = connection.execute(
            select(table.c.id, table.c.job_state).with_for_update()
        ).all()
        for row in rows:
            replacement = transform(row.job_state)
            if replacement is None:
                continue
            result = connection.execute(
                update(table)
                .where(table.c.id == row.id, table.c.job_state == row.job_state)
                .values(job_state=replacement)
            )
            if result.rowcount != 1:
                raise RuntimeError(f"job changed while migrating: {row.id}")
            updated += 1
    return updated


def rewrite_job_references(
    jobstore: SQLAlchemyJobStore,
    legacy_refs: Mapping[str, str] = LEGACY_TASK_REFS,
    *,
    reverse: bool = False,
) -> int:
    """Atomically migrate job blobs before APScheduler tries loading old paths."""
    if not legacy_refs or len(set(legacy_refs.values())) != len(legacy_refs):
        raise ValueError("legacy job references must map to distinct task names")
    return rewrite_scheduler_rows(
        jobstore,
        lambda blob: _rewrite_job_blob(blob, legacy_refs, reverse=reverse),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="restore old callable refs before image rollback",
    )
    parser.add_argument(
        "--scheduler-stopped",
        action="store_true",
        help="confirm every scheduler process using this jobstore is stopped",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="database URL (defaults to DATABASE_URL or data/.env)",
    )
    args = parser.parse_args(argv)
    if args.reverse and not args.scheduler_stopped:
        parser.error(
            "--reverse requires --scheduler-stopped during a maintenance window"
        )
    url = args.url or default_db_url()
    store = SQLAlchemyJobStore(url=url)
    rewritten = rewrite_job_references(store, reverse=args.reverse)
    print(json.dumps({"rewritten": rewritten, "reverse": args.reverse}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
