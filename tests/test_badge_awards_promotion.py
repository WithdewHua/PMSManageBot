"""Reward checks and source trigger matrix; no production I/O."""

import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core import events
from app.domains.badge_awards import service as awards
from app.domains.blackjack import service as blackjack
from app.domains.luckywheel import service as wheel
from app.domains.luckywheel.schemas import (
    LuckyWheelConfig,
    LuckyWheelItem,
    LuckyWheelSpinResult,
)
from app.domains.prediction import service as prediction
from app.domains.treasure import service as treasure
from app.subscriptions import register_all


@pytest.fixture
def mocked_checks(monkeypatch):
    monkeypatch.setattr(
        awards.badges_service,
        "get_badge_by_type",
        lambda kind: {"name": kind, "bonus_percentage": 0.18},
    )
    monkeypatch.setattr(awards.badges_service, "award_badge", lambda *args: True)
    monkeypatch.setattr(
        awards.blackjack_service,
        "get_blackjack_config_dict",
        lambda: {"badge_min_hands": 2000, "badge_min_accuracy": 80},
    )
    monkeypatch.setattr(
        awards.blackjack_service,
        "get_user_blackjack_stats",
        lambda tg_id: {"total_hands": 0, "accuracy": 0},
    )
    monkeypatch.setattr(awards.luckywheel_service, "count_badge_spins", lambda tg_id: 0)
    monkeypatch.setattr(awards.treasure_service, "count_badge_issues", lambda tg_id: 0)
    monkeypatch.setattr(awards.prediction_service, "count_badge_bets", lambda tg_id: 0)
    notify = AsyncMock()
    monkeypatch.setattr(awards.messaging, "send_message_by_url", notify)
    return notify


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "api,name,threshold",
    [
        (wheel, "count_badge_spins", 5000),
        (treasure, "count_badge_issues", 500),
        (prediction, "count_badge_bets", 500),
    ],
)
async def test_activity_threshold_and_idempotent_notification(
    monkeypatch, mocked_checks, api, name, threshold
):
    monkeypatch.setattr(api, name, lambda tg_id: threshold - 1)
    assert await awards.check_and_award_game_king_badge(42) is False
    monkeypatch.setattr(api, name, lambda tg_id: threshold)
    assert await awards.check_and_award_game_king_badge(42) is True
    assert mocked_checks.await_count == 1
    assert (
        mocked_checks.call_args.kwargs["text"]
        == "🎮 恭喜获得勋章！\n====================\n\n勋章名称：game_king\n有效期限：永久\n\n感谢您的热情参与！\n\n===================="
    )
    monkeypatch.setattr(awards.badges_service, "award_badge", lambda *args: False)
    assert await awards.check_and_award_game_king_badge(42) is False
    assert mocked_checks.await_count == 1


@pytest.mark.asyncio
async def test_blackjack_rounded_single_user_and_worker_thread(
    monkeypatch, mocked_checks
):
    main_thread = threading.get_ident()
    threads = []

    def stats(tg_id):
        threads.append(threading.get_ident())
        return {"total_hands": 2000, "accuracy": 80.0}

    monkeypatch.setattr(blackjack, "get_user_blackjack_stats", stats)
    assert await awards.check_and_award_game_king_badge(42) is True
    assert threads and threads[0] != main_thread


@pytest.mark.asyncio
async def test_failed_award_does_not_notify(monkeypatch, mocked_checks):
    monkeypatch.setattr(
        awards.donation_service,
        "list_badge_eligible_donors",
        lambda threshold, tg_id: [(42, 1688.01)],
    )

    def failed(*args):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(awards.badges_service, "award_badge", failed)
    assert await awards.check_and_award_supreme_contributor_badge(42) is False
    mocked_checks.assert_not_awaited()


