#!/usr/bin/env python3
"""Preview or explicitly apply the current week's verified invite quota baseline.

Default is a read-only database report. Apply requires both operator confirmations;
this script never issues codes, changes balances, or sends notifications.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="Write a new private (0600) dry-run report; otherwise print JSON",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Apply the previously reviewed report"
    )
    parser.add_argument("--input", type=Path, help="Reviewed report JSON for --apply")
    parser.add_argument(
        "--history-verified",
        action="store_true",
        help="Confirm complete history and custom prize semantics were checked",
    )
    parser.add_argument(
        "--writers-stopped",
        action="store_true",
        help="Confirm all old wheel writers/schedulers are stopped",
    )
    args = parser.parse_args()
    if args.apply and (
        not args.input or not args.history_verified or not args.writers_stopped
    ):
        parser.error(
            "--apply requires --input, --history-verified and --writers-stopped"
        )
    if args.apply and args.output:
        parser.error("--output is only for a dry-run report")
    if args.input and not args.apply:
        parser.error("--input requires --apply")

    from app.domains.luckywheel import service

    try:
        if args.apply:
            report = json.loads(args.input.read_text(encoding="utf-8"))
            if not isinstance(report, dict):
                raise ValueError("Report must be a JSON object")
            result = service.initialize_invite_quotas(
                report,
                history_verified=args.history_verified,
                writers_stopped=args.writers_stopped,
            )
        else:
            result = service.get_invite_quota_initialization_report()
        serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(serialized)
            print(f"Dry-run report written to {args.output}; review before applying.")
        else:
            print(serialized, end="")
    except Exception as error:
        print(f"Quota initialization refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
