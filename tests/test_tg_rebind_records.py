"""Tests for Telegram ID reassignment across the 9 record domains plus traffic model annotations."""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import get_session
from app.domains.auction import repository as auction_repo
from app.domains.auction.models import AuctionBids, Auctions
from app.domains.crypto_donation import repository as crypto_donation_repo
from app.domains.crypto_donation.models import CryptoDonationOrders
from app.domains.custom_lines import repository as custom_lines_repo
from app.domains.custom_lines.models import CustomLine, CustomLineSettlement
from app.domains.identity.models import Statistics
from app.domains.invitation import repository as invitation_repo
from app.domains.invitation.models import Invitation
from app.domains.lines import repository as lines_repo
from app.domains.lines.models import LineSchedule
from app.domains.prediction import repository as prediction_repo
from app.domains.prediction.models import (
    PredictionBet,
    PredictionMarket,
    PredictionMarketSubmission,
)
from app.domains.traffic.models import LineTrafficMonthlyStats, LineTrafficStats
from app.domains.treasure import repository as treasure_repo
from app.domains.treasure.models import TreasureIssue, TreasureParticipation
from app.domains.vaultwarden import repository as vaultwarden_repo
from app.domains.vaultwarden.models import VaultwardenRedeemRecords
from app.domains.watch_rewards import repository as watch_rewards_repo
from app.domains.watch_rewards.models import GhostSessionLog, WatchRewardSettlement

_next_id = 0


def next_id() -> int:
    global _next_id
    _next_id += 1
    return _next_id


RECORD_REPOSITORIES = [
    ("treasure", treasure_repo),
    ("prediction", prediction_repo),
    ("auction", auction_repo),
    ("invitation", invitation_repo),
    ("lines", lines_repo),
    ("custom_lines", custom_lines_repo),
    ("crypto_donation", crypto_donation_repo),
    ("vaultwarden", vaultwarden_repo),
    ("watch_rewards", watch_rewards_repo),
]


def test_repository_export_contracts():
    """Each repository exports REASSIGNED_TG_ID_COLUMNS, check_tg_id_reassign_tx, and reassign_tg_id_tx."""
    for domain_name, repo in RECORD_REPOSITORIES:
        assert hasattr(repo, "REASSIGNED_TG_ID_COLUMNS"), (
            f"{domain_name} missing REASSIGNED_TG_ID_COLUMNS"
        )
        cols = repo.REASSIGNED_TG_ID_COLUMNS
        assert isinstance(cols, tuple), (
            f"{domain_name} REASSIGNED_TG_ID_COLUMNS must be a tuple"
        )
        assert len(cols) > 0, (
            f"{domain_name} REASSIGNED_TG_ID_COLUMNS must not be empty"
        )
        for col in cols:
            assert isinstance(col, str), f"{domain_name} column {col} must be str"
            assert "." in col, (
                f"{domain_name} column {col} must follow 'table.column' format"
            )

        assert hasattr(repo, "check_tg_id_reassign_tx"), (
            f"{domain_name} missing check_tg_id_reassign_tx"
        )
        assert callable(repo.check_tg_id_reassign_tx)

        assert hasattr(repo, "reassign_tg_id_tx"), (
            f"{domain_name} missing reassign_tg_id_tx"
        )
        assert callable(repo.reassign_tg_id_tx)


def test_check_tg_id_reassign_tx_returns_empty_issues(session_env):
    """Record domains have no in-flight or unique conflict checks, returning an empty list."""
    old_tg_id = 11111
    new_tg_id = 22222
    with get_session() as session:
        for domain_name, repo in RECORD_REPOSITORIES:
            issues = repo.check_tg_id_reassign_tx(session, old_tg_id, new_tg_id)
            assert isinstance(issues, list), f"{domain_name} must return a list"
            assert issues == [], f"{domain_name} issues must be empty"