@pytest.mark.parametrize(
    "action,settled,expected",
    [
        ("create_blackjack_hand", False, 0),
        ("create_blackjack_hand", True, 1),
        ("blackjack_hit", False, 0),
        ("blackjack_hit", True, 1),
        ("blackjack_stand", False, 1),
        ("blackjack_double", False, 1),
        ("blackjack_surrender", False, 1),
        ("settle_blackjack_hand_by_timeout", True, 0),
        ("sweep_timed_out_blackjack_hands", True, 0),
    ],
)
def test_cash_trigger_matrix(monkeypatch, action, settled, expected):
    received = []
    monkeypatch.setattr(events, "emit", received.append)
    monkeypatch.setattr(
        blackjack.blackjack_repository, action, lambda *args: {"settled": settled}
    )
    args = (
        (42,)
        if action
        in ("settle_blackjack_hand_by_timeout", "sweep_timed_out_blackjack_hands")
        else (42, 1)
    )
    getattr(blackjack, action)(*args)
    assert len(received) == expected
    if received:
        assert received[0].tg_id == 42


def test_failed_cash_transaction_does_not_emit(monkeypatch):
    received = []
    monkeypatch.setattr(events, "emit", received.append)

    def failed(*args):
        raise RuntimeError("rollback")

    monkeypatch.setattr(blackjack.blackjack_repository, "blackjack_stand", failed)
    with pytest.raises(RuntimeError):
        blackjack.blackjack_stand(42, 1)
    assert received == []


@pytest.mark.asyncio
async def test_six_subscriptions_register_once(monkeypatch):
    from app.domains.blackjack.events import CashHandPlayed
    from app.domains.crypto_donation.events import CryptoDonationCompleted
    from app.domains.donation.events import DonationApproved
    from app.domains.luckywheel.events import WheelSpun
    from app.domains.prediction.events import PredictionBetPlaced
    from app.domains.treasure.events import TreasureJoined

    game = AsyncMock()
    donation = AsyncMock()
    monkeypatch.setattr(awards, "on_game_activity", game)
    monkeypatch.setattr(awards, "on_donation", donation)
    events.clear_subscriptions()
    try:
        register_all()
        register_all()
        for kind in (
            CashHandPlayed,
            WheelSpun,
            PredictionBetPlaced,
            TreasureJoined,
            DonationApproved,
            CryptoDonationCompleted,
        ):
            events.emit(kind(42))
        await events.drain()
        assert game.await_count == 4
        assert donation.await_count == 2
    finally:
        events.clear_subscriptions()
        monkeypatch.undo()
        register_all()


@pytest.mark.asyncio
async def test_ten_spins_emit_once_and_compatibility_spin_excluded(monkeypatch):
    received = []
    monkeypatch.setattr(events, "emit", received.append)
    monkeypatch.setattr(wheel.wheel_config, "get_randomness_config", dict)
    monkeypatch.setattr(
        wheel.luckywheel_rules,
        "pick_prize",
        lambda *args, **kwargs: SimpleNamespace(name="test", probability=1),
    )
    monkeypatch.setattr(
        wheel,
        "_to_committed_spin",
        lambda data: SimpleNamespace(
            privileged=False,
            result=LuckyWheelSpinResult(
                item=LuckyWheelItem(name="test", probability=1),
                credits_change=1,
                current_credits=100,
            ),
        ),
    )
    monkeypatch.setattr(wheel, "_post_commit", AsyncMock())
    monkeypatch.setattr(wheel.repository, "spin_ten", lambda **kwargs: [{}] * 10)
    config = LuckyWheelConfig(items=[])
    result = await wheel.spin_ten_times(42, config=config)
    assert len(result.results) == 10
    assert len(received) == 1
    monkeypatch.setattr(wheel.repository, "spin", lambda **kwargs: {})
    await wheel.execute_single_spin(config, 42, 100)
    assert len(received) == 1


