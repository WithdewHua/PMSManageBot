"""Rewrite persisted APScheduler callable references before deployment or rollback.

Compatibility wrapper delegating to scripts.migrate_legacy_job_refs.
"""

from scripts.migrate_legacy_job_refs import (
    LEGACY_TASK_REFS,
    RUN_TASK_REF,
    main,
    rewrite_job_references,
)

__all__ = [
    "LEGACY_TASK_REFS",
    "RUN_TASK_REF",
    "main",
    "rewrite_job_references",
]

if __name__ == "__main__":
    raise SystemExit(main())
