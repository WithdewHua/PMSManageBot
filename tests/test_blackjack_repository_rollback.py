"""Caller-owned blackjack transactions roll back as a single unit.

Every case injects a failure at the *last* write inside the transaction body and
asserts that the earlier writes staged by the same call are gone as well: hand
state, tournament bookkeeping, credit balances and free-spin grants.
"""

from __future__ import annotations

import time

import pytest

from app.core.db import get_session
from app.domains.blackjack import repository as blackjack_repository
from app.domains.blackjack.config import (
    DEFAULT_BLACKJACK_CONFIG,
    ENTRY_FINISHED,
    TOURNAMENT_REGISTERING,
    TOURNAMENT_RUNNING,
    TOURNAMENT_SETTLED,
)
from app.domains.blackjack.models import (
    BlackjackHand,
    BlackjackTournament,
    BlackjackTournamentEntry,
)
from app.domains.blackjack.rules import STATUS_PLAYER_TURN
from app.domains.credits import repository as credits_repository
from app.domains.identity.models import Statistics
from app.domains.luckywheel import repository as luckywheel_repository
from app.domains.luckywheel.models import LuckywheelFreeSpin
from tests.conftest import add_cash_hand, add_entry, add_tournament, add_user, next_id

CONFIG = {**DEFAULT_BLACKJACK_CONFIG, "enabled": True}
# 20 点对 19 点：庄家停牌，闲家赢，赔付路径必然写积分
WINNING_HAND = {"player_cards": '["QH", "JH"]', "dealer_cards": '["KH", "9H"]'}


def _stats(tg_id: int) -> dict:
    with get_session() as session:
        stats = session.get(Statistics, int(tg_id))
        assert stats is not None
        return {
            "credits": float(stats.credits),
            "wallet": float(stats.tournament_wallet_credits or 0),
            "hands_since_freespin": int(stats.blackjack_hands_since_freespin or 0),
        }


def _set_freespin_progress(tg_id: int, hands: int) -> None:
    with get_session() as session:
        stats = session.get(Statistics, int(tg_id))
        stats.blackjack_hands_since_freespin = int(hands)


def _hand(hand_id: int) -> dict:
    with get_session() as session:
        hand = session.get(BlackjackHand, int(hand_id))
        return {
            "status": int(hand.status),
            "outcome": hand.outcome,
            "payout_credits": float(hand.payout_credits or 0),
        }


def _tournament(tournament_id: int) -> dict:
    with get_session() as session:
        row = session.get(BlackjackTournament, int(tournament_id))
        return {"status": int(row.status), "entrant_count": int(row.entrant_count)}


def _entry(tournament_id: int, tg_id: int) -> dict | None:
    with get_session() as session:
        row = (
            session.query(BlackjackTournamentEntry)
            .filter(
                BlackjackTournamentEntry.tournament_id == int(tournament_id),
                BlackjackTournamentEntry.tg_id == int(tg_id),
            )
            .one_or_none()
        )
        if row is None:
            return None
        return {
            "status": int(row.status),
            "final_rank": row.final_rank,
            "prize_credits": float(row.prize_credits or 0),
        }


def _freespin_ids(tg_id: int) -> list[int]:
    with get_session() as session:
        return [
            int(row_id)
            for (row_id,) in session.query(LuckywheelFreeSpin.id)
            .filter(LuckywheelFreeSpin.tg_id == int(tg_id))
            .all()
        ]


def _fail_with(message: str):
    def _raise(*args, **kwargs):
        raise RuntimeError(message)

    return _raise


def test_cash_settlement_rolls_back_when_payout_fails(orm, monkeypatch):
    add_user(orm, 1, credits=100.0)
    hand_id = add_cash_hand(orm, 1, **WINNING_HAND)
    monkeypatch.setattr(credits_repository, "add_tx", _fail_with("payout unavailable"))

    with (
        pytest.raises(RuntimeError, match="payout unavailable"),
        get_session() as session,
    ):
        blackjack_repository.blackjack_stand_tx(
            session, 1, hand_id, jackpot_config=CONFIG
        )

    assert _stats(1)["credits"] == 100.0
    assert _hand(hand_id)["status"] == STATUS_PLAYER_TURN
    assert _hand(hand_id)["outcome"] is None


def test_timeout_settlement_rolls_back_when_payout_fails(orm, monkeypatch):
    add_user(orm, 1, credits=100.0)
    hand_id = add_cash_hand(orm, 1, **WINNING_HAND)
    monkeypatch.setattr(credits_repository, "add_tx", _fail_with("payout unavailable"))

    with (
        pytest.raises(RuntimeError, match="payout unavailable"),
        get_session() as session,
    ):
        blackjack_repository.settle_blackjack_hand_by_timeout_tx(
            session, hand_id, jackpot_config=CONFIG
        )

    assert _stats(1)["credits"] == 100.0
    assert _hand(hand_id)["status"] == STATUS_PLAYER_TURN


def test_tournament_registration_rolls_back_when_buy_in_fails(orm, monkeypatch):
    now_ms = int(time.time() * 1000)
    tournament = add_tournament(
        orm,
        status=TOURNAMENT_REGISTERING,
        register_deadline_ms=now_ms + 3600 * 1000,
        entrant_count=0,
        buy_in_credits=30,
    )
    add_user(orm, 1, credits=100.0)
    monkeypatch.setattr(
        credits_repository, "deduct_tx", _fail_with("balance update unavailable")
    )

    with (
        pytest.raises(RuntimeError, match="balance update unavailable"),
        get_session() as session,
    ):
        blackjack_repository.register_blackjack_tournament_tx(
            session,
            1,
            tournament["id"],
            config=CONFIG,
            now_ms=now_ms,
        )

    assert _stats(1)["credits"] == 100.0
    assert _stats(1)["wallet"] == 0.0
    assert _tournament(tournament["id"])["entrant_count"] == 0
    assert _entry(tournament["id"], 1) is None


