"""Tests for Telegram ID reassignment in reward domains (badges, gift_pack, luckywheel)."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.domains.badges import repository as badges_repository
from app.domains.badges.models import Badge, UserBadge
from app.domains.gift_pack import repository as gift_pack_repository
from app.domains.gift_pack.models import GiftPack, GiftPackUserState
from app.domains.identity.models import Statistics
from app.domains.identity.types import TgIdReassignIssue
from app.domains.luckywheel import repository as luckywheel_repository
from app.domains.luckywheel.models import LuckywheelFreeSpin, WheelStats
from tests.conftest import next_id


def _ensure_stats(session: Session, *tg_ids: int) -> None:
    """Ensure statistics rows exist for foreign key targets."""
    for tg_id in tg_ids:
        if not session.get(Statistics, tg_id):
            session.add(
                Statistics(
                    tg_id=tg_id,
                    credits=0.0,
                    donation=0.0,
                )
            )
    session.flush()


def test_reassigned_tg_id_columns_registry():
    """Verify REASSIGNED_TG_ID_COLUMNS definitions on all three repositories."""
    assert badges_repository.REASSIGNED_TG_ID_COLUMNS == ("user_badges.tg_id",)
    assert luckywheel_repository.REASSIGNED_TG_ID_COLUMNS == (
        "wheel_stats.tg_id",
        "luckywheel_free_spins.tg_id",
    )
    assert gift_pack_repository.REASSIGNED_TG_ID_COLUMNS == (
        "gift_pack.created_by",
        "gift_pack_user_state.tg_id",
        "gift_pack.audience",
    )

    for domain_repo in (
        badges_repository,
        luckywheel_repository,
        gift_pack_repository,
    ):
        for col_name in domain_repo.REASSIGNED_TG_ID_COLUMNS:
            assert isinstance(col_name, str)
            parts = col_name.split(".")
            assert len(parts) == 2, f"Expected table.column format: {col_name}"


def test_badges_check_clean(session_env):
    """Clean check when old and new identities have no overlapping badges."""
    with get_session() as session:
        _ensure_stats(session, 1001, 1002)
        badge = Badge(
            badge_type="clean_badge",
            name="Clean Badge",
            description="Test",
            icon_url="https://example.com/icon.svg",
            credits_cost=10.0,
            bonus_percentage=0.1,
            valid_days=30,
            is_enabled=1,
            created_at=1000,
            updated_at=1000,
        )
        session.add(badge)
        session.flush()

        session.add(
            UserBadge(
                id=next_id(),
                tg_id=1001,
                badge_id=badge.id,
                credits_cost=10.0,
                redeemed_at=1000,
                expires_at=2000,
                is_active=1,
            )
        )
        session.flush()

        issues = badges_repository.check_tg_id_reassign_tx(session, 1001, 1002)
        assert issues == []

        # Same ID returns empty
        assert badges_repository.check_tg_id_reassign_tx(session, 1001, 1001) == []


def test_badges_check_conflicts_collect_all(session_env):
    """Conflict check collects all duplicate badge IDs into record_ids."""
    with get_session() as session:
        _ensure_stats(session, 1001, 1002)
        b1 = Badge(
            badge_type="b1",
            name="Badge 1",
            description="Test 1",
            icon_url="https://example.com/b1.svg",
            credits_cost=10.0,
            bonus_percentage=0.05,
            valid_days=30,
            is_enabled=1,
            created_at=1000,
            updated_at=1000,
        )
        b2 = Badge(
            badge_type="b2",
            name="Badge 2",
            description="Test 2",
            icon_url="https://example.com/b2.svg",
            credits_cost=20.0,
            bonus_percentage=0.10,
            valid_days=60,
            is_enabled=1,
            created_at=1000,
            updated_at=1000,
        )
        session.add_all([b1, b2])
        session.flush()

        # Both users hold both badges
        session.add_all(
            [
                UserBadge(
                    id=next_id(),
                    tg_id=1001,
                    badge_id=b1.id,
                    credits_cost=10.0,
                    redeemed_at=1000,
                    expires_at=2000,
                    is_active=1,
                ),
                UserBadge(
                    id=next_id(),
                    tg_id=1001,
                    badge_id=b2.id,
                    credits_cost=20.0,
                    redeemed_at=1000,
                    expires_at=2000,
                    is_active=1,
                ),
                UserBadge(
                    id=next_id(),
                    tg_id=1002,
                    badge_id=b1.id,
                    credits_cost=10.0,
                    redeemed_at=1100,
                    expires_at=2100,
                    is_active=1,
                ),
                UserBadge(
                    id=next_id(),
                    tg_id=1002,
                    badge_id=b2.id,
                    credits_cost=20.0,
                    redeemed_at=1100,
                    expires_at=2100,
                    is_active=1,
                ),
            ]
        )
        session.flush()

        issues = badges_repository.check_tg_id_reassign_tx(session, 1001, 1002)
        assert len(issues) == 1
        issue = issues[0]
        assert isinstance(issue, TgIdReassignIssue)
        assert issue.kind == "conflict"
        assert issue.domain == "badges"
        expected_ids = tuple(sorted([str(b1.id), str(b2.id)], key=int))
        assert issue.record_ids == expected_ids


def test_badges_reassign_tx(session_env):
    """Reassign user badges from old to new identity."""
    with get_session() as session:
        _ensure_stats(session, 1001, 1002)
        badge = Badge(
            badge_type="reassign_badge",
            name="Reassign Badge",
            description="Test",
            icon_url="https://example.com/icon.svg",
            credits_cost=15.0,
            bonus_percentage=0.15,
            valid_days=45,
            is_enabled=1,
            created_at=1000,
            updated_at=1000,
        )
        session.add(badge)
        session.flush()

        session.add(
            UserBadge(
                id=next_id(),
                tg_id=1001,
                badge_id=badge.id,
                credits_cost=15.0,
                redeemed_at=1000,
                expires_at=2000,
                is_active=1,
            )
        )
        session.flush()

        counts = badges_repository.reassign_tg_id_tx(session, 1001, 1002)
        assert counts == {"user_badges.tg_id": 1}

        # Check DB state
        old_badges = (
            session.execute(select(UserBadge).where(UserBadge.tg_id == 1001))
            .scalars()
            .all()
        )
        new_badges = (
            session.execute(select(UserBadge).where(UserBadge.tg_id == 1002))
            .scalars()
            .all()
        )
        assert len(old_badges) == 0
        assert len(new_badges) == 1
        assert new_badges[0].badge_id == badge.id


def test_gift_pack_check_clean(session_env):
    """Clean check when old and new identities have no overlapping claim states."""
    with get_session() as session:
        _ensure_stats(session, 2001, 2002)
        pack1 = GiftPack(
            id=next_id(),
            title="Pack 1",
            rewards="[]",
            start_at=1000,
            end_at=2000,
            created_at=1000,
            updated_at=1000,
        )
        pack2 = GiftPack(
            id=next_id(),
            title="Pack 2",
            rewards="[]",
            start_at=1000,
            end_at=2000,
            created_at=1000,
            updated_at=1000,
        )
        session.add_all([pack1, pack2])
        session.flush()

        # User 1 has state on pack 1, User 2 has state on pack 2
        session.add_all(
            [
                GiftPackUserState(
                    id=next_id(), pack_id=pack1.id, tg_id=2001, claimed_at=1500
                ),
                GiftPackUserState(
                    id=next_id(), pack_id=pack2.id, tg_id=2002, claimed_at=1500
                ),
            ]
        )
        session.flush()

        issues = gift_pack_repository.check_tg_id_reassign_tx(session, 2001, 2002)
        assert issues == []
        assert gift_pack_repository.check_tg_id_reassign_tx(session, 2001, 2001) == []


def test_gift_pack_check_conflicts_collect_all(session_env):
    """Conflict check collects all overlapping gift pack claim states."""
    with get_session() as session:
        _ensure_stats(session, 2001, 2002)
        pack1 = GiftPack(
            id=next_id(),
            title="Pack 1",
            rewards="[]",
            start_at=1000,
            end_at=2000,
            created_at=1000,
            updated_at=1000,
        )
        pack2 = GiftPack(
            id=next_id(),
            title="Pack 2",
            rewards="[]",
            start_at=1000,
            end_at=2000,
            created_at=1000,
            updated_at=1000,
        )
        session.add_all([pack1, pack2])
        session.flush()

        # Both users have state on pack 1 and pack 2
        session.add_all(
            [
                GiftPackUserState(
                    id=next_id(), pack_id=pack1.id, tg_id=2001, claimed_at=1500
                ),
                GiftPackUserState(
                    id=next_id(), pack_id=pack2.id, tg_id=2001, claimed_at=None
                ),
                GiftPackUserState(
                    id=next_id(), pack_id=pack1.id, tg_id=2002, claimed_at=1600
                ),
                GiftPackUserState(
                    id=next_id(), pack_id=pack2.id, tg_id=2002, claimed_at=1600
                ),
            ]
        )
        session.flush()

        issues = gift_pack_repository.check_tg_id_reassign_tx(session, 2001, 2002)
        assert len(issues) == 1
        issue = issues[0]
        assert isinstance(issue, TgIdReassignIssue)
        assert issue.kind == "conflict"
        assert issue.domain == "gift_pack"
        expected_ids = tuple(sorted([str(pack1.id), str(pack2.id)], key=int))
        assert issue.record_ids == expected_ids


def test_gift_pack_reassign_creator_claims_and_audience_dedup(session_env):
    """Reassign gift pack creator, claim states, and audience list with duplicate dedup."""
    with get_session() as session:
        _ensure_stats(session, 2001, 2002)

        # Audience JSON includes old ID (2001) and new ID (2002) plus other IDs
        audience_data = [
            {
                "type": "user_list",
                "mode": "include",
                "tg_ids": [2001, 9999, 2002, 8888],
            },
            {
                "type": "user_list",
                "mode": "exclude",
                "tg_ids": [2002, 2001],
            },
            {
                "type": "premium",
                "state": "active",
            },
        ]
        pack = GiftPack(
            id=next_id(),
            title="Audience Pack",
            rewards="[]",
            start_at=1000,
            end_at=2000,
            created_by=2001,
            audience=json.dumps(audience_data),
            created_at=1000,
            updated_at=1000,
        )
        session.add(pack)
        session.flush()

        session.add(
            GiftPackUserState(
                id=next_id(),
                pack_id=pack.id,
                tg_id=2001,
                claimed_at=1500,
            )
        )
        session.flush()

        counts = gift_pack_repository.reassign_tg_id_tx(session, 2001, 2002)
        assert counts == {
            "gift_pack.created_by": 1,
            "gift_pack_user_state.tg_id": 1,
            "gift_pack.audience": 1,
        }

        # Verify DB updates
        refreshed_pack = session.get(GiftPack, pack.id)
        assert refreshed_pack.created_by == 2002

        parsed_audience = json.loads(refreshed_pack.audience)
        include_list = parsed_audience[0]
        exclude_list = parsed_audience[1]
        premium_cond = parsed_audience[2]

        # 2001 replaced with 2002, duplicate 2002 deduped preserving order
        # Original: [2001, 9999, 2002, 8888] -> [2002, 9999, 8888]
        assert include_list["tg_ids"] == [2002, 9999, 8888]

        # Original: [2002, 2001] -> 2002 is first, 2001 becomes 2002 (duplicate dropped) -> [2002]
        assert exclude_list["tg_ids"] == [2002]

        assert premium_cond == {"type": "premium", "state": "active"}

        # User state moved to new ID
        old_states = (
            session.execute(
                select(GiftPackUserState).where(GiftPackUserState.tg_id == 2001)
            )
            .scalars()
            .all()
        )
        new_states = (
            session.execute(
                select(GiftPackUserState).where(GiftPackUserState.tg_id == 2002)
            )
            .scalars()
            .all()
        )
        assert len(old_states) == 0
        assert len(new_states) == 1


def test_luckywheel_check_and_reassign(session_env):
    """Luckywheel check returns empty and reassign migrates stats and free spins."""
    with get_session() as session:
        _ensure_stats(session, 3001, 3002)

        # Check always empty
        issues = luckywheel_repository.check_tg_id_reassign_tx(session, 3001, 3002)
        assert issues == []

        # Add WheelStats and LuckywheelFreeSpin rows
        stat1 = WheelStats(
            id=next_id(),
            tg_id=3001,
            item_name="credits_10",
            cost_credits=10.0,
            credits_change=10.0,
            timestamp=1000,
            date="2026-04-01",
            source="paid",
        )
        stat2 = WheelStats(
            id=next_id(),
            tg_id=3001,
            item_name="credits_20",
            cost_credits=10.0,
            credits_change=20.0,
            timestamp=1001,
            date="2026-04-01",
            source="paid",
        )
        spin1 = LuckywheelFreeSpin(
            tg_id=3001,
            source="blackjack",
            cost_credits_snapshot=0.0,
            wheel_stats_source="blackjack_free",
            granted_at_ms=1000,
            expires_at_ms=2000,
        )
        session.add_all([stat1, stat2, spin1])
        session.flush()

        counts = luckywheel_repository.reassign_tg_id_tx(session, 3001, 3002)
        assert counts == {
            "wheel_stats.tg_id": 2,
            "luckywheel_free_spins.tg_id": 1,
        }

        # Verify DB updates
        old_stats = (
            session.execute(select(WheelStats).where(WheelStats.tg_id == 3001))
            .scalars()
            .all()
        )
        new_stats = (
            session.execute(select(WheelStats).where(WheelStats.tg_id == 3002))
            .scalars()
            .all()
        )
        assert len(old_stats) == 0
        assert len(new_stats) == 2

        old_spins = (
            session.execute(
                select(LuckywheelFreeSpin).where(LuckywheelFreeSpin.tg_id == 3001)
            )
            .scalars()
            .all()
        )
        new_spins = (
            session.execute(
                select(LuckywheelFreeSpin).where(LuckywheelFreeSpin.tg_id == 3002)
            )
            .scalars()
            .all()
        )
        assert len(old_spins) == 0
        assert len(new_spins) == 1


def test_atomic_transaction_rollback_across_domains(session_env):
    """Simulate atomic rebind across the three domains rolling back on failure."""
    with get_session() as session:
        _ensure_stats(session, 4001, 4002)

        badge = Badge(
            badge_type="atomic_badge",
            name="Atomic Badge",
            description="Test",
            icon_url="https://example.com/icon.svg",
            credits_cost=10.0,
            bonus_percentage=0.1,
            valid_days=30,
            is_enabled=1,
            created_at=1000,
            updated_at=1000,
        )
        session.add(badge)
        session.flush()

        session.add(
            UserBadge(
                id=next_id(),
                tg_id=4001,
                badge_id=badge.id,
                credits_cost=10.0,
                redeemed_at=1000,
                expires_at=2000,
                is_active=1,
            )
        )
        stat = WheelStats(
            id=next_id(),
            tg_id=4001,
            item_name="credits_10",
            cost_credits=10.0,
            credits_change=10.0,
            timestamp=1000,
            date="2026-04-01",
            source="paid",
        )
        session.add(stat)
        session.flush()

    # In a new session, run partial migration inside nested savepoint/rollback
    with get_session() as session, session.begin_nested():
        c1 = badges_repository.reassign_tg_id_tx(session, 4001, 4002)
        c2 = luckywheel_repository.reassign_tg_id_tx(session, 4001, 4002)
        assert c1["user_badges.tg_id"] == 1
        assert c2["wheel_stats.tg_id"] == 1
        # Explicit rollback
        session.rollback()

    # Verify rows remained on 4001
    with get_session() as session:
        b_count = (
            session.execute(select(UserBadge).where(UserBadge.tg_id == 4001))
            .scalars()
            .all()
        )
        s_count = (
            session.execute(select(WheelStats).where(WheelStats.tg_id == 4001))
            .scalars()
            .all()
        )
        assert len(b_count) == 1
        assert len(s_count) == 1
