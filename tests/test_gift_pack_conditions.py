"""礼包条件 schema 与求值引擎测试（openspec: add-gift-pack-audience-and-tasks）。

这些用例只覆盖条件 schema、旧礼包兼容、计数器、条件进度、计数缓存和
生命周期边界；礼包受众及各用户入口在 test_gift_pack_audience.py 中覆盖。
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import event, text

from app.core.db import get_session
from app.domains.auction.models import AuctionBids, Auctions
from app.domains.badges.models import Badge, UserBadge
from app.domains.blackjack.config import TOURNAMENT_RUNNING
from app.domains.blackjack.models import (
    BlackjackHand,
    BlackjackTournament,
    BlackjackTournamentEntry,
)
from app.domains.gift_pack.models import GiftPack, GiftPackUserState
from app.domains.gift_pack.schemas import GiftPackCreateRequest
from app.domains.identity.models import EmbyUser, PlexUser
from app.domains.invitation.models import Invitation
from app.domains.luckywheel.models import WheelStats
from app.domains.prediction.models import PredictionBet, PredictionMarket
from app.domains.treasure.models import TreasureIssue, TreasureParticipation
from tests.conftest import add_cash_hand, add_entry, add_tournament, add_user, next_id


# SQLite does not autoincrement BIGINT primary keys.  Production code inserts many
# of these rows without an explicit id, so the test-only listener supplies one.
def _assign_bigint_id(mapper, connection, target) -> None:
    if target.id is None:
        target.id = next_id()


for _model in (
    AuctionBids,
    Auctions,
    Badge,
    BlackjackHand,
    BlackjackTournament,
    BlackjackTournamentEntry,
    GiftPack,
    GiftPackUserState,
    PredictionBet,
    PredictionMarket,
    TreasureIssue,
    TreasureParticipation,
    UserBadge,
    WheelStats,
):
    event.listen(_model, "before_insert", _assign_bigint_id)


BASE_REQUEST = {
    "title": "条件礼包",
    "rewards": [{"type": "credits", "amount": 10}],
    "start_at": 100,
    "end_at": 200,
}


def _pack(
    *,
    start_at: int,
    end_at: int,
    audience: list[dict] | None = None,
    requirements: list[dict] | None = None,
    eligibility: dict | None = None,
    task_end_at: int | None = None,
    max_task_prompt_count: int = 2,
    notify_audience_on_start: int = 0,
    is_enabled: int = 1,
) -> GiftPack:
    now = int(time.time())
    return GiftPack(
        id=next_id(),
        title="测试礼包",
        rewards=json.dumps([{"type": "credits", "amount": 10}]),
        audience=json.dumps(audience, ensure_ascii=False)
        if audience is not None
        else None,
        requirements=(
            json.dumps(requirements, ensure_ascii=False)
            if requirements is not None
            else None
        ),
        eligibility=(
            json.dumps(eligibility, ensure_ascii=False)
            if eligibility is not None
            else None
        ),
        task_end_at=task_end_at,
        total_quantity=None,
        claimed_count=0,
        start_at=start_at,
        end_at=end_at,
        max_prompt_count=3,
        max_task_prompt_count=max_task_prompt_count,
        notify_audience_on_start=notify_audience_on_start,
        is_enabled=is_enabled,
        expiry_notified=0,
        created_at=now,
        updated_at=now,
    )


def _update_hand(
    hand_id: int,
    *,
    status: int = 3,
    tournament_id: int | None = None,
    decisions_total: int = 0,
    decisions_correct: int = 0,
) -> None:
    with get_session() as session:
        hand = session.get(BlackjackHand, hand_id)
        assert hand is not None
        hand.status = status
        hand.tournament_id = tournament_id
        hand.decisions_total = decisions_total
        hand.decisions_correct = decisions_correct


def _insert_treasure_issue(issue_id: int) -> None:
    with get_session() as session:
        session.add(
            TreasureIssue(
                id=issue_id,
                title=f"issue-{issue_id}",
                description=None,
                prize_credits=100,
                total_credits_required=100,
                credits_per_share=10,
                total_shares=10,
                start_number=10000001,
                status=1,
                shares_sold=0,
            )
        )


def _insert_market(market_id: int) -> None:
    with get_session() as session:
        session.add(
            PredictionMarket(
                id=market_id,
                title=f"market-{market_id}",
                description=None,
                status=1,
                result_option=None,
                betting_deadline=9999999999,
                real_yes_pool=0,
                real_no_pool=0,
                virtual_yes_pool=500,
                virtual_no_pool=500,
                fee_rate_bp=500,
                fee_burn_bp=300,
                fee_glory_bp=200,
                max_bet_per_user=500,
                total_fee_collected=0,
                fee_burned=0,
                fee_to_glory=0,
                resolution_note=None,
                created_by=None,
                resolved_by=None,
                resolved_at=None,
                created_at=datetime.fromtimestamp(1000, UTC),
            )
        )


def _insert_auction(auction_id: int) -> None:
    with get_session() as session:
        session.add(
            Auctions(
                id=auction_id,
                title=f"auction-{auction_id}",
                description="test",
                starting_price=1,
                current_price=1,
                end_time=9999999999,
                created_by=1,
                created_at=1000,
                is_active=1,
                winner_id=None,
                bid_count=0,
            )
        )


# ---------------------------------------------------------------------------
# Schema validation (OpenSpec 2.1)


def _request(**overrides):
    values = {**BASE_REQUEST, **overrides}
    return GiftPackCreateRequest.model_validate(values)


def test_schema_accepts_all_leaf_condition_families_and_any_of():
    audience = [
        {"type": "user_list", "mode": "include", "tg_ids": [1, 2]},
        {"type": "premium", "state": "active"},
        {"type": "bound", "service": "plex"},
        {"type": "credits", "min": 10, "max": 100},
        {"type": "badge", "badge_id": 1},
        {"type": "claimed_pack", "pack_id": 2},
        {"type": "wheel_spins", "min": 2, "window": {"kind": "pack"}},
        {"type": "blackjack_hands", "min": 2, "min_bet": 10, "min_accuracy": 80},
        {"type": "treasure_issues", "min": 2, "window": {"kind": "days", "days": 7}},
        {"type": "prediction_bets", "min": 2},
        {"type": "auction_participations", "min": 2},
        {"type": "tournament_entries", "min": 2},
        {"type": "invitees", "min": 2},
        {"type": "watched_hours", "min": 2.5},
        {
            "type": "any_of",
            "items": [
                {"type": "wheel_spins", "min": 5},
                {"type": "blackjack_hands", "min": 5},
            ],
        },
    ]

    request = _request(audience=audience, requirements=audience[1:])

    assert request.audience is not None
    assert request.requirements is not None
    assert request.max_task_prompt_count == 2
    assert request.audience[0].type == "user_list"
    assert request.requirements[-1].type == "any_of"


def test_schema_normalizes_empty_condition_lists_and_validates_task_window():
    request = _request(audience=[], requirements=[])

    assert request.audience is None
    assert request.requirements is None

    with pytest.raises(ValidationError):
        _request(task_end_at=100)
    assert _request(task_end_at=150).task_end_at == 150
    assert _request(task_end_at=200).task_end_at == 200
    with pytest.raises(ValidationError):
        _request(task_end_at=99)
    with pytest.raises(ValidationError):
        _request(task_end_at=201)


def test_schema_rejects_invalid_condition_shapes():
    invalid_requests = [
        {"requirements": [{"type": "credits"}]},
        {"requirements": [{"type": "credits", "min": 101, "max": 100}]},
        {
            "requirements": [
                {"type": "wheel_spins", "min": 1, "window": {"kind": "days", "days": 0}}
            ]
        },
        {
            "requirements": [
                {
                    "type": "wheel_spins",
                    "min": 1,
                    "window": {"kind": "days", "days": 366},
                }
            ]
        },
        {"requirements": [{"type": "invitees", "min": 1, "window": {"kind": "pack"}}]},
        {
            "requirements": [
                {
                    "type": "watched_hours",
                    "min": 1,
                    "window": {"kind": "days", "days": 7},
                }
            ]
        },
        {
            "requirements": [
                {"type": "any_of", "items": [{"type": "credits", "min": 1}]}
            ]
        },
        {
            "requirements": [
                {
                    "type": "any_of",
                    "items": [
                        {"type": "credits", "min": 1},
                        {
                            "type": "any_of",
                            "items": [
                                {"type": "credits", "min": 2},
                                {"type": "premium", "state": "active"},
                            ],
                        },
                    ],
                }
            ]
        },
        {"requirements": [{"type": "user_list", "mode": "include", "tg_ids": [1]}]},
        {
            "requirements": [
                {
                    "type": "any_of",
                    "items": [
                        {"type": "user_list", "mode": "include", "tg_ids": [1]},
                        {"type": "credits", "min": 1},
                    ],
                }
            ]
        },
        {
            "audience": [
                {"type": "user_list", "mode": "include", "tg_ids": list(range(5001))}
            ]
        },
    ]

    for invalid in invalid_requests:
        with pytest.raises(ValidationError):
            _request(**invalid)


def test_schema_requires_include_list_for_start_notification():
    with pytest.raises(ValidationError, match="include"):
        _request(
            notify_audience_on_start=True,
            audience=[{"type": "user_list", "mode": "exclude", "tg_ids": [1]}],
        )

    with pytest.raises(ValidationError, match="include"):
        _request(
            notify_audience_on_start=True,
            audience=[{"type": "credits", "max": 100}],
        )

    request = _request(
        notify_audience_on_start=True,
        audience=[{"type": "user_list", "mode": "include", "tg_ids": [1]}],
    )
    assert request.notify_audience_on_start is True


# ---------------------------------------------------------------------------
# Legacy conversion and condition evaluation (OpenSpec 3.1, 3.3, 3.4)


def test_resolve_conditions_converts_legacy_eligibility_without_mutating_pack(orm):
    pack = _pack(
        start_at=100,
        end_at=200,
        eligibility={
            "min_credits": 50,
            "require_premium": True,
            "require_binding": "emby",
        },
    )

    audience, requirements = orm._resolve_gift_pack_conditions(pack)

    assert audience == []
    assert requirements == [
        {"type": "credits", "min": 50},
        {"type": "premium", "state": "active"},
        {"type": "bound", "service": "emby"},
    ]
    assert pack.requirements is None
    assert pack.eligibility is not None


def test_resolve_conditions_prefers_new_columns_over_legacy(orm):
    pack = _pack(
        start_at=100,
        end_at=200,
        audience=[{"type": "credits", "max": 10}],
        requirements=[{"type": "wheel_spins", "min": 3}],
        eligibility={"min_credits": 999},
    )

    audience, requirements = orm._resolve_gift_pack_conditions(pack)

    assert audience == [{"type": "credits", "max": 10}]
    assert requirements == [{"type": "wheel_spins", "min": 3}]


def test_load_context_contains_live_state_sets_and_request_metric_cache(orm):
    add_user(orm, 1, credits=42)
    with get_session() as session:
        claimed_pack = _pack(start_at=100, end_at=200)
        claimed_pack.id = 88
        session.add(claimed_pack)
        session.add(
            Badge(
                id=7,
                badge_type="test-badge",
                name="测试勋章",
                description="test",
                icon_url="",
                credits_cost=0,
                bonus_percentage=0,
                valid_days=365,
                is_enabled=1,
                created_at=100,
                updated_at=100,
            )
        )
        session.add(
            UserBadge(
                id=next_id(),
                tg_id=1,
                badge_id=7,
                credits_cost=0,
                redeemed_at=100,
                expires_at=9999999999,
                is_active=1,
            )
        )
        session.add(
            GiftPackUserState(id=next_id(), pack_id=88, tg_id=1, claimed_at=123)
        )
        session.flush()

        context = orm._load_gift_pack_user_context(session, 1)

    assert context["has_stats"] is True
    assert context["credits"] == 42.0
    assert context["badge_ids"] == {7}
    assert context["claimed_pack_ids"] == {88}
    assert context["_tg_id"] == 1
    assert context["_metric_cache"] == {}


def test_condition_progress_and_any_of_group_report_all_children(orm, monkeypatch):
    pack = _pack(start_at=100, end_at=1000)
    calls = []

    def count_wheels(session, tg_id, since, until, **qualifiers):
        calls.append((tg_id, since, until, qualifiers))
        return 12

    monkeypatch.setattr(orm, "_count_gift_pack_wheel_spins", count_wheels)
    context = {
        "credits": 20,
        "premium_services": [],
        "bound_services": [],
        "badge_ids": set(),
        "claimed_pack_ids": set(),
        "_session": object(),
        "_tg_id": 1,
        "_metric_cache": {},
    }
    items = [
        {"type": "credits", "min": 50},
        {
            "type": "any_of",
            "items": [
                {"type": "wheel_spins", "min": 10, "window": {"kind": "pack"}},
                {"type": "wheel_spins", "min": 20, "window": {"kind": "pack"}},
            ],
        },
    ]

    ok, progress = orm._evaluate_conditions(items, context, pack, ref=200)

    assert ok is False
    assert progress[0]["met"] is False
    assert progress[0]["current"] == 20
    assert progress[0]["target"] == 50
    assert progress[1]["type"] == "any_of"
    assert progress[1]["met"] is True
    assert [item["met"] for item in progress[1]["items"]] == [True, False]
    assert progress[1]["label"] == "任选其一"
    # The two leaves have identical metric keys and share one request cache entry.
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Counter primitives (OpenSpec 3.2)


def test_wheel_counter_includes_time_boundaries_and_filters_free_spins(orm):
    add_user(orm, 1)
    with get_session() as session:
        for row_id, timestamp, source in (
            (next_id(), 100, "paid"),
            (next_id(), 200, "paid"),
            (next_id(), 150, "blackjack_free"),
            (next_id(), 99, "paid"),
            (next_id(), 201, "paid"),
        ):
            session.add(
                WheelStats(
                    id=row_id,
                    tg_id=1,
                    item_name="奖品",
                    cost_credits=10,
                    credits_change=5,
                    timestamp=timestamp,
                    date="1970-01-01",
                    source=source,
                )
            )
        session.flush()
        assert orm._count_gift_pack_wheel_spins(session, 1, 100, 200) == 2
        assert (
            orm._count_gift_pack_wheel_spins(session, 1, 100, 200, paid_only=False) == 3
        )


def test_blackjack_counter_excludes_tournaments_filters_bet_and_calculates_accuracy(
    orm,
):
    add_user(orm, 1)
    first = add_cash_hand(orm, 1, bet_credits=5, created_at_ms=100000)
    second = add_cash_hand(orm, 1, bet_credits=10, created_at_ms=200000)
    tournament_hand = add_cash_hand(
        orm, 1, bet_credits=100, created_at_ms=150000, tournament_id=999
    )
    outside = add_cash_hand(orm, 1, bet_credits=10, created_at_ms=999999)
    pending = add_cash_hand(orm, 1, bet_credits=10, created_at_ms=150000)
    _update_hand(first, decisions_total=4, decisions_correct=3)
    _update_hand(second, decisions_total=0, decisions_correct=0)
    _update_hand(
        tournament_hand, tournament_id=999, decisions_total=4, decisions_correct=4
    )
    _update_hand(outside, decisions_total=4, decisions_correct=4)
    _update_hand(pending, status=1, decisions_total=4, decisions_correct=4)

    with get_session() as session:
        assert orm._count_gift_pack_blackjack_hands(session, 1, 100, 200) == 2
        assert (
            orm._count_gift_pack_blackjack_hands(session, 1, 100, 200, min_bet=10) == 1
        )
        count, accuracy = orm._count_gift_pack_blackjack_hands(
            session, 1, 100, 200, min_accuracy=80
        )

    assert count == 2
    assert accuracy == pytest.approx(75.0)


def test_treasure_and_auction_counters_deduplicate_by_issue_and_auction(orm):
    add_user(orm, 1)
    issue_a, issue_b = next_id(), next_id()
    auction_a, auction_b = next_id(), next_id()
    _insert_treasure_issue(issue_a)
    _insert_treasure_issue(issue_b)
    _insert_auction(auction_a)
    _insert_auction(auction_b)
    with get_session() as session:
        session.add_all(
            [
                TreasureParticipation(
                    id=next_id(),
                    issue_id=issue_a,
                    tg_id=1,
                    lucky_number=1,
                    cost_credits=10,
                    created_at_ms=100000,
                ),
                TreasureParticipation(
                    id=next_id(),
                    issue_id=issue_a,
                    tg_id=1,
                    lucky_number=2,
                    cost_credits=10,
                    created_at_ms=150000,
                ),
                TreasureParticipation(
                    id=next_id(),
                    issue_id=issue_b,
                    tg_id=1,
                    lucky_number=3,
                    cost_credits=10,
                    created_at_ms=200000,
                ),
                TreasureParticipation(
                    id=next_id(),
                    issue_id=issue_b,
                    tg_id=1,
                    lucky_number=4,
                    cost_credits=10,
                    created_at_ms=999999,
                ),
                AuctionBids(
                    id=next_id(),
                    auction_id=auction_a,
                    bidder_id=1,
                    bid_amount=10,
                    bid_time=100,
                ),
                AuctionBids(
                    id=next_id(),
                    auction_id=auction_a,
                    bidder_id=1,
                    bid_amount=11,
                    bid_time=150,
                ),
                AuctionBids(
                    id=next_id(),
                    auction_id=auction_b,
                    bidder_id=1,
                    bid_amount=12,
                    bid_time=200,
                ),
                AuctionBids(
                    id=next_id(),
                    auction_id=auction_b,
                    bidder_id=1,
                    bid_amount=13,
                    bid_time=999,
                ),
            ]
        )
        session.flush()
        assert orm._count_gift_pack_treasure_issues(session, 1, 100, 200) == 2
        assert orm._count_gift_pack_auction_participations(session, 1, 100, 200) == 2


def test_prediction_counter_uses_utc_datetime_boundaries(orm):
    add_user(orm, 1)
    market_id = next_id()
    _insert_market(market_id)
    with get_session() as session:
        session.add_all(
            [
                PredictionBet(
                    id=next_id(),
                    market_id=market_id,
                    tg_id=1,
                    option=0,
                    amount=1,
                    created_at=datetime.fromtimestamp(100, UTC),
                ),
                PredictionBet(
                    id=next_id(),
                    market_id=market_id,
                    tg_id=1,
                    option=1,
                    amount=1,
                    created_at=datetime.fromtimestamp(200, UTC),
                ),
                PredictionBet(
                    id=next_id(),
                    market_id=market_id,
                    tg_id=1,
                    option=0,
                    amount=1,
                    created_at=datetime.fromtimestamp(201, UTC),
                ),
            ]
        )
        session.flush()
        assert orm._count_gift_pack_prediction_bets(session, 1, 100, 200) == 2


def test_tournament_counter_excludes_cancelled_events_and_applies_time_window(orm):
    add_user(orm, 1)
    active = add_tournament(orm, status=TOURNAMENT_RUNNING)
    active_two = add_tournament(orm, status=TOURNAMENT_RUNNING)
    cancelled = add_tournament(orm, status=4)
    add_entry(orm, active["id"], 1, registered_at_ms=100000)
    add_entry(orm, cancelled["id"], 1, registered_at_ms=150000)
    add_entry(orm, active_two["id"], 1, registered_at_ms=200000)
    outside = add_tournament(orm, status=TOURNAMENT_RUNNING)
    add_entry(orm, outside["id"], 1, registered_at_ms=999999)

    with get_session() as session:
        assert orm._count_gift_pack_tournament_entries(session, 1, 100, 200) == 2


def test_invitees_and_watched_hours_are_historical_and_distinct(orm):
    add_user(orm, 1)
    with get_session() as session:
        session.add_all(
            [
                Invitation(code="a", owner=1, is_used=1, used_by="2"),
                Invitation(code="b", owner=1, is_used=1, used_by="2"),
                Invitation(code="c", owner=1, is_used=1, used_by="3"),
                Invitation(code="d", owner=1, is_used=0, used_by=None),
                PlexUser(
                    plex_id=101,
                    tg_id=1,
                    plex_email="1@example.com",
                    plex_username="p1",
                    watched_time=2.5,
                ),
                EmbyUser(emby_username="e1", tg_id=1, emby_watched_time=1.5),
            ]
        )
        session.flush()
        assert orm._count_gift_pack_invitees(session, 1, 100, 200) == 2
        assert orm._count_gift_pack_watched_hours(session, 1, 0, 1) == pytest.approx(
            4.0
        )


# ---------------------------------------------------------------------------
# Cache, deadline freezing, and lifecycle (OpenSpec 3.3-3.5)


def test_metric_cache_is_shared_by_same_metric_window_and_qualifiers(orm, monkeypatch):
    pack = _pack(start_at=100, end_at=1000)
    calls = []

    def count_wheels(session, tg_id, since, until, **qualifiers):
        calls.append((since, until, tuple(sorted(qualifiers.items()))))
        return 4

    monkeypatch.setattr(orm, "_count_gift_pack_wheel_spins", count_wheels)
    context = {
        "credits": 0,
        "premium_services": [],
        "bound_services": [],
        "badge_ids": set(),
        "claimed_pack_ids": set(),
        "_session": object(),
        "_tg_id": 1,
        "_metric_cache": {},
    }
    first = {"type": "wheel_spins", "min": 4, "window": {"kind": "pack"}}
    second = {"type": "wheel_spins", "min": 5, "window": {"kind": "pack"}}

    assert orm._gift_pack_metric_value(first, context, pack, ref=500) == 4
    assert orm._gift_pack_metric_value(second, context, pack, ref=500) == 4
    assert len(calls) == 1


def test_pack_window_before_start_returns_zero_without_count_query(orm, monkeypatch):
    pack = _pack(start_at=500, end_at=1000)

    def should_not_query(*args, **kwargs):
        raise AssertionError("pack-window counter queried before pack start")

    monkeypatch.setattr(orm, "_count_gift_pack_wheel_spins", should_not_query)
    context = {
        "_session": object(),
        "_tg_id": 1,
        "_metric_cache": {},
    }

    assert (
        orm._gift_pack_metric_value(
            {"type": "wheel_spins", "min": 1, "window": {"kind": "pack"}},
            context,
            pack,
            ref=499,
        )
        == 0
    )


def test_lifecycle_boundaries_and_frozen_phase_reference(orm):
    active_pack = _pack(start_at=100, end_at=300, task_end_at=200)
    no_task_deadline = _pack(start_at=100, end_at=300)
    deadline_at_end = _pack(start_at=100, end_at=300, task_end_at=300)

    assert orm._gift_pack_lifecycle(active_pack, 99) == "upcoming"
    assert orm._gift_pack_lifecycle(active_pack, 100) == "active"
    assert orm._gift_pack_lifecycle(active_pack, 200) == "active"
    assert orm._gift_pack_lifecycle(active_pack, 201) == "claim_only"
    assert orm._gift_pack_lifecycle(active_pack, 300) == "claim_only"
    assert orm._gift_pack_lifecycle(active_pack, 301) == "ended"
    assert orm._gift_pack_lifecycle(no_task_deadline, 300) == "active"
    assert orm._gift_pack_lifecycle(deadline_at_end, 300) == "active"
    assert orm._gift_pack_lifecycle(deadline_at_end, 301) == "ended"
    assert orm._gift_pack_phase_ref(active_pack, 250) == 200
    assert orm._gift_pack_phase_ref(active_pack, 150) == 150
    assert orm._gift_pack_phase_ref(no_task_deadline, 250) == 250


def test_blackjack_accuracy_with_no_decisions_is_zero(orm):
    add_user(orm, 1)
    hand_id = add_cash_hand(orm, 1, bet_credits=10, created_at_ms=100000)
    _update_hand(hand_id, decisions_total=0, decisions_correct=0)

    with get_session() as session:
        count, accuracy = orm._count_gift_pack_blackjack_hands(
            session, 1, 100, 200, min_accuracy=1
        )

    assert count == 1
    assert accuracy == 0.0


@pytest.mark.parametrize(
    "old, new",
    [
        (
            {"min_credits": 50},
            [{"type": "credits", "min": 50}],
        ),
        (
            {"require_premium": True},
            [{"type": "premium", "state": "active"}],
        ),
        (
            {"require_binding": "any"},
            [{"type": "bound", "service": "any"}],
        ),
    ],
)
def test_legacy_fields_each_map_to_an_equivalent_leaf(orm, old, new):
    pack = _pack(start_at=100, end_at=200, eligibility=old)
    _, requirements = orm._resolve_gift_pack_conditions(pack)
    assert requirements == new


def test_legacy_pack_uses_zero_task_prompt_limit(orm):
    # Omit new columns just as an existing row would under the add-column migration.
    pack_id = next_id()
    with get_session() as session:
        session.execute(
            text(
                "INSERT INTO gift_pack "
                "(id, title, rewards, eligibility, start_at, end_at, "
                "created_at, updated_at, claimed_count, max_prompt_count, "
                "is_enabled, expiry_notified) "
                "VALUES (:id, 'legacy', :rewards, :eligibility, "
                "100, 200, 100, 100, 0, 3, 1, 0)"
            ),
            {
                "id": pack_id,
                "rewards": json.dumps([{"type": "credits", "amount": 10}]),
                "eligibility": json.dumps({"min_credits": 50}),
            },
        )
        pack = session.get(GiftPack, pack_id)
        assert pack is not None
        assert pack.max_task_prompt_count == 0
        _, requirements = orm._resolve_gift_pack_conditions(pack)
        assert requirements == [{"type": "credits", "min": 50}]


# ------------------------------------------------------ 领取拒绝的文案


def _save_pack(pack: GiftPack) -> int:
    with get_session() as session:
        session.add(pack)
        session.flush()
        return int(pack.id)


def _pack_with_rewards(*, start_at: int, end_at: int, rewards: list[dict]) -> GiftPack:
    pack = _pack(start_at=start_at, end_at=end_at)
    pack.rewards = json.dumps(rewards, ensure_ascii=False)
    return pack


def test_claim_rejections_keep_their_messages(orm):
    """领取的每类拒绝都保留原有文案，供 router 与前端展示。"""
    now = int(time.time())
    add_user(orm, 1)
    add_user(orm, 2)

    def claim(pack_id: int, tg_id: int = 1):
        return orm.claim_gift_pack(pack_id, tg_id)

    disabled = _save_pack(_pack(start_at=now - 10, end_at=now + 3600, is_enabled=0))
    future = _save_pack(_pack(start_at=now + 3600, end_at=now + 7200))
    ended = _save_pack(_pack(start_at=now - 7200, end_at=now - 3600))
    limited = _save_pack(_pack(start_at=now - 10, end_at=now + 3600))
    with get_session() as session:
        pack_row = session.get(GiftPack, limited)
        pack_row.total_quantity = 1
        pack_row.claimed_count = 1
    claimed = _save_pack(_pack(start_at=now - 10, end_at=now + 3600))
    claim(claimed)
    unbound = _save_pack(
        _pack_with_rewards(
            start_at=now - 10,
            end_at=now + 3600,
            rewards=[{"type": "premium_days", "days": 7}],
        )
    )
    no_stats = _save_pack(_pack(start_at=now - 10, end_at=now + 3600))

    with pytest.raises(ValueError, match="^礼包不存在$"):
        claim(999_999)
    with pytest.raises(ValueError, match="^礼包已停用$"):
        claim(disabled)
    with pytest.raises(ValueError, match="^礼包尚未开始$"):
        claim(future)
    with pytest.raises(ValueError, match="^礼包已结束$"):
        claim(ended)
    with pytest.raises(ValueError, match="^礼包已被领完$"):
        claim(limited)
    with pytest.raises(ValueError, match="^你已领取过该礼包$"):
        claim(claimed)
    with pytest.raises(ValueError, match="^请先绑定媒体账号后再领取$"):
        claim(unbound, 2)
    with pytest.raises(ValueError, match="^用户积分信息不存在$"):
        claim(no_stats, 9999)