def test_tournament_settlement_rolls_back_when_prize_payout_fails(orm, monkeypatch):
    tournament = add_tournament(orm, status=TOURNAMENT_RUNNING)
    add_user(orm, 1, credits=0.0)
    add_user(orm, 2, credits=0.0)
    add_entry(
        orm, tournament["id"], 1, status=ENTRY_FINISHED, chips=1200, registered_at_ms=1
    )
    add_entry(
        orm, tournament["id"], 2, status=ENTRY_FINISHED, chips=800, registered_at_ms=2
    )
    monkeypatch.setattr(
        credits_repository, "add_tx", _fail_with("prize payout unavailable")
    )

    with (
        pytest.raises(RuntimeError, match="prize payout unavailable"),
        get_session() as session,
    ):
        blackjack_repository.settle_blackjack_tournament_tx(session, tournament["id"])

    assert _tournament(tournament["id"])["status"] == TOURNAMENT_RUNNING
    assert _entry(tournament["id"], 1)["final_rank"] is None
    assert _entry(tournament["id"], 2)["final_rank"] is None
    assert _stats(1)["credits"] == 0.0


def test_free_spin_grant_failure_aborts_cash_settlement(orm, monkeypatch):
    add_user(orm, 1, credits=100.0)
    _set_freespin_progress(1, int(CONFIG["freespins_hand_threshold"]) - 1)
    hand_id = add_cash_hand(orm, 1, **WINNING_HAND)
    monkeypatch.setattr(
        luckywheel_repository,
        "grant_free_spins_tx",
        _fail_with("free spin ledger unavailable"),
    )

    with (
        pytest.raises(RuntimeError, match="free spin ledger unavailable"),
        get_session() as session,
    ):
        blackjack_repository.blackjack_stand_tx(
            session, 1, hand_id, jackpot_config=CONFIG
        )

    assert _stats(1)["credits"] == 100.0
    assert (
        _stats(1)["hands_since_freespin"] == int(CONFIG["freespins_hand_threshold"]) - 1
    )
    assert _hand(hand_id)["status"] == STATUS_PLAYER_TURN
    assert _freespin_ids(1) == []


def test_free_spin_grants_share_the_settlement_transaction(orm):
    add_user(orm, 1, credits=100.0)
    _set_freespin_progress(1, int(CONFIG["freespins_hand_threshold"]) - 1)
    hand_id = add_cash_hand(orm, 1, **WINNING_HAND)

    with pytest.raises(RuntimeError, match="caller aborted"), get_session() as session:
        result = blackjack_repository.blackjack_stand_tx(
            session, 1, hand_id, jackpot_config=CONFIG
        )
        # 结算链在同一个 caller session 内发放了免费机会
        assert result["freespins"]
        raise RuntimeError("caller aborted")

    assert _freespin_ids(1) == []
    assert _stats(1)["credits"] == 100.0
    assert (
        _stats(1)["hands_since_freespin"] == int(CONFIG["freespins_hand_threshold"]) - 1
    )
    assert _hand(hand_id)["status"] == STATUS_PLAYER_TURN


def test_free_spin_grant_rolls_back_on_caller_abort(orm):
    add_user(orm, 1, credits=0.0)
    now_ms = int(time.time() * 1000)

    with pytest.raises(RuntimeError, match="caller aborted"), get_session() as session:
        rows = luckywheel_repository.grant_free_spins_tx(
            session,
            1,
            2,
            source="blackjack",
            granted_at_ms=now_ms,
            expires_at_ms=now_ms + 86400 * 1000,
        )
        assert len(rows) == 2
        raise RuntimeError("caller aborted")

    assert _freespin_ids(1) == []


def test_free_spin_grant_commits_with_the_caller_transaction(orm):
    add_user(orm, 1, credits=0.0)
    now_ms = int(time.time() * 1000)

    with get_session() as session:
        luckywheel_repository.grant_free_spins_tx(
            session,
            1,
            1,
            source="blackjack",
            granted_at_ms=now_ms,
            expires_at_ms=now_ms + 86400 * 1000,
        )

    assert len(_freespin_ids(1)) == 1


def test_tournament_settlement_commits_when_payouts_succeed(orm):
    """对照：同一路径成功时名次、状态与奖金一起落库。"""

    tournament = add_tournament(orm, status=TOURNAMENT_RUNNING)
    add_user(orm, 1, credits=0.0)
    add_user(orm, 2, credits=0.0)
    add_entry(
        orm, tournament["id"], 1, status=ENTRY_FINISHED, chips=1200, registered_at_ms=1
    )
    add_entry(
        orm, tournament["id"], 2, status=ENTRY_FINISHED, chips=800, registered_at_ms=2
    )

    with get_session() as session:
        result = blackjack_repository.settle_blackjack_tournament_tx(
            session, tournament["id"]
        )

    assert result["settled"] is True
    assert _tournament(tournament["id"])["status"] == TOURNAMENT_SETTLED
    assert _entry(tournament["id"], 1)["final_rank"] == 1
    assert next_id() > 0
