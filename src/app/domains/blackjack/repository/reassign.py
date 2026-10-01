"""Blackjack domain Telegram ID reassignment operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import or_, select, update

from app.domains.blackjack import models as blackjack_models
from app.domains.blackjack.repository import wallet as blackjack_wallet
from app.domains.identity import models as identity_models
from app.domains.identity import types as identity_types

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

REASSIGNED_TG_ID_COLUMNS: tuple[str, ...] = (
    "blackjack_hand.tg_id",
    "blackjack_tournament.created_by",
    "blackjack_tournament_entry.tg_id",
    "blackjack_weekly_cashback.tg_id",
)

_wallet_repo = blackjack_wallet._BlackjackRepositoryWallet()


def check_tg_id_reassign_tx(
    session: Session, old_tg_id: int, new_tg_id: int
) -> list[identity_types.TgIdReassignIssue]:
    """Check for in-flight blackjack activities or conflicts between old and new identities."""
    issues: list[identity_types.TgIdReassignIssue] = []

    # 1. Reject OLD user unfinished hands (status not in (3, 4))
    unfinished_hands = (
        session.execute(
            select(blackjack_models.BlackjackHand.id)
            .where(
                blackjack_models.BlackjackHand.tg_id == old_tg_id,
                or_(
                    blackjack_models.BlackjackHand.status.notin_((3, 4)),
                    blackjack_models.BlackjackHand.status.is_(None),
                ),
            )
            .order_by(blackjack_models.BlackjackHand.id.asc())
        )
        .scalars()
        .all()
    )
    if unfinished_hands:
        issues.append(
            identity_types.TgIdReassignIssue(
                kind="in_flight",
                domain="blackjack",
                description="old ID has unfinished blackjack hands",
                record_ids=tuple(str(hid) for hid in unfinished_hands),
            )
        )

    # 2. Reject OLD user registered in registering or in-progress tournaments (status 1 or 2)
    in_flight_tournaments = (
        session.execute(
            select(blackjack_models.BlackjackTournament.id)
            .join(
                blackjack_models.BlackjackTournamentEntry,
                blackjack_models.BlackjackTournamentEntry.tournament_id
                == blackjack_models.BlackjackTournament.id,
            )
            .where(
                blackjack_models.BlackjackTournamentEntry.tg_id == old_tg_id,
                blackjack_models.BlackjackTournament.status.in_((1, 2)),
            )
            .order_by(blackjack_models.BlackjackTournament.id.asc())
        )
        .scalars()
        .all()
    )
    if in_flight_tournaments:
        issues.append(
            identity_types.TgIdReassignIssue(
                kind="in_flight",
                domain="blackjack",
                description="old ID is registered in active or registering tournaments",
                record_ids=tuple(str(tid) for tid in in_flight_tournaments),
            )
        )

    if old_tg_id != new_tg_id:
        # 3. Reject if both identities have entries in the same tournament
        old_tournaments = set(
            session.execute(
                select(blackjack_models.BlackjackTournamentEntry.tournament_id).where(
                    blackjack_models.BlackjackTournamentEntry.tg_id == old_tg_id
                )
            )
            .scalars()
            .all()
        )
        new_tournaments = set(
            session.execute(
                select(blackjack_models.BlackjackTournamentEntry.tournament_id).where(
                    blackjack_models.BlackjackTournamentEntry.tg_id == new_tg_id
                )
            )
            .scalars()
            .all()
        )
        common_tournaments = sorted(old_tournaments & new_tournaments)
        if common_tournaments:
            issues.append(
                identity_types.TgIdReassignIssue(
                    kind="conflict",
                    domain="blackjack",
                    description="both IDs have entries in the same tournament",
                    record_ids=tuple(str(tid) for tid in common_tournaments),
                )
            )

        # 4. Reject if both identities have weekly cashback records for the same week
        old_cashback_weeks = set(
            session.execute(
                select(blackjack_models.BlackjackWeeklyCashback.week_start_ms).where(
                    blackjack_models.BlackjackWeeklyCashback.tg_id == old_tg_id
                )
            )
            .scalars()
            .all()
        )
        new_cashback_weeks = set(
            session.execute(
                select(blackjack_models.BlackjackWeeklyCashback.week_start_ms).where(
                    blackjack_models.BlackjackWeeklyCashback.tg_id == new_tg_id
                )
            )
            .scalars()
            .all()
        )
        common_cashback_weeks = sorted(old_cashback_weeks & new_cashback_weeks)
        if common_cashback_weeks:
            issues.append(
                identity_types.TgIdReassignIssue(
                    kind="conflict",
                    domain="blackjack",
                    description="both IDs have weekly cashback records for the same week",
                    record_ids=tuple(str(w) for w in common_cashback_weeks),
                )
            )

    return issues


def reassign_tg_id_tx(
    session: Session, old_tg_id: int, new_tg_id: int
) -> dict[str, int]:
    """Reassign blackjack records and merge wallet balances and counters."""
    counts: dict[str, int] = {}

    res_hands = session.execute(
        update(blackjack_models.BlackjackHand)
        .where(blackjack_models.BlackjackHand.tg_id == old_tg_id)
        .values(tg_id=new_tg_id)
    )
    counts["blackjack_hand.tg_id"] = res_hands.rowcount

    res_tournaments = session.execute(
        update(blackjack_models.BlackjackTournament)
        .where(blackjack_models.BlackjackTournament.created_by == old_tg_id)
        .values(created_by=new_tg_id)
    )
    counts["blackjack_tournament.created_by"] = res_tournaments.rowcount

    res_entries = session.execute(
        update(blackjack_models.BlackjackTournamentEntry)
        .where(blackjack_models.BlackjackTournamentEntry.tg_id == old_tg_id)
        .values(tg_id=new_tg_id)
    )
    counts["blackjack_tournament_entry.tg_id"] = res_entries.rowcount

    res_cashback = session.execute(
        update(blackjack_models.BlackjackWeeklyCashback)
        .where(blackjack_models.BlackjackWeeklyCashback.tg_id == old_tg_id)
        .values(tg_id=new_tg_id)
    )
    counts["blackjack_weekly_cashback.tg_id"] = res_cashback.rowcount

    # Read delta indicators from source statistics before move
    old_stats = session.get(identity_models.Statistics, int(old_tg_id))
    wallet_delta = (
        float(old_stats.tournament_wallet_credits or 0.0) if old_stats else 0.0
    )
    streak_delta = int(old_stats.blackjack_lose_streak or 0) if old_stats else 0
    freespin_delta = (
        int(old_stats.blackjack_hands_since_freespin or 0) if old_stats else 0
    )

    # Move wallet balance and counters via delta updates under deterministic row locks
    _wallet_repo.move_tournament_wallet_tx(session, old_tg_id, new_tg_id)

    # MUST flush session before expire so prior modifications (e.g. donation) are not lost
    session.flush()

    for tid in (old_tg_id, new_tg_id):
        st = session.get(identity_models.Statistics, int(tid))
        if st is not None:
            session.expire(st)

    counts["statistics.tournament_wallet_credits"] = 1 if wallet_delta != 0.0 else 0
    counts["statistics.blackjack_lose_streak"] = 1 if streak_delta != 0 else 0
    counts["statistics.blackjack_hands_since_freespin"] = (
        1 if freespin_delta != 0 else 0
    )

    return counts


__all__ = [
    "REASSIGNED_TG_ID_COLUMNS",
    "check_tg_id_reassign_tx",
    "reassign_tg_id_tx",
]