def test_model_column_info_labels():
    """Verify that all TG model columns are labeled with info 'user'/'admin' and suspicious non-TG with False."""
    assert TreasureParticipation.tg_id.property.columns[0].info.get("tg_id") == "user"
    assert TreasureIssue.winner_tg_id.property.columns[0].info.get("tg_id") == "user"
    assert TreasureIssue.created_by.property.columns[0].info.get("tg_id") == "admin"

    assert PredictionBet.tg_id.property.columns[0].info.get("tg_id") == "user"
    assert (
        PredictionMarketSubmission.submitter_tg_id.property.columns[0].info.get("tg_id")
        == "user"
    )
    assert (
        PredictionMarketSubmission.reviewed_by.property.columns[0].info.get("tg_id")
        == "admin"
    )
    assert PredictionMarket.created_by.property.columns[0].info.get("tg_id") == "admin"
    assert PredictionMarket.resolved_by.property.columns[0].info.get("tg_id") == "admin"

    assert AuctionBids.bidder_id.property.columns[0].info.get("tg_id") == "user"
    assert Auctions.winner_id.property.columns[0].info.get("tg_id") == "user"
    assert Auctions.created_by.property.columns[0].info.get("tg_id") == "admin"

    assert Invitation.owner.property.columns[0].info.get("tg_id") == "user"
    assert Invitation.used_by.property.columns[0].info.get("tg_id") is False

    assert LineSchedule.tg_id.property.columns[0].info.get("tg_id") == "user"

    assert CustomLine.tg_id.property.columns[0].info.get("tg_id") == "user"
    assert CustomLine.approved_by.property.columns[0].info.get("tg_id") == "admin"
    assert CustomLineSettlement.tg_id.property.columns[0].info.get("tg_id") == "user"

    assert CryptoDonationOrders.user_id.property.columns[0].info.get("tg_id") == "user"

    assert (
        VaultwardenRedeemRecords.tg_id.property.columns[0].info.get("tg_id") == "user"
    )

    assert WatchRewardSettlement.tg_id.property.columns[0].info.get("tg_id") == "user"
    assert (
        WatchRewardSettlement.inviter_tg_id.property.columns[0].info.get("tg_id")
        == "user"
    )
    assert GhostSessionLog.user_id.property.columns[0].info.get("tg_id") is False

    assert LineTrafficStats.user_id.property.columns[0].info.get("tg_id") is False
    assert (
        LineTrafficMonthlyStats.user_id.property.columns[0].info.get("tg_id") is False
    )


def test_reassign_treasure_records(session_env):
    old_tg_id = 10001
    new_tg_id = 20002
    other_tg_id = 30003

    with get_session() as session:
        issue1 = TreasureIssue(
            id=next_id(),
            title="Issue 1",
            prize_credits=100,
            total_credits_required=120,
            credits_per_share=10,
            total_shares=12,
            start_number=1001,
            status=2,
            shares_sold=12,
            winner_tg_id=old_tg_id,
            created_by=old_tg_id,
        )
        issue2 = TreasureIssue(
            id=next_id(),
            title="Issue 2",
            prize_credits=200,
            total_credits_required=240,
            credits_per_share=10,
            total_shares=24,
            start_number=2001,
            status=1,
            shares_sold=5,
            winner_tg_id=None,
            created_by=other_tg_id,
        )
        session.add_all([issue1, issue2])
        session.flush()

        part1 = TreasureParticipation(
            id=next_id(),
            issue_id=issue1.id,
            tg_id=old_tg_id,
            lucky_number=1001,
            cost_credits=10,
            created_at_ms=1000,
        )
        part2 = TreasureParticipation(
            id=next_id(),
            issue_id=issue2.id,
            tg_id=other_tg_id,
            lucky_number=2001,
            cost_credits=10,
            created_at_ms=2000,
        )
        session.add_all([part1, part2])
        session.flush()

        counts = treasure_repo.reassign_tg_id_tx(session, old_tg_id, new_tg_id)
        assert counts == {
            "treasure_participation.tg_id": 1,
            "treasure_issue.winner_tg_id": 1,
            "treasure_issue.created_by": 1,
        }

        # Verify no old residues
        assert (
            session.execute(
                select(TreasureParticipation).where(
                    TreasureParticipation.tg_id == old_tg_id
                )
            ).scalar_one_or_none()
            is None
        )
        assert (
            session.execute(
                select(TreasureIssue).where(TreasureIssue.winner_tg_id == old_tg_id)
            ).scalar_one_or_none()
            is None
        )
        assert (
            session.execute(
                select(TreasureIssue).where(TreasureIssue.created_by == old_tg_id)
            ).scalar_one_or_none()
            is None
        )

        # Verify new records
        reloaded_part = session.get(TreasureParticipation, part1.id)
        assert reloaded_part.tg_id == new_tg_id

        reloaded_issue1 = session.get(TreasureIssue, issue1.id)
        assert reloaded_issue1.winner_tg_id == new_tg_id
        assert reloaded_issue1.created_by == new_tg_id

        # Verify other untouched
        reloaded_issue2 = session.get(TreasureIssue, issue2.id)
        assert reloaded_issue2.created_by == other_tg_id


