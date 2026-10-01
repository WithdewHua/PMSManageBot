"""Tests for Telegram ID reassignment in the blackjack domain."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.domains.blackjack import models as blackjack_models
from app.domains.blackjack.config import (
    ENTRY_FINISHED,
    ENTRY_PLAYING,
    TOURNAMENT_REGISTERING,
    TOURNAMENT_RUNNING,
    TOURNAMENT_SETTLED,
)
from app.domains.blackjack.repository import (
    REASSIGNED_TG_ID_COLUMNS,
    check_tg_id_reassign_tx,
    reassign_tg_id_tx,
)
from app.domains.blackjack.repository.wallet import move_tournament_wallet_tx
from app.domains.identity.models import Statistics
from tests.conftest import next_id


def _create_hand(
    session: Session,
    tg_id: int,
    status: int = 3,
    bet_credits: int = 10,
) -> blackjack_models.BlackjackHand:
    hand = blackjack_models.BlackjackHand(
        id=next_id(),
        tg_id=tg_id,
        status=status,
        bet_credits=bet_credits,
        doubled=0,
        deck_seed="test_deck_seed",
        next_card_index=0,
        player_cards="[]",
        dealer_cards="[]",
        blackjack_payout=1.5,
        dealer_hits_soft_17=1,
        hand_timeout_minutes=5,
        surrender_enabled=1,
        created_at_ms=1000000,
    )
    session.add(hand)
    session.flush()
    return hand


def _create_tournament(
    session: Session,
    status: int = TOURNAMENT_SETTLED,
    created_by: int | None = None,
) -> blackjack_models.BlackjackTournament:
    tournament = blackjack_models.BlackjackTournament(
        id=next_id(),
        title="Test Tournament",
        status=status,
        buy_in_credits=20,
        starting_chips=1000,
        total_hands=10,
        min_bet_chips=10,
        max_bet_chips=100,
        bet_step_chips=10,
        min_entrants=2,
        max_entrants=10,
        entrant_count=2,
        rake_bp=0,
        seeded_prize_credits=0.0,
        payout_structure="[]",
        dealer_hits_soft_17=1,
        blackjack_payout=1.5,
        surrender_enabled=1,
        hand_timeout_minutes=5,
        register_deadline_ms=1000000,
        play_deadline_ms=2000000,
        created_by=created_by,
    )
    session.add(tournament)
    session.flush()
    return tournament


def _create_entry(
    session: Session,
    tournament_id: int,
    tg_id: int,
    status: int = ENTRY_FINISHED,
) -> blackjack_models.BlackjackTournamentEntry:
    entry = blackjack_models.BlackjackTournamentEntry(
        id=next_id(),
        tournament_id=tournament_id,
        tg_id=tg_id,
        chips=1000,
        hands_played=10,
        status=status,
        wallet_paid_credits=0.0,
        credits_paid_credits=20.0,
        registered_at_ms=1000000,
    )
    session.add(entry)
    session.flush()
    return entry


def _create_cashback(
    session: Session,
    tg_id: int,
    week_start_ms: int,
) -> blackjack_models.BlackjackWeeklyCashback:
    cashback = blackjack_models.BlackjackWeeklyCashback(
        tg_id=tg_id,
        week_start_ms=week_start_ms,
        net_change=-100.0,
        cashback_credits=10.0,
        created_at_ms=week_start_ms + 1000,
    )
    session.add(cashback)
    session.flush()
    return cashback


def test_reassigned_tg_id_columns_and_model_info():
    """Verify metadata markings and exported columns match spec."""
    expected_columns = (
        "blackjack_hand.tg_id",
        "blackjack_tournament.created_by",
        "blackjack_tournament_entry.tg_id",
        "blackjack_weekly_cashback.tg_id",
    )
    assert REASSIGNED_TG_ID_COLUMNS == expected_columns

    assert blackjack_models.BlackjackHand.tg_id.info.get("tg_id") == "user"
    assert blackjack_models.BlackjackTournament.created_by.info.get("tg_id") == "admin"
    assert blackjack_models.BlackjackTournamentEntry.tg_id.info.get("tg_id") == "user"
    assert blackjack_models.BlackjackWeeklyCashback.tg_id.info.get("tg_id") == "user"


def test_check_reassign_no_issues(session_env):
    """Old user with completed hands and settled tournaments has no issues."""
    old_tg_id = 1001
    new_tg_id = 2002

    with get_session() as session:
        session.add(Statistics(tg_id=old_tg_id))
        session.add(Statistics(tg_id=new_tg_id))

        _create_hand(session, old_tg_id, status=3)
        _create_hand(session, old_tg_id, status=4)

        t1 = _create_tournament(session, status=TOURNAMENT_SETTLED)
        t2 = _create_tournament(session, status=TOURNAMENT_SETTLED)
        _create_entry(session, t1.id, old_tg_id)
        _create_entry(session, t2.id, new_tg_id)

        _create_cashback(session, old_tg_id, week_start_ms=1700000000000)
        _create_cashback(session, new_tg_id, week_start_ms=1700604800000)

        issues = check_tg_id_reassign_tx(session, old_tg_id, new_tg_id)
        assert issues == []


def test_check_reassign_unfinished_hands(session_env):
    """Reject old user unfinished hands (status 1 or 2)."""
    old_tg_id = 1001
    new_tg_id = 2002

    with get_session() as session:
        session.add(Statistics(tg_id=old_tg_id))
        session.add(Statistics(tg_id=new_tg_id))

        hand1 = _create_hand(session, old_tg_id, status=1)
        hand2 = _create_hand(session, old_tg_id, status=2)

        issues = check_tg_id_reassign_tx(session, old_tg_id, new_tg_id)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.kind == "in_flight"
        assert issue.domain == "blackjack"
        assert "unfinished" in issue.description
        assert str(hand1.id) in issue.record_ids
        assert str(hand2.id) in issue.record_ids


def test_check_reassign_active_tournaments(session_env):
    """Reject old user registered in registering (status 1) or running (status 2) tournaments."""
    old_tg_id = 1001
    new_tg_id = 2002

    with get_session() as session:
        session.add(Statistics(tg_id=old_tg_id))
        session.add(Statistics(tg_id=new_tg_id))

        t_reg = _create_tournament(session, status=TOURNAMENT_REGISTERING)
        _create_entry(session, t_reg.id, old_tg_id, status=ENTRY_PLAYING)

        t_run = _create_tournament(session, status=TOURNAMENT_RUNNING)
        _create_entry(session, t_run.id, old_tg_id, status=ENTRY_FINISHED)

        # Settled tournament should not cause in_flight issue
        t_set = _create_tournament(session, status=TOURNAMENT_SETTLED)
        _create_entry(session, t_set.id, old_tg_id, status=ENTRY_FINISHED)

        issues = check_tg_id_reassign_tx(session, old_tg_id, new_tg_id)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.kind == "in_flight"
        assert issue.domain == "blackjack"
        assert "active or registering" in issue.description
        assert str(t_reg.id) in issue.record_ids
        assert str(t_run.id) in issue.record_ids
        assert str(t_set.id) not in issue.record_ids


def test_check_reassign_same_tournament_conflict(session_env):
    """Reject when both old and new identities have registered for the same tournament."""
    old_tg_id = 1001
    new_tg_id = 2002

    with get_session() as session:
        session.add(Statistics(tg_id=old_tg_id))
        session.add(Statistics(tg_id=new_tg_id))

        t = _create_tournament(session, status=TOURNAMENT_SETTLED)
        _create_entry(session, t.id, old_tg_id)
        _create_entry(session, t.id, new_tg_id)

        issues = check_tg_id_reassign_tx(session, old_tg_id, new_tg_id)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.kind == "conflict"
        assert issue.domain == "blackjack"
        assert "same tournament" in issue.description
        assert str(t.id) in issue.record_ids


def test_check_reassign_same_weekly_cashback_conflict(session_env):
    """Reject when both old and new identities have cashback for the same week."""
    old_tg_id = 1001
    new_tg_id = 2002
    week_start = 1700000000000

    with get_session() as session:
        session.add(Statistics(tg_id=old_tg_id))
        session.add(Statistics(tg_id=new_tg_id))

        _create_cashback(session, old_tg_id, week_start_ms=week_start)
        _create_cashback(session, new_tg_id, week_start_ms=week_start)

        issues = check_tg_id_reassign_tx(session, old_tg_id, new_tg_id)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.kind == "conflict"
        assert issue.domain == "blackjack"
        assert "same week" in issue.description
        assert str(week_start) in issue.record_ids


def test_check_reassign_collects_all_issues(session_env):
    """Verify that all issues are collected together rather than stopping at the first."""
    old_tg_id = 1001
    new_tg_id = 2002
    week_start = 1700000000000

    with get_session() as session:
        session.add(Statistics(tg_id=old_tg_id))
        session.add(Statistics(tg_id=new_tg_id))

        # 1. Unfinished hand
        hand = _create_hand(session, old_tg_id, status=1)

        # 2. Running tournament
        t_active = _create_tournament(session, status=TOURNAMENT_RUNNING)
        _create_entry(session, t_active.id, old_tg_id)

        # 3. Same tournament conflict
        t_conflict = _create_tournament(session, status=TOURNAMENT_SETTLED)
        _create_entry(session, t_conflict.id, old_tg_id)
        _create_entry(session, t_conflict.id, new_tg_id)

        # 4. Same week cashback conflict
        _create_cashback(session, old_tg_id, week_start_ms=week_start)
        _create_cashback(session, new_tg_id, week_start_ms=week_start)

        issues = check_tg_id_reassign_tx(session, old_tg_id, new_tg_id)
        assert len(issues) == 4

        kinds = [iss.kind for iss in issues]
        assert kinds.count("in_flight") == 2
        assert kinds.count("conflict") == 2

        record_ids_all = [r_id for iss in issues for r_id in iss.record_ids]
        assert str(hand.id) in record_ids_all
        assert str(t_active.id) in record_ids_all
        assert str(t_conflict.id) in record_ids_all
        assert str(week_start) in record_ids_all


def test_reassign_tg_id_tx_records_and_balances(session_env):
    """Verify that records are reassigned and balances/counters are summed."""
    old_tg_id = 1001
    new_tg_id = 2002

    with get_session() as session:
        session.add(
            Statistics(
                tg_id=old_tg_id,
                tournament_wallet_credits=50.25,
                blackjack_lose_streak=3,
                blackjack_hands_since_freespin=14,
            )
        )
        session.add(
            Statistics(
                tg_id=new_tg_id,
                tournament_wallet_credits=20.50,
                blackjack_lose_streak=2,
                blackjack_hands_since_freespin=6,
            )
        )

        hand = _create_hand(session, old_tg_id, status=3)
        t_created = _create_tournament(
            session, status=TOURNAMENT_SETTLED, created_by=old_tg_id
        )
        t_entry = _create_tournament(session, status=TOURNAMENT_SETTLED)
        entry = _create_entry(session, t_entry.id, old_tg_id)
        cashback = _create_cashback(session, old_tg_id, week_start_ms=1700000000000)

        counts = reassign_tg_id_tx(session, old_tg_id, new_tg_id)

        assert counts == {
            "blackjack_hand.tg_id": 1,
            "blackjack_tournament.created_by": 1,
            "blackjack_tournament_entry.tg_id": 1,
            "blackjack_weekly_cashback.tg_id": 1,
            "statistics.tournament_wallet_credits": 1,
            "statistics.blackjack_lose_streak": 1,
            "statistics.blackjack_hands_since_freespin": 1,
        }

        # Check records reassigned
        session.refresh(hand)
        assert hand.tg_id == new_tg_id

        session.refresh(t_created)
        assert t_created.created_by == new_tg_id

        session.refresh(entry)
        assert entry.tg_id == new_tg_id

        session.refresh(cashback)
        assert cashback.tg_id == new_tg_id

        # Check balances and counters
        new_stats = session.get(Statistics, new_tg_id)
        assert new_stats.tournament_wallet_credits == pytest.approx(70.75)
        assert new_stats.blackjack_lose_streak == 5
        assert new_stats.blackjack_hands_since_freespin == 20

        old_stats = session.get(Statistics, old_tg_id)
        assert old_stats.tournament_wallet_credits == 0.0
        assert old_stats.blackjack_lose_streak == 0
        assert old_stats.blackjack_hands_since_freespin == 0


def test_reassign_tg_id_tx_no_commit_caller_controls_transaction(session_env):
    """Verify that reassign_tg_id_tx does not commit and rolls back with the caller."""
    old_tg_id = 1001
    new_tg_id = 2002

    with get_session() as session:
        session.add(
            Statistics(
                tg_id=old_tg_id,
                tournament_wallet_credits=10.0,
                blackjack_lose_streak=1,
                blackjack_hands_since_freespin=2,
            )
        )
        session.add(
            Statistics(
                tg_id=new_tg_id,
                tournament_wallet_credits=5.0,
                blackjack_lose_streak=0,
                blackjack_hands_since_freespin=0,
            )
        )
        hand = _create_hand(session, old_tg_id, status=3)
        hand_id = hand.id
        session.commit()

    with get_session() as session:
        reassign_tg_id_tx(session, old_tg_id, new_tg_id)
        session.rollback()

    # After rollback, old records and balances must remain untouched
    with get_session() as session:
        refreshed_hand = session.get(blackjack_models.BlackjackHand, hand_id)
        assert refreshed_hand.tg_id == old_tg_id

        old_stats = session.get(Statistics, old_tg_id)
        assert old_stats.tournament_wallet_credits == 10.0
        assert old_stats.blackjack_lose_streak == 1
        assert old_stats.blackjack_hands_since_freespin == 2

        new_stats = session.get(Statistics, new_tg_id)
        assert new_stats.tournament_wallet_credits == 5.0
        assert new_stats.blackjack_lose_streak == 0
        assert new_stats.blackjack_hands_since_freespin == 0


def test_reassign_tg_id_tx_with_zero_balances(session_env):
    """Verify reassign_tg_id_tx handles zero balances cleanly without raising errors."""
    old_tg_id = 1001
    new_tg_id = 2002

    with get_session() as session:
        session.add(
            Statistics(
                tg_id=old_tg_id,
                tournament_wallet_credits=0.0,
                blackjack_lose_streak=0,
                blackjack_hands_since_freespin=0,
            )
        )
        session.add(
            Statistics(
                tg_id=new_tg_id,
                tournament_wallet_credits=0.0,
                blackjack_lose_streak=0,
                blackjack_hands_since_freespin=0,
            )
        )
        session.flush()

        counts = reassign_tg_id_tx(session, old_tg_id, new_tg_id)
        assert counts == {
            "blackjack_hand.tg_id": 0,
            "blackjack_tournament.created_by": 0,
            "blackjack_tournament_entry.tg_id": 0,
            "blackjack_weekly_cashback.tg_id": 0,
            "statistics.tournament_wallet_credits": 0,
            "statistics.blackjack_lose_streak": 0,
            "statistics.blackjack_hands_since_freespin": 0,
        }

        new_stats = session.get(Statistics, new_tg_id)
        assert new_stats.tournament_wallet_credits == 0.0
        assert new_stats.blackjack_lose_streak == 0
        assert new_stats.blackjack_hands_since_freespin == 0


def test_raw_wallet_precision_preserved_no_loss(session_env):
    """Verify raw float tournament wallet credits are preserved without rounding loss."""
    old_tg_id = 3001
    new_tg_id = 3002
    raw_old_wallet = 12.345678
    raw_new_wallet = 5.123456
    expected_sum = raw_old_wallet + raw_new_wallet

    with get_session() as session:
        session.add(
            Statistics(
                tg_id=old_tg_id,
                tournament_wallet_credits=raw_old_wallet,
                blackjack_lose_streak=0,
                blackjack_hands_since_freespin=0,
            )
        )
        session.add(
            Statistics(
                tg_id=new_tg_id,
                tournament_wallet_credits=raw_new_wallet,
                blackjack_lose_streak=0,
                blackjack_hands_since_freespin=0,
            )
        )
        session.flush()

        counts = reassign_tg_id_tx(session, old_tg_id, new_tg_id)
        assert counts["statistics.tournament_wallet_credits"] == 1

        new_stats = session.get(Statistics, new_tg_id)
        old_stats = session.get(Statistics, old_tg_id)

        # Must not be rounded to 2 decimal places (12.35 + 5.12 = 17.47)
        assert new_stats.tournament_wallet_credits == pytest.approx(
            expected_sum, abs=1e-6
        )
        assert old_stats.tournament_wallet_credits == pytest.approx(0.0, abs=1e-6)


def test_zero_counters_and_delta_behavior(session_env):
    """Verify zero counters leave target untouched and return 0 in counts."""
    old_tg_id = 4001
    new_tg_id = 4002

    with get_session() as session:
        session.add(
            Statistics(
                tg_id=old_tg_id,
                tournament_wallet_credits=10.0,
                blackjack_lose_streak=0,
                blackjack_hands_since_freespin=0,
            )
        )
        session.add(
            Statistics(
                tg_id=new_tg_id,
                tournament_wallet_credits=5.0,
                blackjack_lose_streak=3,
                blackjack_hands_since_freespin=8,
            )
        )
        session.flush()

        counts = reassign_tg_id_tx(session, old_tg_id, new_tg_id)
        assert counts["statistics.tournament_wallet_credits"] == 1
        assert counts["statistics.blackjack_lose_streak"] == 0
        assert counts["statistics.blackjack_hands_since_freespin"] == 0

        new_stats = session.get(Statistics, new_tg_id)
        assert new_stats.blackjack_lose_streak == 3
        assert new_stats.blackjack_hands_since_freespin == 8
        assert new_stats.tournament_wallet_credits == pytest.approx(15.0)


def test_move_tournament_wallet_tx_direct(session_env):
    """Directly test move_tournament_wallet_tx delta updates and return value."""
    old_tg_id = 5001
    new_tg_id = 5002

    with get_session() as session:
        session.add(
            Statistics(
                tg_id=old_tg_id,
                tournament_wallet_credits=25.555,
                blackjack_lose_streak=4,
                blackjack_hands_since_freespin=7,
            )
        )
        session.add(
            Statistics(
                tg_id=new_tg_id,
                tournament_wallet_credits=10.111,
                blackjack_lose_streak=1,
                blackjack_hands_since_freespin=2,
            )
        )
        session.flush()

        moved = move_tournament_wallet_tx(session, old_tg_id, new_tg_id)
        assert moved == pytest.approx(25.555)

        session.flush()
        new_stats = session.get(Statistics, new_tg_id)
        old_stats = session.get(Statistics, old_tg_id)

        assert new_stats.tournament_wallet_credits == pytest.approx(35.666)
        assert new_stats.blackjack_lose_streak == 5
        assert new_stats.blackjack_hands_since_freespin == 9

        assert old_stats.tournament_wallet_credits == pytest.approx(0.0)
        assert old_stats.blackjack_lose_streak == 0
        assert old_stats.blackjack_hands_since_freespin == 0

        # Same ID move returns 0.0
        assert move_tournament_wallet_tx(session, new_tg_id, new_tg_id) == 0.0


def test_no_session_commit_or_close(session_env, monkeypatch):
    """Verify that reassign operations never invoke session.commit or session.close."""
    old_tg_id = 6001
    new_tg_id = 6002

    with get_session() as session:
        session.add(Statistics(tg_id=old_tg_id, tournament_wallet_credits=10.0))
        session.add(Statistics(tg_id=new_tg_id, tournament_wallet_credits=5.0))
        session.flush()

        committed = False
        closed = False

        original_commit = session.commit
        original_close = session.close

        def _fail_commit(*args, **kwargs):
            nonlocal committed
            committed = True
            raise AssertionError("session.commit() was illegally called")

        def _fail_close(*args, **kwargs):
            nonlocal closed
            closed = True
            raise AssertionError("session.close() was illegally called")

        monkeypatch.setattr(session, "commit", _fail_commit)
        monkeypatch.setattr(session, "close", _fail_close)

        issues = check_tg_id_reassign_tx(session, old_tg_id, new_tg_id)
        assert issues == []
        assert not committed
        assert not closed

        counts = reassign_tg_id_tx(session, old_tg_id, new_tg_id)
        assert counts["statistics.tournament_wallet_credits"] == 1
        assert not committed
        assert not closed

        # Restore so context manager cleanup succeeds
        monkeypatch.setattr(session, "commit", original_commit)
        monkeypatch.setattr(session, "close", original_close)


def test_flush_preserves_unflushed_donation_updates(session_env):
    """Verify that session.flush() before expire preserves prior donation modifications."""
    old_tg_id = 7001
    new_tg_id = 7002

    with get_session() as session:
        session.add(
            Statistics(
                tg_id=old_tg_id,
                donation=100.0,
                tournament_wallet_credits=20.0,
            )
        )
        new_stats = Statistics(
            tg_id=new_tg_id,
            donation=50.0,
            tournament_wallet_credits=10.0,
        )
        session.add(new_stats)
        session.flush()

        # Simulate donation domain having run earlier in the same transaction
        # and modified new_stats.donation in the active session without flushing:
        new_stats.donation = 150.0

        # Now reassign blackjack; blackjack MUST flush before expire so 150.0 is not lost
        reassign_tg_id_tx(session, old_tg_id, new_tg_id)

        # Inspect new_stats after reassign
        reloaded_new = session.get(Statistics, new_tg_id)
        assert reloaded_new.donation == pytest.approx(150.0)
        assert reloaded_new.tournament_wallet_credits == pytest.approx(30.0)
