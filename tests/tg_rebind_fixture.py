"""End-to-end test fixtures driven by model metadata and encoded declarations."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import Base
from app.domains.tg_rebind.constants import ENCODED_TG_ID_LOCATIONS

DEFAULT_OLD_TG_ID = 101
DEFAULT_NEW_TG_ID = 202
DEFAULT_ADMIN_TG_ID = 9001

# Table insertion order respecting foreign key constraints
TABLE_INSERTION_ORDER: tuple[str, ...] = (
    # Parents with marked columns
    "auctions",
    "blackjack_tournament",
    "gift_pack",
    "prediction_market",
    "treasure_issue",
    "custom_lines",
    # Children referencing parents
    "auction_bids",
    "blackjack_tournament_entry",
    "gift_pack_user_state",
    "prediction_bet",
    "prediction_market_submission",
    "treasure_participation",
    "custom_line_settlement",
    "user_badges",
    # Remaining independent tables
    "blackjack_hand",
    "blackjack_weekly_cashback",
    "crypto_donation_orders",
    "donation_registrations",
    "emby_user",
    "invitation",
    "line_schedule",
    "luckywheel_free_spins",
    "overseerr",
    "plex_user",
    "vaultwarden_redeem_records",
    "watch_reward_settlement",
    "wheel_stats",
)


def _auction_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "title": "Auction 101",
        "description": "Test Auction",
        "starting_price": 10.0,
        "current_price": 10.0,
        "end_time": 2000,
        "created_by": old,
        "created_at": 1000,
        "is_active": 0,
        "winner_id": old,
        "bid_count": 1,
    }


def _auction_bids_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "auction_id": 101,
        "bidder_id": old,
        "bid_amount": 10.0,
        "bid_time": 1000,
    }


def _blackjack_tournament_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "title": "Tourney 101",
        "status": 3,  # TOURNAMENT_SETTLED (terminal)
        "buy_in_credits": 10,
        "starting_chips": 1000,
        "total_hands": 10,
        "min_bet_chips": 10,
        "max_bet_chips": 100,
        "bet_step_chips": 10,
        "min_entrants": 2,
        "max_entrants": 10,
        "entrant_count": 2,
        "rake_bp": 0,
        "seeded_prize_credits": 0.0,
        "payout_structure": "[]",
        "dealer_hits_soft_17": 1,
        "blackjack_payout": 1.5,
        "surrender_enabled": 1,
        "hand_timeout_minutes": 5,
        "register_deadline_ms": 1000,
        "play_deadline_ms": 2000,
        "created_by": old,
        "created_at": datetime.now(UTC),
    }


def _blackjack_tournament_entry_override(
    old: int, new: int, admin: int
) -> dict[str, Any]:
    return {
        "id": 101,
        "tournament_id": 101,
        "tg_id": old,
        "chips": 1000,
        "hands_played": 10,
        "status": 3,  # ENTRY_FINISHED (terminal)
        "wallet_paid_credits": 0.0,
        "credits_paid_credits": 10.0,
        "registered_at_ms": 1000,
    }


def _blackjack_hand_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "tg_id": old,
        "status": 3,  # Terminal settled hand
        "bet_credits": 10,
        "doubled": 0,
        "deck_seed": "deck_seed_101",
        "next_card_index": 0,
        "player_cards": "[]",
        "dealer_cards": "[]",
        "decisions_total": 0,
        "decisions_correct": 0,
        "rake_waived": 0,
        "rake_bp_on_profit": 0,
        "rake_jackpot_bp": 0,
        "blackjack_payout": 1.5,
        "dealer_hits_soft_17": 1,
        "hand_timeout_minutes": 5,
        "surrender_enabled": 1,
        "created_at_ms": 1000000,
        "created_at": datetime.now(UTC),
    }


def _blackjack_weekly_cashback_override(
    old: int, new: int, admin: int
) -> dict[str, Any]:
    return {
        "id": 101,
        "tg_id": old,
        "week_start_ms": 1700000000000,
        "net_change": -100.0,
        "cashback_credits": 10.0,
        "created_at_ms": 1700000001000,
    }


def _gift_pack_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "title": "Gift Pack 101",
        "rewards": "[]",
        "start_at": 1000,
        "end_at": 2000,
        "max_prompt_count": 3,
        "max_task_prompt_count": 2,
        "notify_audience_on_start": 0,
        "is_enabled": 1,
        "expiry_notified": 0,
        "created_by": old,
        "audience": json.dumps(
            [{"type": "user_list", "mode": "include", "tg_ids": [old, 9999, new, 8888]}]
        ),
        "claimed_count": 1,
        "created_at": 1000,
        "updated_at": 1000,
    }


def _gift_pack_user_state_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "pack_id": 101,
        "tg_id": old,
        "claimed_at": 1500,
        "prompt_count": 0,
        "task_prompt_count": 0,
    }


def _prediction_market_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "title": "Prediction Market 101",
        "status": 2,  # Resolved
        "real_yes_pool": 10,
        "real_no_pool": 10,
        "virtual_yes_pool": 0,
        "virtual_no_pool": 0,
        "fee_rate_bp": 0,
        "fee_burn_bp": 0,
        "fee_glory_bp": 0,
        "max_bet_per_user": 100,
        "total_fee_collected": 0,
        "fee_burned": 0,
        "fee_to_glory": 0,
        "created_by": old,
        "resolved_by": old,
        "resolved_at": 2000,
        "created_at": datetime.now(UTC),
    }


def _prediction_bet_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "market_id": 101,
        "tg_id": old,
        "option": 1,
        "amount": 10,
        "created_at": datetime.now(UTC),
    }


def _prediction_market_submission_override(
    old: int, new: int, admin: int
) -> dict[str, Any]:
    return {
        "id": 101,
        "title": "Submission 101",
        "betting_deadline": 2000,
        "status": 2,  # Approved
        "submitter_tg_id": old,
        "reviewed_by": old,
        "reviewed_at": 1500,
        "market_id": 101,
        "created_at": datetime.now(UTC),
    }


def _treasure_issue_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "title": "Treasure Issue 101",
        "prize_credits": 100,
        "total_credits_required": 100,
        "credits_per_share": 10,
        "total_shares": 10,
        "start_number": 1,
        "status": 2,  # Ended
        "shares_sold": 10,
        "winner_number": 5,
        "winner_tg_id": old,
        "created_by": old,
        "created_at": datetime.now(UTC),
    }


def _treasure_participation_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "issue_id": 101,
        "tg_id": old,
        "lucky_number": 5,
        "cost_credits": 10,
        "created_at_ms": 1000,
        "created_at": datetime.now(UTC),
    }


def _custom_lines_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "tg_id": old,
        "domain": "line101.test.com",
        "network_info": "direct",
        "traffic_type": "one_way",
        "is_permanent": 0,
        "status": "approved",
        "approved_by": old,
        "approved_at": 1000,
        "created_at": 1000,
        "updated_at": 1000,
    }


def _custom_line_settlement_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "line_id": 101,
        "tg_id": old,
        "domain": "line101.test.com",
        "year_month": "2026-04",
        "trigger": "monthly",
        "traffic_bytes": 1000,
        "credits": 10.0,
        "created_at": 1000,
    }


def _user_badges_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "tg_id": old,
        "badge_id": 1,
        "credits_cost": 10.0,
        "redeemed_at": 1000,
        "expires_at": 2000,
        "is_active": 1,
    }


def _crypto_donation_orders_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "user_id": old,
        "order_id": "CRYPTO_ORDER_101",
        "crypto_type": "USDT",
        "amount": 10.0,
        "status": 2,  # Completed
        "created_at": "2026-04-01",
    }


def _donation_registrations_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "user_id": old,
        "payment_method": "alipay",
        "amount": 20.0,
        "status": "approved",
        "processed_by": old,
        "processed_at": "2026-04-01",
        "created_at": "2026-04-01",
        "is_donation_registration": 1,
    }


def _emby_user_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "emby_username": f"emby_user_{old}",
        "emby_id": f"emby_id_{old}",
        "tg_id": old,
        "emby_is_unlock": 1,
        "emby_watched_time": 10.0,
        "emby_credits": 0.0,
        "is_premium": 0,
        "line_schedule_unlocked": 0,
        "download_unlocked": 0,
        "premium_traffic_debt_bytes": 0,
    }


def _invitation_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "code": f"INV_CODE_{old}",
        "owner": old,
        "is_used": 1,
        "is_privileged": 0,
        "used_by": f"credits_by_{old}",
    }


def _line_schedule_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "tg_id": old,
        "service": "plex",
        "line": "line_primary",
        "days_of_week": "1,2,3,4,5,6,7",
        "start_time": "00:00",
        "end_time": "23:59",
        "priority": 1,
        "is_enabled": 1,
        "created_at": 1000,
        "updated_at": 1000,
    }


def _luckywheel_free_spins_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "tg_id": old,
        "source": "blackjack",
        "cost_credits_snapshot": 0.0,
        "wheel_stats_source": "blackjack_free",
        "granted_at_ms": 1000,
        "expires_at_ms": 2000,
    }


def _overseerr_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "user_id": 101,
        "tg_id": old,
        "user_email": f"overseerr_{old}@example.com",
    }


def _plex_user_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "plex_id": 101,
        "tg_id": old,
        "credits": 0.0,
        "plex_email": f"plex_{old}@example.com",
        "plex_username": f"plex_user_{old}",
        "all_lib": 0,
        "watched_time": 10.0,
        "is_premium": 0,
        "line_schedule_unlocked": 0,
        "sync_unlocked": 0,
        "premium_traffic_debt_bytes": 0,
    }


def _vaultwarden_redeem_records_override(
    old: int, new: int, admin: int
) -> dict[str, Any]:
    return {
        "id": 101,
        "tg_id": old,
        "email": f"vault_{old}@example.com",
        "credits_cost": 10.0,
        "redeem_date": "2026-04-01",
        "created_at": 1000,
    }


def _watch_reward_settlement_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "service": "plex",
        "account_key": f"acc_{old}",
        "settlement_date": "2026-04-01",
        "tg_id": old,
        "credits_delta": 10.0,
        "premium_charge": 0.0,
        "inviter_tg_id": old,
        "inviter_bonus": 2.0,
        "created_at": 1000,
    }


def _wheel_stats_override(old: int, new: int, admin: int) -> dict[str, Any]:
    return {
        "id": 101,
        "tg_id": old,
        "item_name": "credits_10",
        "cost_credits": 10.0,
        "credits_change": 10.0,
        "timestamp": 1000,
        "date": "2026-04-01",
        "source": "paid",
    }


TABLE_OVERRIDES: dict[str, Callable[[int, int, int], dict[str, Any]]] = {
    "auction_bids": _auction_bids_override,
    "auctions": _auction_override,
    "blackjack_hand": _blackjack_hand_override,
    "blackjack_tournament": _blackjack_tournament_override,
    "blackjack_tournament_entry": _blackjack_tournament_entry_override,
    "blackjack_weekly_cashback": _blackjack_weekly_cashback_override,
    "crypto_donation_orders": _crypto_donation_orders_override,
    "custom_line_settlement": _custom_line_settlement_override,
    "custom_lines": _custom_lines_override,
    "donation_registrations": _donation_registrations_override,
    "emby_user": _emby_user_override,
    "gift_pack": _gift_pack_override,
    "gift_pack_user_state": _gift_pack_user_state_override,
    "invitation": _invitation_override,
    "line_schedule": _line_schedule_override,
    "luckywheel_free_spins": _luckywheel_free_spins_override,
    "overseerr": _overseerr_override,
    "plex_user": _plex_user_override,
    "prediction_bet": _prediction_bet_override,
    "prediction_market": _prediction_market_override,
    "prediction_market_submission": _prediction_market_submission_override,
    "treasure_issue": _treasure_issue_override,
    "treasure_participation": _treasure_participation_override,
    "user_badges": _user_badges_override,
    "vaultwarden_redeem_records": _vaultwarden_redeem_records_override,
    "watch_reward_settlement": _watch_reward_settlement_override,
    "wheel_stats": _wheel_stats_override,
}


def _marked_columns_for_table(table) -> list[str]:
    return [
        col.name
        for col in table.columns
        if isinstance(col.info, dict) and col.info.get("tg_id") in ("user", "admin")
    ]


def seed_rebind_fixtures(
    session: Session,
    *,
    old_tg_id: int = DEFAULT_OLD_TG_ID,
    new_tg_id: int = DEFAULT_NEW_TG_ID,
    admin_tg_id: int = DEFAULT_ADMIN_TG_ID,
    seed_new_stats: bool = False,
    old_credits: float = 120.0,
    new_credits: float = 70.0,
    old_donation: float = 50.0,
    new_donation: float = 15.0,
    old_wallet: float = 30.0,
    new_wallet: float = 20.0,
    old_lose_streak: int = 3,
    new_lose_streak: int = 1,
    old_freespin_progress: int = 5,
    new_freespin_progress: int = 2,
) -> None:
    """Dynamically seed ONE row per marked table driven by column metadata."""
    # 1. Ensure all marked tables have a valid override (fail loudly on unmapped tables)
    for table in Base.metadata.tables.values():
        marked_cols = _marked_columns_for_table(table)
        if (
            marked_cols
            and table.name != "statistics"
            and table.name not in TABLE_OVERRIDES
        ):
            raise AssertionError(
                f"New table with marked tg_id column has no valid override: {table.name}"
            )

    # 2. Seed statistics prerequisites (including sentinel admin ID backing FKs)
    stat_table = Base.metadata.tables["statistics"]
    session.execute(
        stat_table.insert().values(
            tg_id=old_tg_id,
            credits=old_credits,
            donation=old_donation,
            tournament_wallet_credits=old_wallet,
            blackjack_lose_streak=old_lose_streak,
            blackjack_hands_since_freespin=old_freespin_progress,
        )
    )
    session.execute(
        stat_table.insert().values(
            tg_id=admin_tg_id,
            credits=0.0,
            donation=0.0,
            tournament_wallet_credits=0.0,
            blackjack_lose_streak=0,
            blackjack_hands_since_freespin=0,
        )
    )
    if seed_new_stats:
        session.execute(
            stat_table.insert().values(
                tg_id=new_tg_id,
                credits=new_credits,
                donation=new_donation,
                tournament_wallet_credits=new_wallet,
                blackjack_lose_streak=new_lose_streak,
                blackjack_hands_since_freespin=new_freespin_progress,
            )
        )

    # 3. Seed badge prerequisite for user_badges
    badge_table = Base.metadata.tables["badges"]
    session.execute(
        badge_table.insert().values(
            id=1,
            badge_type="fixture_badge_1",
            name="Fixture Badge",
            description="Fixture Description",
            icon_url="https://example.com/badge.svg",
            credits_cost=10.0,
            bonus_percentage=0.1,
            valid_days=30,
            is_enabled=1,
            created_at=1000,
            updated_at=1000,
        )
    )

    # 4. Seed all marked tables in dependency order
    for table_name in TABLE_INSERTION_ORDER:
        table = Base.metadata.tables[table_name]
        override_fn = TABLE_OVERRIDES[table_name]
        row_values = override_fn(old_tg_id, new_tg_id, admin_tg_id)

        # Dynamic guarantee: every marked column automatically defaults to old_tg_id
        for col_name in _marked_columns_for_table(table):
            if col_name not in row_values:
                row_values[col_name] = old_tg_id

        # Encoded location guarantee
        for location in ENCODED_TG_ID_LOCATIONS:
            if location.table == table_name:
                if location.column == "used_by" and location.prefix:
                    row_values[location.column] = f"{location.prefix}{old_tg_id}"
                elif location.column == "audience":
                    row_values[location.column] = json.dumps(
                        [
                            {
                                "type": "user_list",
                                "mode": "include",
                                "tg_ids": [old_tg_id, 9999, new_tg_id, 8888],
                            }
                        ]
                    )

        session.execute(table.insert().values(**row_values))

    session.flush()


def assert_no_old_tg_id_residues(
    session: Session, old_tg_id: int = DEFAULT_OLD_TG_ID
) -> None:
    """Assert no records, columns, or encoded entries still reference old_tg_id."""
    residues: list[str] = []

    for table in Base.metadata.tables.values():
        for col_name in _marked_columns_for_table(table):
            count = session.execute(
                text(f"SELECT count(*) FROM {table.name} WHERE {col_name} = :old_id"),
                {"old_id": old_tg_id},
            ).scalar_one()
            if count > 0:
                residues.append(f"{table.name}.{col_name}: {count} row(s)")

    # Check invitation.used_by
    inv_count = session.execute(
        text("SELECT count(*) FROM invitation WHERE used_by LIKE :pattern"),
        {"pattern": f"%{old_tg_id}%"},
    ).scalar_one()
    if inv_count > 0:
        residues.append(f"invitation.used_by: {inv_count} row(s)")

    # Check gift_pack.audience
    audiences = session.execute(
        text("SELECT id, audience FROM gift_pack WHERE audience IS NOT NULL")
    ).fetchall()
    for pack_id, aud in audiences:
        if str(old_tg_id) in str(aud):
            residues.append(f"gift_pack.audience (id={pack_id}): {aud}")

    assert residues == [], f"Found lingering old_tg_id residues: {residues}"


def get_all_marked_column_counts(
    session: Session, target_tg_id: int = DEFAULT_NEW_TG_ID
) -> dict[str, int]:
    """Return map of {table.column: count_of_target_id} across all marked columns."""
    counts: dict[str, int] = {}
    for table in Base.metadata.tables.values():
        for col_name in _marked_columns_for_table(table):
            count = session.execute(
                text(
                    f"SELECT count(*) FROM {table.name} WHERE {col_name} = :target_id"
                ),
                {"target_id": target_tg_id},
            ).scalar_one()
            counts[f"{table.name}.{col_name}"] = int(count)
    return counts