def test_reassign_prediction_records(session_env):
    old_tg_id = 10001
    new_tg_id = 20002
    other_tg_id = 30003

    with get_session() as session:
        market1 = PredictionMarket(
            id=next_id(),
            title="Market 1",
            created_by=old_tg_id,
            resolved_by=old_tg_id,
            status=2,
            result_option=1,
        )
        market2 = PredictionMarket(
            id=next_id(),
            title="Market 2",
            created_by=other_tg_id,
            resolved_by=None,
            status=1,
        )
        session.add_all([market1, market2])
        session.flush()

        sub1 = PredictionMarketSubmission(
            id=next_id(),
            title="Sub 1",
            betting_deadline=2000000,
            submitter_tg_id=old_tg_id,
            reviewed_by=old_tg_id,
            status=1,
            market_id=market1.id,
        )
        sub2 = PredictionMarketSubmission(
            id=next_id(),
            title="Sub 2",
            betting_deadline=3000000,
            submitter_tg_id=other_tg_id,
            reviewed_by=other_tg_id,
            status=1,
            market_id=market2.id,
        )
        session.add_all([sub1, sub2])
        session.flush()

        bet1 = PredictionBet(
            id=next_id(),
            market_id=market1.id,
            tg_id=old_tg_id,
            option=1,
            amount=50,
        )
        bet2 = PredictionBet(
            id=next_id(),
            market_id=market2.id,
            tg_id=other_tg_id,
            option=0,
            amount=20,
        )
        session.add_all([bet1, bet2])
        session.flush()

        counts = prediction_repo.reassign_tg_id_tx(session, old_tg_id, new_tg_id)
        assert counts == {
            "prediction_bet.tg_id": 1,
            "prediction_market_submission.submitter_tg_id": 1,
            "prediction_market_submission.reviewed_by": 1,
            "prediction_market.created_by": 1,
            "prediction_market.resolved_by": 1,
        }

        # Verify no old residues
        assert (
            session.execute(
                select(PredictionBet).where(PredictionBet.tg_id == old_tg_id)
            ).scalar_one_or_none()
            is None
        )
        assert (
            session.execute(
                select(PredictionMarketSubmission).where(
                    (PredictionMarketSubmission.submitter_tg_id == old_tg_id)
                    | (PredictionMarketSubmission.reviewed_by == old_tg_id)
                )
            ).scalar_one_or_none()
            is None
        )
        assert (
            session.execute(
                select(PredictionMarket).where(
                    (PredictionMarket.created_by == old_tg_id)
                    | (PredictionMarket.resolved_by == old_tg_id)
                )
            ).scalar_one_or_none()
            is None
        )

        # Verify new records
        reloaded_bet = session.get(PredictionBet, bet1.id)
        assert reloaded_bet.tg_id == new_tg_id

        reloaded_sub = session.get(PredictionMarketSubmission, sub1.id)
        assert reloaded_sub.submitter_tg_id == new_tg_id
        assert reloaded_sub.reviewed_by == new_tg_id

        reloaded_market = session.get(PredictionMarket, market1.id)
        assert reloaded_market.created_by == new_tg_id
        assert reloaded_market.resolved_by == new_tg_id

        # Verify other untouched
        reloaded_sub2 = session.get(PredictionMarketSubmission, sub2.id)
        assert reloaded_sub2.submitter_tg_id == other_tg_id
        assert reloaded_sub2.reviewed_by == other_tg_id


