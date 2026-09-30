"""Export unused privileged invitation codes as a PRIVILEGED_CODES= line for rollback.

This script is strictly read-only and never writes to the database.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine, select

from app.domains.invitation.models import Invitation


def export_unused_privileged_codes(url: str | None = None) -> str:
    """Return formatted PRIVILEGED_CODES= line of unused privileged codes."""
    stmt = (
        select(Invitation.code)
        .where(Invitation.is_privileged == 1, Invitation.is_used == 0)
        .order_by(Invitation.code)
    )
    if url:
        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                codes = conn.execute(stmt).scalars().all()
        finally:
            engine.dispose()
    else:
        from app.core.db import get_session

        with get_session() as session:
            codes = session.execute(stmt).scalars().all()
    return f"PRIVILEGED_CODES={','.join(codes)}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export unused privileged codes for rollback"
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Database URL (defaults to application DB_URL)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file path (defaults to stdout)",
    )
    args = parser.parse_args(argv)

    line = export_unused_privileged_codes(args.url)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(line + "\n", encoding="utf-8")
    else:
        sys.stdout.write(line + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
