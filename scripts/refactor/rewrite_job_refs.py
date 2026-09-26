"""Rewrite persisted APScheduler callable references before deployment or rollback.

Run ``python -m scripts.refactor.rewrite_job_refs --reverse`` *before*
rolling back a B3 image; otherwise APScheduler would delete jobs whose new
function reference no longer exists in the old code.
"""

import argparse
import json

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from app.core.config import settings
from app.core.scheduler import rewrite_job_references
from app.schedule import LEGACY_TASK_REFS


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
        help="confirm every B3 scheduler process using this jobstore is stopped",
    )
    parser.add_argument(
        "--url", default=None, help="database URL (defaults to settings.DB_URL)"
    )
    args = parser.parse_args(argv)
    if args.reverse and not args.scheduler_stopped:
        parser.error(
            "--reverse requires --scheduler-stopped during a maintenance window"
        )
    store = SQLAlchemyJobStore(url=args.url or settings.DB_URL)
    rewritten = rewrite_job_references(store, LEGACY_TASK_REFS, reverse=args.reverse)
    print(json.dumps({"rewritten": rewritten, "reverse": args.reverse}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