def test_reassign_auction_records(session_env):
    old_tg_id = 10001
    new_tg_id = 20002
    other_tg_id = 30003

    with get_session() as session:
        auction1 = Auctions(
            id=next_id(),
            title="Auction 1",
            description="Auction Desc 1",
            starting_price=10.0,
            current_price=50.0,
            end_time=2000000,
            created_by=old_tg_id,
            created_at=1000000,
            is_active=0,
            winner_id=old_tg_id,
            bid_count=2,
        )
        auction2 = Auctions(
            id=next_id(),
            title="Auction 2",
            description="Auction Desc 2",
            starting_price=20.0,
            current_price=20.0,
            end_time=3000000,
            created_by=other_tg_id,
            created_at=1000000,
            is_active=1,
            winner_id=None,
            bid_count=0,
        )
        session.add_all([auction1, auction2])
        session.flush()

        bid1 = AuctionBids(
            id=next_id(),
            auction_id=auction1.id,
            bidder_id=old_tg_id,
            bid_amount=50.0,
            bid_time=1500000,
        )
        bid2 = AuctionBids(
            id=next_id(),
            auction_id=auction1.id,
            bidder_id=other_tg_id,
            bid_amount=30.0,
            bid_time=1400000,
        )
        session.add_all([bid1, bid2])
        session.flush()

        counts = auction_repo.reassign_tg_id_tx(session, old_tg_id, new_tg_id)
        assert counts == {
            "auction_bids.bidder_id": 1,
            "auctions.winner_id": 1,
            "auctions.created_by": 1,
        }

        # Verify no old residues
        assert (
            session.execute(
                select(AuctionBids).where(AuctionBids.bidder_id == old_tg_id)
            ).scalar_one_or_none()
            is None
        )
        assert (
            session.execute(
                select(Auctions).where(
                    (Auctions.winner_id == old_tg_id)
                    | (Auctions.created_by == old_tg_id)
                )
            ).scalar_one_or_none()
            is None
        )

        # Verify new records
        reloaded_bid = session.get(AuctionBids, bid1.id)
        assert reloaded_bid.bidder_id == new_tg_id

        reloaded_auction = session.get(Auctions, auction1.id)
        assert reloaded_auction.winner_id == new_tg_id
        assert reloaded_auction.created_by == new_tg_id

        # Verify other untouched
        reloaded_bid2 = session.get(AuctionBids, bid2.id)
        assert reloaded_bid2.bidder_id == other_tg_id


