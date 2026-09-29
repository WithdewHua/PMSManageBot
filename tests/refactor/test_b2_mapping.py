"""B2 route, schema, and authentication mapping coverage."""

import tomllib

from scripts.refactor.inventory import ROOT, SOURCE, coverage, inventory

MAPPING = ROOT / "scripts/refactor/mapping.toml"


def _records() -> dict[str, dict]:
    with MAPPING.open("rb") as stream:
        return {record["id"]: record for record in tomllib.load(stream)["items"]}


def test_b2_router_and_schema_units_have_reviewed_destinations() -> None:
    records = _records()
    paths = [
        SOURCE / "webapp" / "routers",
        SOURCE / "webapp" / "schemas",
        SOURCE / "webapp" / "auth.py",
        SOURCE / "webapp" / "middlewares.py",
        SOURCE / "handlers",
    ]
    # Flatten the two directory iterators for the inventory API.
    items = inventory(
        [candidate for path in paths for candidate in path.rglob("*.py")], root=ROOT
    )
    result = coverage(items, MAPPING)
    assert result["missing"] == []
    assert result["todo"] == []
    assert result["invalid"] == []
    assert records["app.webapp.auth:get_telegram_user"]["target"] == (
        "app.transport.http.auth"
    )
    assert records["app.webapp.middlewares:require_telegram_auth"]["target"] == (
        "app.transport.http.auth"
    )
    assert records["app.webapp.schemas.user:TelegramUser"]["target"] == (
        "app.transport.http.schemas"
    )
    assert records["app.webapp.schemas.user:BaseResponse"]["target"] == (
        "app.transport.http.schemas"
    )
    assert records["app.handlers.user:exchange"]["target"] == (
        "app.domains.invitation.bot"
    )
    assert records["app.handlers.status:set_register"]["target"] == (
        "app.domains.accounts.bot"
    )


def test_blackjack_route_embedded_jobs_and_notifications_are_domain_roles() -> None:
    records = _records()
    destinations = {
        "app.webapp.routers.activities.blackjack": {
            "jobs.cash": (
                "_settle_blackjack_hand_on_timeout",
                "_schedule_blackjack_timeout",
                "restore_blackjack_timeouts",
                "sweep_expired_blackjack_hands_job",
                "notify_blackjack_jackpot_wins_job",
                "notify_blackjack_freespin_grants_job",
                "remind_blackjack_freespin_expiry_job",
                "blackjack_weekly_cashback_job",
            ),
            "notifications.cash": (
                "_get_group_chat_id",
                "_format_jackpot_win",
                "_fmt_credits",
            ),
        },
        "app.webapp.routers.activities.blackjack_tournament": {
            "jobs.tournament": (
                "_tick_registration_deadlines",
                "_tick_completion_reminders",
                "_tick_play_deadlines",
                "blackjack_tournament_tick_job",
                "auto_create_blackjack_tournament_job",
                "_schedule_tournament_hand_timeout",
            ),
            "notifications.tournament": (
                "_notify_enabled",
                "_group_chat_id",
                "_fmt_ts",
                "_send_many",
                "_format_created",
                "_format_started",
                "_format_reminder",
                "_format_result_dm",
                "len_or_dash",
                "_format_result_group",
                "_format_cancelled",
                "_broadcast_group",
                "notify_tournament_started",
            ),
        },
    }
    for source, groups in destinations.items():
        for role, names in groups.items():
            for name in names:
                assert records[f"{source}:{name}"]["target"] == (
                    f"app.domains.blackjack.{role}"
                )


def test_route_embedded_activity_roles_have_reviewed_targets() -> None:
    records = _records()
    roles = {
        "app.webapp.routers.activities.auction": {
            "jobs": {"finish_single_auction_job", "restore_auction_schedules"},
            "notifications": {
                "send_channel_auction_notification",
                "send_bid_notifications",
            },
        },
        "app.webapp.routers.activities.prediction": {
            "notifications": {
                "_get_group_chat_id",
                "notify_prediction_market_created",
                "notify_prediction_markets_closing_soon",
                "notify_prediction_market_resolved",
                "notify_prediction_user_settlement",
                "notify_prediction_bet_placed",
                "notify_prediction_submission_created",
                "notify_prediction_submission_reviewed",
            },
        },
        "app.webapp.routers.activities.treasure": {
            "jobs": {
                "_auto_create_next_treasure_issue_from",
                "schedule_auto_reopen_treasure_issue",
            },
            "notifications": {
                "_get_group_chat_id",
                "notify_treasure_issue_created",
                "notify_treasure_not_full_after_join",
                "notify_treasure_settled",
            },
        },
        "app.webapp.routers.gift_pack": {
            "jobs": {"scan_expired_gift_packs", "scan_gift_pack_start_dms"},
            "notifications": {
                "_format_rewards",
                "_format_time",
                "_notify_detached",
                "_pending_notifications",
                "notify_gift_pack_claim_failed",
                "notify_gift_pack_created",
                "notify_gift_pack_download_sync_failed",
                "notify_gift_pack_sold_out",
            },
        },
        "app.webapp.routers.vaultwarden": {
            "notifications": {"_notify_admins_vaultwarden_redeem"},
        },
    }
    for source, destinations in roles.items():
        domain = source.removeprefix("app.webapp.routers.activities.").removeprefix(
            "app.webapp.routers."
        )
        for role, names in destinations.items():
            for name in names:
                assert (
                    records[f"{source}:{name}"]["target"]
                    == f"app.domains.{domain}.{role}"
                )


def test_new_domain_interfaces_do_not_depend_on_legacy_webapp() -> None:
    import ast

    interfaces = {
        "router.py",
        "admin_router.py",
        "bot.py",
        "jobs.py",
        "notifications.py",
    }
    domain_root = SOURCE / "domains"
    for path in domain_root.rglob("*.py"):
        if (
            path.name not in interfaces
            and "/router/" not in path.as_posix()
            and "/jobs/" not in path.as_posix()
            and "/notifications/" not in path.as_posix()
        ):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.webapp"), path
            elif isinstance(node, ast.Import):
                assert all(
                    not alias.name.startswith("app.webapp") for alias in node.names
                ), path
