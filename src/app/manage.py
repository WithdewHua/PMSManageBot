"""Manual operational commands for the backend.

The old ``app.databases.db_func`` and ``app.utils.report`` module entry points
are intentionally replaced by these explicit subcommands in B3. The command
bodies preserve their historical ordering, defaults, and side effects.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from app.domains.accounts.service import update_plex_info
from app.domains.reports import constants as report_constants
from app.domains.reports import service as report_service
from app.domains.watch_rewards.service import update_emby_credits, update_plex_credits
from app.subscriptions import register_all


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.manage")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "legacy-credit-sync",
        help="update Plex credits, Plex user info, then Emby credits",
    )

    report = subparsers.add_parser(
        "report",
        description="Use Tautulli to pull library and user statistics for date range.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    report.add_argument(
        "-d",
        "--days",
        default=7,
        metavar="",
        type=int,
        help="Enter in number of days to go back.\n(default: %(default)s)",
    )
    report.add_argument(
        "-t",
        "--top",
        default=5,
        metavar="",
        type=int,
        help="Enter in number of top users to find.\n(default: %(default)s)",
    )
    report.add_argument(
        "--stat",
        default="duration",
        choices=report_constants.STAT_CHOICE,
        help="Enter in stats type to show.\n(default: %(default)s)",
    )
    report.add_argument(
        "--refresh", action="store_true", help="Refresh all libraries in Tautulli"
    )
    report.add_argument("--all_stats", action="store_true", help="Retrieve all stats.")
    report.add_argument(
        "--library_stats", action="store_true", help="Only retrieve library stats."
    )
    report.add_argument(
        "--user_stats", action="store_true", help="Only retrieve users stats."
    )
    report.add_argument(
        "--watched_stats",
        action="store_true",
        help="Only retrieve watched movies and tv_shows stats.",
    )
    report.add_argument("--emby", action="store_true", help="Retrieve stats for Emby.")
    return parser


def _run_legacy_credit_sync() -> None:
    update_plex_credits()
    update_plex_info()
    update_emby_credits()


def _run_report(options: argparse.Namespace) -> None:
    # Deliberately do not print the return value: this preserves the legacy CLI.
    report_service.stats_report(
        days=options.days,
        top=options.top,
        stat=options.stat,
        refresh=options.refresh,
        all_stats=options.all_stats,
        library_stats=options.library_stats,
        user_stats=options.user_stats,
        watched_stats=options.watched_stats,
        emby=options.emby,
    )


def main(argv: Sequence[str] | None = None) -> int:
    register_all()
    options = _parser().parse_args(argv)
    if options.command == "legacy-credit-sync":
        _run_legacy_credit_sync()
    elif options.command == "report":
        _run_report(options)
    else:  # pragma: no cover - argparse enforces the subcommand choices
        raise AssertionError(f"unknown management command: {options.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