def test_reassign_invitation_records_and_encoded_used_by(session_env):
    old_tg_id = 10001
    new_tg_id = 20002
    other_tg_id = 30003

    with get_session() as session:
        inv_owner = Invitation(
            code="code_owned_by_old",
            owner=old_tg_id,
            is_used=0,
        )
        inv_used_encoded_old = Invitation(
            code="code_redeemed_by_old_credits",
            owner=other_tg_id,
            is_used=1,
            used_by=f"credits_by_{old_tg_id}",
        )
        inv_used_encoded_other = Invitation(
            code="code_redeemed_by_other_credits",
            owner=other_tg_id,
            is_used=1,
            used_by=f"credits_by_{other_tg_id}",
        )
        inv_used_email = Invitation(
            code="code_redeemed_by_email",
            owner=other_tg_id,
            is_used=1,
            used_by="plex_user@example.com",
            service="plex",
        )
        session.add_all(
            [inv_owner, inv_used_encoded_old, inv_used_encoded_other, inv_used_email]
        )
        session.flush()

        counts = invitation_repo.reassign_tg_id_tx(session, old_tg_id, new_tg_id)
        assert counts == {
            "invitation.owner": 1,
            "invitation.used_by": 1,
        }

        # Verify no old residues
        assert (
            session.execute(
                select(Invitation).where(Invitation.owner == old_tg_id)
            ).scalar_one_or_none()
            is None
        )
        assert (
            session.execute(
                select(Invitation).where(
                    Invitation.used_by == f"credits_by_{old_tg_id}"
                )
            ).scalar_one_or_none()
            is None
        )

        # Verify rewritten
        reloaded_owner = session.get(Invitation, "code_owned_by_old")
        assert reloaded_owner.owner == new_tg_id

        reloaded_encoded = session.get(Invitation, "code_redeemed_by_old_credits")
        assert reloaded_encoded.used_by == f"credits_by_{new_tg_id}"

        # Verify other untouched
        reloaded_other = session.get(Invitation, "code_redeemed_by_other_credits")
        assert reloaded_other.used_by == f"credits_by_{other_tg_id}"

        reloaded_email = session.get(Invitation, "code_redeemed_by_email")
        assert reloaded_email.used_by == "plex_user@example.com"


def test_reassign_lines_schedule(session_env):
    old_tg_id = 10001
    new_tg_id = 20002
    other_tg_id = 30003

    with get_session() as session:
        session.add_all(
            [
                Statistics(tg_id=old_tg_id),
                Statistics(tg_id=new_tg_id),
                Statistics(tg_id=other_tg_id),
            ]
        )
        session.flush()

        sched1 = LineSchedule(
            id=next_id(),
            tg_id=old_tg_id,
            service="plex",
            line="normal_line_1",
            created_at=1000000,
            updated_at=1000000,
        )
        sched2 = LineSchedule(
            id=next_id(),
            tg_id=other_tg_id,
            service="emby",
            line="normal_line_2",
            created_at=1000000,
            updated_at=1000000,
        )
        session.add_all([sched1, sched2])
        session.flush()

        counts = lines_repo.reassign_tg_id_tx(session, old_tg_id, new_tg_id)
        assert counts == {
            "line_schedule.tg_id": 1,
        }

        # Verify no old residues
        assert (
            session.execute(
                select(LineSchedule).where(LineSchedule.tg_id == old_tg_id)
            ).scalar_one_or_none()
            is None
        )

        # Verify updated
        reloaded_sched1 = session.get(LineSchedule, sched1.id)
        assert reloaded_sched1.tg_id == new_tg_id

        # Verify other untouched
        reloaded_sched2 = session.get(LineSchedule, sched2.id)
        assert reloaded_sched2.tg_id == other_tg_id


