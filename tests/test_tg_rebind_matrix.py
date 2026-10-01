"""End-to-end matrix tests for Telegram ID reassignment across backends."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest
from sqlalchemy import select, text

from app.domains.identity.models import EmbyUser, Overseerr, PlexUser, Statistics
from app.domains.tg_rebind import service as rebind_service
from app.domains.tg_rebind.exceptions import (
    TgRebindAccountNotFound,
    TgRebindRejected,
    TgRebindSameId,
)
from tests.refactor.tg_rebind_backends import rebind_backend
from tests.tg_rebind_fixture import (
    DEFAULT_NEW_TG_ID,
    DEFAULT_OLD_TG_ID,
    assert_no_old_tg_id_residues,
    seed_rebind_fixtures,
)

BACKEND_NAMES = ["sqlite-off", "sqlite-on"]
if os.environ.get("TG_REBIND_POSTGRES_URL"):
    BACKEND_NAMES.append("postgres")


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_rebind_new_id_all_columns_and_counts(backend_name: str) -> None:
    """Migrate all marked columns and encoded locations to a clean new Telegram ID."""
    with rebind_backend(backend_name) as backend:
        with backend.sessions() as session:
            seed_rebind_fixtures(session, seed_new_stats=False)
            session.commit()

        report = rebind_service.rebind(DEFAULT_NEW_TG_ID, from_tg_id=DEFAULT_OLD_TG_ID)

        assert report.old_tg_id == DEFAULT_OLD_TG_ID
        assert report.new_tg_id == DEFAULT_NEW_TG_ID
        assert report.dry_run is False
        assert report.total_rows == 42

        # Verify exact domain counts
        assert report.counts["credits"] == {"statistics.credits": 1}
        assert report.counts["donation"] == {
            "donation_registrations.user_id": 1,
            "donation_registrations.processed_by": 1,
            "statistics.donation": 1,
        }
        assert report.counts["badges"] == {"user_badges.tg_id": 1}
        assert report.counts["gift_pack"] == {
            "gift_pack.created_by": 1,
            "gift_pack_user_state.tg_id": 1,
            "gift_pack.audience": 1,
        }
        assert report.counts["luckywheel"] == {
            "wheel_stats.tg_id": 1,
            "luckywheel_free_spins.tg_id": 1,
        }

        # Verify no old residues remain
        with backend.sessions() as session:
            assert_no_old_tg_id_residues(session, DEFAULT_OLD_TG_ID)

            # Check new statistics row values
            stat = session.get(Statistics, DEFAULT_NEW_TG_ID)
            assert stat is not None
            assert stat.credits == 120.0
            assert stat.donation == 50.0
            assert stat.tournament_wallet_credits == 30.0
            assert stat.blackjack_lose_streak == 3
            assert stat.blackjack_hands_since_freespin == 5

            # Old statistics row must be deleted
            assert session.get(Statistics, DEFAULT_OLD_TG_ID) is None

        # Post-commit cache callbacks fired
        assert backend.cache_tracker.user_info_refreshed >= 1


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_rebind_merge_existing_balances_sum(backend_name: str) -> None:
    """Merging into an existing Telegram ID sums all balances and counters."""
    with rebind_backend(backend_name) as backend:
        with backend.sessions() as session:
            seed_rebind_fixtures(
                session,
                seed_new_stats=True,
                old_credits=120.0,
                new_credits=70.0,
                old_donation=50.0,
                new_donation=15.0,
                old_wallet=30.0,
                new_wallet=20.0,
                old_lose_streak=3,
                new_lose_streak=1,
                old_freespin_progress=5,
                new_freespin_progress=2,
            )
            session.commit()

        report = rebind_service.rebind(DEFAULT_NEW_TG_ID, from_tg_id=DEFAULT_OLD_TG_ID)
        assert report.total_rows == 42

        with backend.sessions() as session:
            assert_no_old_tg_id_residues(session, DEFAULT_OLD_TG_ID)

            stat = session.get(Statistics, DEFAULT_NEW_TG_ID)
            assert stat is not None
            assert stat.credits == 190.0  # 120 + 70
            assert stat.donation == 65.0  # 50 + 15
            assert stat.tournament_wallet_credits == 50.0  # 30 + 20
            assert stat.blackjack_lose_streak == 4  # 3 + 1
            assert stat.blackjack_hands_since_freespin == 7  # 5 + 2


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_rebind_negative_credits_overdraft(backend_name: str) -> None:
    """Overdrafted negative credit balances preserve debt upon merge."""
    with rebind_backend(backend_name) as backend:
        with backend.sessions() as session:
            seed_rebind_fixtures(
                session,
                seed_new_stats=True,
                old_credits=-25.0,
                new_credits=50.0,
            )
            session.commit()

        report = rebind_service.rebind(DEFAULT_NEW_TG_ID, from_tg_id=DEFAULT_OLD_TG_ID)
        assert report.total_rows == 42

        with backend.sessions() as session:
            stat = session.get(Statistics, DEFAULT_NEW_TG_ID)
            assert stat is not None
            assert stat.credits == 25.0  # 50.0 + (-25.0)


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_rebind_dry_run_leaves_database_and_caches_unchanged(
    backend_name: str,
) -> None:
    """Dry run produces the exact report counts but rolls back all DB and cache changes."""
    with rebind_backend(backend_name) as backend:
        with backend.sessions() as session:
            seed_rebind_fixtures(session, seed_new_stats=False)
            session.commit()

        dry_report = rebind_service.rebind(
            DEFAULT_NEW_TG_ID, from_tg_id=DEFAULT_OLD_TG_ID, dry_run=True
        )

        assert dry_report.dry_run is True
        assert dry_report.total_rows == 42
        assert dry_report.old_tg_id == DEFAULT_OLD_TG_ID
        assert dry_report.new_tg_id == DEFAULT_NEW_TG_ID

        # Verify DB is completely untouched: old ID exists, new ID does not
        with backend.sessions() as session:
            old_stat = session.get(Statistics, DEFAULT_OLD_TG_ID)
            new_stat = session.get(Statistics, DEFAULT_NEW_TG_ID)
            assert old_stat is not None
            assert old_stat.credits == 120.0
            assert new_stat is None

        # Verify zero cache callbacks were triggered
        assert backend.cache_tracker.user_info_refreshed == 0
        assert len(backend.cache_tracker.credits_invalidated) == 0


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_rebind_injected_late_failure_full_rollback(backend_name: str) -> None:
    """A failure right before commit causes complete transaction rollback."""
    with rebind_backend(backend_name) as backend:
        with backend.sessions() as session:
            seed_rebind_fixtures(session, seed_new_stats=False)
            session.commit()

        from app.domains.identity import repository as id_repo

        def _exploding_reassign(session, old_id, new_id):
            raise RuntimeError("Injected late database failure")

        with (
            patch.object(id_repo, "reassign_tg_id_tx", side_effect=_exploding_reassign),
            pytest.raises(RuntimeError, match="Injected late database failure"),
        ):
            rebind_service.rebind(DEFAULT_NEW_TG_ID, from_tg_id=DEFAULT_OLD_TG_ID)

        # Database must be unchanged
        with backend.sessions() as session:
            old_stat = session.get(Statistics, DEFAULT_OLD_TG_ID)
            new_stat = session.get(Statistics, DEFAULT_NEW_TG_ID)
            assert old_stat is not None
            assert old_stat.credits == 120.0
            assert new_stat is None

        # Cache callbacks discarded
        assert backend.cache_tracker.user_info_refreshed == 0


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_rebind_case_insensitive_media_locators(backend_name: str) -> None:
    """Plex email and Emby username locators match case-insensitively."""
    with rebind_backend(backend_name) as backend:
        with backend.sessions() as session:
            seed_rebind_fixtures(session, seed_new_stats=False)
            session.commit()

        # Locate by uppercase Plex email
        report1 = rebind_service.rebind(
            DEFAULT_NEW_TG_ID, plex_email="PLEX_101@EXAMPLE.COM"
        )
        assert report1.total_rows == 42
        assert report1.old_tg_id == DEFAULT_OLD_TG_ID

        # Prepare for second test: locate by uppercase Emby username
        # Re-seed under 202 and rebind to 303
        with backend.sessions() as session:
            stat303 = session.get(Statistics, 303)
            if not stat303:
                session.add(Statistics(tg_id=303, credits=0, donation=0))
            session.commit()

        report2 = rebind_service.rebind(303, emby_username="EMBY_USER_101")
        assert report2.total_rows == 42
        assert report2.old_tg_id == DEFAULT_NEW_TG_ID


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_rebind_unbound_media_accounts(backend_name: str) -> None:
    """Unbound media accounts migrate accumulated balance and bind to new ID."""
    with rebind_backend(backend_name) as backend:
        with backend.sessions() as session:
            session.add(Statistics(tg_id=9001, credits=0, donation=0))
            # Unbound Plex account
            session.add(
                PlexUser(
                    id=501,
                    plex_id=501,
                    tg_id=None,
                    credits=15.0,
                    plex_email="unbound_plex@test.com",
                    plex_username="unbound_plex",
                    all_lib=0,
                    watched_time=0.0,
                    is_premium=0,
                )
            )
            # Unbound Emby account
            session.add(
                EmbyUser(
                    emby_id="unbound_emby_502",
                    emby_username="unbound_emby",
                    tg_id=None,
                    emby_credits=25.0,
                    emby_is_unlock=0,
                    emby_watched_time=0.0,
                    is_premium=0,
                )
            )
            session.commit()

        # Rebind unbound Plex
        rep_plex = rebind_service.rebind(5010, plex_email="unbound_plex@test.com")
        assert rep_plex.counts["identity"] == {"plex_user.tg_id": 1}
        assert rep_plex.counts["credits"] == {
            "plex_user.credits": 1,
            "statistics.credits": 1,
        }

        # Rebind unbound Emby
        rep_emby = rebind_service.rebind(5020, emby_username="unbound_emby")
        assert rep_emby.counts["identity"] == {"emby_user.tg_id": 1}
        assert rep_emby.counts["credits"] == {
            "emby_user.emby_credits": 1,
            "statistics.credits": 1,
        }

        with backend.sessions() as session:
            p_acc = session.execute(
                select(PlexUser).where(PlexUser.plex_id == 501)
            ).scalar_one()
            assert p_acc.tg_id == 5010
            assert p_acc.credits == 0.0

            stat_plex = session.get(Statistics, 5010)
            assert stat_plex is not None
            assert stat_plex.credits == 15.0

            e_acc = session.execute(
                select(EmbyUser).where(EmbyUser.emby_id == "unbound_emby_502")
            ).scalar_one()
            assert e_acc.tg_id == 5020
            assert e_acc.emby_credits == 0.0

            stat_emby = session.get(Statistics, 5020)
            assert stat_emby is not None
            assert stat_emby.credits == 25.0


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_rebind_duplicate_media_conflicts_rejected(backend_name: str) -> None:
    """Conflicting media accounts between old and new identities are rejected."""
    # 1. Plex duplicate conflict
    with rebind_backend(backend_name) as backend:
        with backend.sessions() as session:
            seed_rebind_fixtures(session, seed_new_stats=True)
            # Add a Plex account to 202 as well
            session.add(
                PlexUser(
                    id=20202,
                    plex_id=20202,
                    tg_id=DEFAULT_NEW_TG_ID,
                    credits=0.0,
                    plex_email="plex_202@example.com",
                    plex_username="plex202",
                    all_lib=0,
                    watched_time=0.0,
                    is_premium=0,
                )
            )
            session.commit()

        with pytest.raises(TgRebindRejected) as exc_info:
            rebind_service.rebind(DEFAULT_NEW_TG_ID, from_tg_id=DEFAULT_OLD_TG_ID)
        assert any(
            issue.description == "new ID already owns a Plex account"
            for issue in exc_info.value.issues
        )

    # 2. Overseerr duplicate conflict
    with rebind_backend(backend_name) as backend:
        with backend.sessions() as session:
            seed_rebind_fixtures(session, seed_new_stats=True)
            # Add an Overseerr account to 202 as well
            session.add(
                Overseerr(
                    user_id=20202,
                    tg_id=DEFAULT_NEW_TG_ID,
                    user_email="overseerr_202@example.com",
                )
            )
            session.commit()

        with pytest.raises(TgRebindRejected) as exc_info:
            rebind_service.rebind(DEFAULT_NEW_TG_ID, from_tg_id=DEFAULT_OLD_TG_ID)
        assert any(
            issue.description == "both IDs own Overseerr accounts"
            for issue in exc_info.value.issues
        )


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_rebind_same_id_rejected(backend_name: str) -> None:
    """Rebinding to the same ID raises TgRebindSameId."""
    with rebind_backend(backend_name) as backend:
        with backend.sessions() as session:
            seed_rebind_fixtures(session)
            session.commit()

        with pytest.raises(TgRebindSameId):
            rebind_service.rebind(DEFAULT_OLD_TG_ID, from_tg_id=DEFAULT_OLD_TG_ID)


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_rebind_account_not_found(backend_name: str) -> None:
    """Unknown locator raises TgRebindAccountNotFound."""
    with rebind_backend(backend_name), pytest.raises(TgRebindAccountNotFound):
        rebind_service.rebind(DEFAULT_NEW_TG_ID, from_tg_id=9999999)


@pytest.mark.parametrize("backend_name", BACKEND_NAMES)
def test_encoded_audience_dedup_order_preserved(backend_name: str) -> None:
    """Gift pack audience JSON dedup preserves list order and replaces old with new ID."""
    with rebind_backend(backend_name) as backend:
        with backend.sessions() as session:
            seed_rebind_fixtures(session, seed_new_stats=False)
            session.commit()

        rebind_service.rebind(DEFAULT_NEW_TG_ID, from_tg_id=DEFAULT_OLD_TG_ID)

        with backend.sessions() as session:
            raw_aud = session.execute(
                text("SELECT audience FROM gift_pack WHERE id = 101")
            ).scalar_one()
            data = json.loads(raw_aud)
            user_list_cond = next(item for item in data if item["type"] == "user_list")
            # Original list was [101, 9999, 202, 8888]
            # Old 101 becomes 202; subsequent 202 duplicate is removed; 9999 and 8888 preserved
            assert user_list_cond["tg_ids"] == [DEFAULT_NEW_TG_ID, 9999, 8888]


def test_fixture_fails_loudly_on_new_table_without_override() -> None:
    """A new table with a marked tg_id column without an override fails loudly."""
    from sqlalchemy import Column, Integer, Table

    from app.core.db import Base

    synthetic = Table(
        "synthetic_unmapped_table",
        Base.metadata,
        Column("id", Integer, primary_key=True),
        Column("owner_tg_id", Integer, info={"tg_id": "user"}),
    )
    try:
        with (
            rebind_backend("sqlite-off") as backend,
            backend.sessions() as session,
            pytest.raises(
                AssertionError,
                match="New table with marked tg_id column has no valid override",
            ),
        ):
            seed_rebind_fixtures(session)
    finally:
        Base.metadata.remove(synthetic)


def test_fixture_automatically_covers_new_marked_field_in_existing_table() -> None:
    """A newly added marked column on an existing table is populated automatically."""
    from sqlalchemy import Column, Integer

    from app.core.db import Base

    table = Base.metadata.tables["wheel_stats"]
    new_col = Column(
        "secondary_user_id", Integer, nullable=True, info={"tg_id": "user"}
    )
    table.append_column(new_col)
    try:
        with rebind_backend("sqlite-off") as backend, backend.sessions() as session:
            seed_rebind_fixtures(session)
            session.commit()

            # Verify the new marked column was automatically populated with old_tg_id
            val = session.execute(
                text("SELECT secondary_user_id FROM wheel_stats WHERE id = 101")
            ).scalar_one()
            assert val == DEFAULT_OLD_TG_ID
    finally:
        # Remove dynamically added column from table
        table._columns.remove(new_col)