def test_read_api_counts_preserve_sources_and_distinct_issues(session_env):
    from app.core.db import get_session
    from app.domains.donation import service as donation
    from app.domains.identity.models import Statistics
    from app.domains.luckywheel.models import WheelStats
    from app.domains.prediction.models import PredictionBet, PredictionMarket
    from app.domains.treasure.models import TreasureIssue, TreasureParticipation

    with get_session() as session:
        session.add_all(
            [
                Statistics(tg_id=42, donation=1688),
                Statistics(tg_id=43, donation=1688.01),
            ]
        )
        for i, source in enumerate(("paid", "blackjack_free", "gift_pack_free"), 1):
            session.add(
                WheelStats(
                    id=i,
                    tg_id=42,
                    item_name="test",
                    credits_change=0,
                    timestamp=1,
                    date="2026-01-01",
                    source=source,
                )
            )
        session.add(PredictionMarket(id=1, title="test"))
        for i in range(1, 4):
            session.add(PredictionBet(id=i, market_id=1, tg_id=42, option=1, amount=10))
        for i in (1, 2):
            session.add(
                TreasureIssue(
                    id=i,
                    title="test",
                    prize_credits=10,
                    total_credits_required=10,
                    total_shares=3,
                )
            )
        for i, issue in enumerate((1, 1, 2), 1):
            session.add(
                TreasureParticipation(
                    id=i,
                    issue_id=issue,
                    tg_id=42,
                    lucky_number=i,
                    cost_credits=10,
                    created_at_ms=1,
                )
            )
    assert wheel.count_badge_spins(42) == 3
    assert wheel.list_badge_eligible_tg_ids(3) == [42]
    assert treasure.count_badge_issues(42) == 2
    assert treasure.list_badge_eligible_tg_ids(3) == []
    assert treasure.list_badge_eligible_tg_ids(2) == [42]
    assert prediction.count_badge_bets(42) == 3
    assert prediction.list_badge_eligible_tg_ids(3) == [42]
    assert donation.list_badge_eligible_donors(1688) == [(43, 1688.01)]
    assert donation.list_badge_eligible_donors(1688, 42) == []


@pytest.mark.asyncio
async def test_batch_candidates_deduplicated_and_no_notification_on_conflict(
    monkeypatch, mocked_checks
):
    monkeypatch.setattr(wheel, "list_badge_eligible_tg_ids", lambda minimum: [42])
    monkeypatch.setattr(
        treasure, "list_badge_eligible_tg_ids", lambda minimum: [42, 43]
    )
    monkeypatch.setattr(prediction, "list_badge_eligible_tg_ids", lambda minimum: [43])
    monkeypatch.setattr(
        blackjack, "get_game_king_eligible_tg_ids", lambda hands, accuracy: [44]
    )
    calls = []

    def award(tg_id, badge_type):
        calls.append(tg_id)
        return tg_id == 44

    monkeypatch.setattr(awards.badges_service, "award_badge", award)
    monkeypatch.setattr(awards.asyncio, "sleep", AsyncMock())
    assert await awards.check_and_award_game_king_badge() is None
    assert calls == [42, 43, 44]
    assert mocked_checks.await_count == 1
    assert mocked_checks.call_args.kwargs["chat_id"] == 44


@pytest.mark.asyncio
async def test_prediction_success_once_and_failure_excluded(monkeypatch):
    received = []
    monkeypatch.setattr(events, "emit", received.append)
    monkeypatch.setattr(
        prediction.prediction_repository, "place_prediction_bet", lambda **kwargs: {}
    )
    monkeypatch.setattr(
        prediction.prediction_notifications, "notify_prediction_bet_placed", AsyncMock()
    )
    await prediction.place_prediction_bet(market_id=1, tg_id=42, option=1, amount=10)
    assert len(received) == 1

    def failed(**kwargs):
        raise RuntimeError("rollback")

    monkeypatch.setattr(
        prediction.prediction_repository, "place_prediction_bet", failed
    )
    with pytest.raises(RuntimeError):
        await prediction.place_prediction_bet(
            market_id=1, tg_id=42, option=1, amount=10
        )
    assert len(received) == 1