def test_reassign_custom_lines_and_settlement(session_env):
    old_tg_id = 10001
    new_tg_id = 20002
    other_tg_id = 30003

    with get_session() as session:
        session.add_all(
            [
                Statistics(tg_id=old_tg_id),
                Statistics(tg_id=new_tg_id),
                Statistics(tg_id=other_tg_id),
            ]
        )
        session.flush()

        line1 = CustomLine(
            id=next_id(),
            tg_id=old_tg_id,
            domain="custom-old.com",
            network_info="info",
            created_at=1000000,
            updated_at=1000000,
        )
        line2 = CustomLine(
            id=next_id(),
            tg_id=other_tg_id,
            approved_by=old_tg_id,
            domain="custom-other.com",
            network_info="info",
            created_at=1000000,
            updated_at=1000000,
        )
        session.add_all([line1, line2])
        session.flush()

        settle1 = CustomLineSettlement(
            id=next_id(),
            line_id=line1.id,
            tg_id=old_tg_id,
            domain=line1.domain,
            year_month="2026-09",
            trigger="monthly",
            traffic_bytes=1000,
            credits=5.0,
            created_at=1000000,
        )
        settle2 = CustomLineSettlement(
            id=next_id(),
            line_id=line2.id,
            tg_id=other_tg_id,
            domain=line2.domain,
            year_month="2026-09",
            trigger="monthly",
            traffic_bytes=2000,
            credits=10.0,
            created_at=1000000,
        )
        session.add_all([settle1, settle2])
        session.flush()

        counts = custom_lines_repo.reassign_tg_id_tx(session, old_tg_id, new_tg_id)
        assert counts == {
            "custom_lines.tg_id": 1,
            "custom_lines.approved_by": 1,
            "custom_line_settlement.tg_id": 1,
        }

        # Verify no old residues
        assert (
            session.execute(
                select(CustomLine).where(
                    (CustomLine.tg_id == old_tg_id)
                    | (CustomLine.approved_by == old_tg_id)
                )
            ).scalar_one_or_none()
            is None
        )
        assert (
            session.execute(
                select(CustomLineSettlement).where(
                    CustomLineSettlement.tg_id == old_tg_id
                )
            ).scalar_one_or_none()
            is None
        )

        # Verify updated
        reloaded_line1 = session.get(CustomLine, line1.id)
        assert reloaded_line1.tg_id == new_tg_id

        reloaded_line2 = session.get(CustomLine, line2.id)
        assert reloaded_line2.approved_by == new_tg_id

        reloaded_settle1 = session.get(CustomLineSettlement, settle1.id)
        assert reloaded_settle1.tg_id == new_tg_id

        # Verify other untouched
        assert reloaded_line2.tg_id == other_tg_id
        reloaded_settle2 = session.get(CustomLineSettlement, settle2.id)
        assert reloaded_settle2.tg_id == other_tg_id


def test_reassign_crypto_donation_orders(session_env):
    old_tg_id = 10001
    new_tg_id = 20002
    other_tg_id = 30003

    with get_session() as session:
        session.add_all(
            [
                Statistics(tg_id=old_tg_id),
                Statistics(tg_id=new_tg_id),
                Statistics(tg_id=other_tg_id),
            ]
        )
        session.flush()

        order1 = CryptoDonationOrders(
            id=next_id(),
            user_id=old_tg_id,
            order_id="order_old",
            crypto_type="USDT",
            amount=10.0,
            created_at="2026-09-01T00:00:00",
        )
        order2 = CryptoDonationOrders(
            id=next_id(),
            user_id=other_tg_id,
            order_id="order_other",
            crypto_type="USDT",
            amount=20.0,
            created_at="2026-09-01T00:00:00",
        )
        session.add_all([order1, order2])
        session.flush()

        counts = crypto_donation_repo.reassign_tg_id_tx(session, old_tg_id, new_tg_id)
        assert counts == {
            "crypto_donation_orders.user_id": 1,
        }

        # Verify no old residues
        assert (
            session.execute(
                select(CryptoDonationOrders).where(
                    CryptoDonationOrders.user_id == old_tg_id
                )
            ).scalar_one_or_none()
            is None
        )

        # Verify updated
        reloaded_order1 = session.get(CryptoDonationOrders, order1.id)
        assert reloaded_order1.user_id == new_tg_id

        # Verify other untouched
        reloaded_order2 = session.get(CryptoDonationOrders, order2.id)
        assert reloaded_order2.user_id == other_tg_id


def test_reassign_vaultwarden_records(session_env):
    old_tg_id = 10001
    new_tg_id = 20002
    other_tg_id = 30003

    with get_session() as session:
        session.add_all(
            [
                Statistics(tg_id=old_tg_id),
                Statistics(tg_id=new_tg_id),
                Statistics(tg_id=other_tg_id),
            ]
        )
        session.flush()

        rec1 = VaultwardenRedeemRecords(
            id=next_id(),
            tg_id=old_tg_id,
            email="user_old@example.com",
            credits_cost=100.0,
            redeem_date="2026-09-01",
            created_at=1000000,
        )
        rec2 = VaultwardenRedeemRecords(
            id=next_id(),
            tg_id=other_tg_id,
            email="user_other@example.com",
            credits_cost=100.0,
            redeem_date="2026-09-01",
            created_at=1000000,
        )
        session.add_all([rec1, rec2])
        session.flush()

        counts = vaultwarden_repo.reassign_tg_id_tx(session, old_tg_id, new_tg_id)
        assert counts == {
            "vaultwarden_redeem_records.tg_id": 1,
        }

        # Verify no old residues
        assert (
            session.execute(
                select(VaultwardenRedeemRecords).where(
                    VaultwardenRedeemRecords.tg_id == old_tg_id
                )
            ).scalar_one_or_none()
            is None
        )

        # Verify updated
        reloaded_rec1 = session.get(VaultwardenRedeemRecords, rec1.id)
        assert reloaded_rec1.tg_id == new_tg_id

        # Verify other untouched
        reloaded_rec2 = session.get(VaultwardenRedeemRecords, rec2.id)
        assert reloaded_rec2.tg_id == other_tg_id


def test_reassign_watch_rewards_settlements(session_env):
    old_tg_id = 10001
    new_tg_id = 20002
    other_tg_id = 30003

    with get_session() as session:
        settle1 = WatchRewardSettlement(
            id=next_id(),
            service="plex",
            account_key="acc_1",
            settlement_date="2026-09-01",
            tg_id=old_tg_id,
            credits_delta=10.0,
            premium_charge=0.0,
            inviter_tg_id=other_tg_id,
            inviter_bonus=0.0,
            created_at=1000000,
        )
        settle2 = WatchRewardSettlement(
            id=next_id(),
            service="plex",
            account_key="acc_2",
            settlement_date="2026-09-01",
            tg_id=other_tg_id,
            credits_delta=10.0,
            premium_charge=0.0,
            inviter_tg_id=old_tg_id,
            inviter_bonus=5.0,
            created_at=1000000,
        )
        session.add_all([settle1, settle2])
        session.flush()

        counts = watch_rewards_repo.reassign_tg_id_tx(session, old_tg_id, new_tg_id)
        assert counts == {
            "watch_reward_settlement.tg_id": 1,
            "watch_reward_settlement.inviter_tg_id": 1,
        }

        # Verify no old residues
        assert (
            session.execute(
                select(WatchRewardSettlement).where(
                    (WatchRewardSettlement.tg_id == old_tg_id)
                    | (WatchRewardSettlement.inviter_tg_id == old_tg_id)
                )
            ).scalar_one_or_none()
            is None
        )

        # Verify updated
        reloaded1 = session.get(WatchRewardSettlement, settle1.id)
        assert reloaded1.tg_id == new_tg_id
        assert reloaded1.inviter_tg_id == other_tg_id

        reloaded2 = session.get(WatchRewardSettlement, settle2.id)
        assert reloaded2.tg_id == other_tg_id
        assert reloaded2.inviter_tg_id == new_tg_id


def test_reassign_zero_rows_when_no_match(session_env):
    """When old_tg_id has no records, reassign_tg_id_tx returns 0 for all columns."""
    non_existent_tg_id = 999999
    new_tg_id = 888888
    with get_session() as session:
        for domain_name, repo in RECORD_REPOSITORIES:
            counts = repo.reassign_tg_id_tx(session, non_existent_tg_id, new_tg_id)
            assert set(counts.keys()) == set(repo.REASSIGNED_TG_ID_COLUMNS), (
                f"{domain_name} keys must match REASSIGNED_TG_ID_COLUMNS"
            )
            for col, count in counts.items():
                assert count == 0, f"{domain_name}.{col} count must be 0"