@pytest.mark.asyncio
async def test_treasure_multiple_shares_emits_once(monkeypatch):
    received = []
    monkeypatch.setattr(events, "emit", received.append)
    monkeypatch.setattr(
        treasure.eth_rpc, "latest_block_hash_int", AsyncMock(return_value=1)
    )
    monkeypatch.setattr(
        treasure.treasure_repository,
        "join_treasure_issue",
        lambda **kwargs: {"participations": [{}, {}, {}]},
    )
    monkeypatch.setattr(
        treasure.treasure_repository, "get_treasure_issue_by_id", lambda issue_id: {}
    )
    monkeypatch.setattr(
        treasure.treasure_notifications,
        "notify_treasure_not_full_after_join",
        AsyncMock(),
    )
    await treasure.join_treasure_issue(issue_id=1, tg_id=42, quantity=3)
    assert len(received) == 1
    assert received[0].tg_id == 42


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id", [42, None])
async def test_donor_boundary_and_committed_notifications(
    session_env, monkeypatch, mocked_checks, user_id
):
    from app.core.db import get_session
    from app.domains.identity.models import Statistics

    with get_session() as session:
        session.add(Statistics(tg_id=42, donation=1688, credits=0))
    monkeypatch.setattr(awards.asyncio, "sleep", AsyncMock())
    assert await awards.check_and_award_supreme_contributor_badge(user_id) == (
        False if user_id else None
    )
    mocked_checks.assert_not_awaited()
    with get_session() as session:
        session.get(Statistics, 42).donation = 1688.01
    assert await awards.check_and_award_supreme_contributor_badge(user_id) == (
        True if user_id else None
    )
    mocked_checks.assert_awaited_once_with(
        chat_id=42,
        text=(
            "🏆 恭喜获得勋章！\n====================\n\n"
            "勋章名称：supreme_contributor\n勋章权益：每日观看积分 +18%\n"
            "有效期限：永久\n\n感谢您的支持与贡献！\n\n===================="
        ),
        disable_notification=False,
    )
    monkeypatch.setattr(awards.badges_service, "award_badge", lambda *args: False)
    await awards.check_and_award_supreme_contributor_badge(user_id)
    assert mocked_checks.await_count == 1


@pytest.mark.asyncio
async def test_real_blackjack_accuracy_rounding_differs_in_single_and_batch(
    session_env, monkeypatch
):
    from app.core.db import get_session
    from app.domains.blackjack import rules as blackjack_rules
    from app.domains.blackjack.models import BlackjackHand
    from tests.conftest import add_cash_hand

    hand_id = add_cash_hand(42)
    with get_session() as session:
        hand = session.get(BlackjackHand, hand_id)
        hand.status = next(iter(blackjack_rules.TERMINAL_STATUSES))
        hand.decisions_total = 25001
        hand.decisions_correct = 20000
    assert blackjack.get_user_blackjack_stats(42)["accuracy"] == 80.0
    assert blackjack.get_game_king_eligible_tg_ids(1, 80) == []
    monkeypatch.setattr(
        blackjack,
        "get_blackjack_config_dict",
        lambda: {"badge_min_hands": 1, "badge_min_accuracy": 80},
    )
    monkeypatch.setattr(
        awards.badges_service, "get_badge_by_type", lambda kind: {"name": "game_king"}
    )
    awarded = []
    monkeypatch.setattr(
        awards.badges_service, "award_badge", lambda *args: awarded.append(args) or True
    )
    notify = AsyncMock()
    monkeypatch.setattr(awards.messaging, "send_message_by_url", notify)
    assert await awards.check_and_award_game_king_badge(42) is True
    assert len(awarded) == 1
    assert await awards.check_and_award_game_king_badge() is None
    assert len(awarded) == 1
    assert notify.await_count == 1
