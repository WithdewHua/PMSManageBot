#!/usr/bin/env python3
"""
SQLAlchemy ORM models for PMSManageBot
"""

from typing import Optional

from sqlalchemy import (
    BIGINT,
    JSON,
    SMALLINT,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models"""

    pass


class PlexUser(Base):
    """Plex user model"""

    __tablename__ = "plex_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plex_id: Mapped[Optional[int]] = mapped_column(
        BIGINT, unique=True, index=True, nullable=True
    )
    tg_id: Mapped[Optional[int]] = mapped_column(
        BIGINT, unique=True, index=True, nullable=True
    )
    credits: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    plex_email: Mapped[Optional[str]] = mapped_column(
        String, unique=True, index=True, nullable=True
    )
    plex_username: Mapped[Optional[str]] = mapped_column(
        String, index=True, nullable=True
    )
    all_lib: Mapped[int] = mapped_column(SMALLINT, default=0, nullable=False)
    unlock_time: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    watched_time: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    plex_line: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_premium: Mapped[int] = mapped_column(SMALLINT, default=0, nullable=False)
    premium_expiry_time: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    premium_status_updated_at: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True
    )
    # Line schedule feature unlock
    line_schedule_unlocked: Mapped[int] = mapped_column(
        SMALLINT, default=0, nullable=False
    )  # 0=not unlocked, 1=unlocked
    line_schedule_unlock_time: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True
    )  # Timestamp when unlocked
    # Last viewed time
    last_viewed_at: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True
    )  # Timestamp of last viewing activity
    # Download/Sync permission unlock
    sync_unlocked: Mapped[int] = mapped_column(
        SMALLINT, default=0, nullable=False
    )  # 0=not unlocked, 1=unlocked
    sync_unlock_time: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True
    )  # Timestamp when unlocked
    premium_traffic_debt_bytes: Mapped[int] = mapped_column(
        BIGINT, default=0, nullable=False
    )
    premium_traffic_debt_updated_date: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )


class EmbyUser(Base):
    """Emby user model"""

    __tablename__ = "emby_user"

    emby_username: Mapped[str] = mapped_column(String, primary_key=True)
    emby_id: Mapped[Optional[str]] = mapped_column(
        String, unique=True, index=True, nullable=True
    )
    tg_id: Mapped[Optional[int]] = mapped_column(
        BIGINT, unique=True, index=True, nullable=True
    )
    emby_is_unlock: Mapped[int] = mapped_column(SMALLINT, default=0, nullable=False)
    emby_unlock_time: Mapped[Optional[int]] = mapped_column(BIGINT, nullable=True)
    emby_watched_time: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    emby_credits: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    emby_line: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_premium: Mapped[int] = mapped_column(SMALLINT, default=0, nullable=False)
    premium_expiry_time: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    premium_status_updated_at: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True
    )
    # Line schedule feature unlock
    line_schedule_unlocked: Mapped[int] = mapped_column(
        SMALLINT, default=0, nullable=False
    )  # 0=not unlocked, 1=unlocked
    line_schedule_unlock_time: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True
    )  # Timestamp when unlocked
    # Last viewed time
    last_viewed_at: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True
    )  # Timestamp of last viewing activity
    # Download permission unlock
    download_unlocked: Mapped[int] = mapped_column(
        SMALLINT, default=0, nullable=False
    )  # 0=not unlocked, 1=unlocked
    download_unlock_time: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True
    )  # Timestamp when unlocked
    premium_traffic_debt_bytes: Mapped[int] = mapped_column(
        BIGINT, default=0, nullable=False
    )
    premium_traffic_debt_updated_date: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )


class Invitation(Base):
    """Invitation code model"""

    __tablename__ = "invitation"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    owner: Mapped[int] = mapped_column(BIGINT, index=True, nullable=False)
    is_used: Mapped[int] = mapped_column(SMALLINT, default=0, nullable=False)
    used_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    service: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )  # Service used for redemption: plex, emby; NULL if not yet used
    plex_id: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True
    )  # Plex user ID after redemption
    emby_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )  # Emby user ID after redemption


class Statistics(Base):
    """User statistics model"""

    __tablename__ = "statistics"

    tg_id: Mapped[int] = mapped_column(BIGINT, primary_key=True)
    donation: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    credits: Mapped[float] = mapped_column(Float, default=0, nullable=False)


class Overseerr(Base):
    """Overseerr user model"""

    __tablename__ = "overseerr"

    user_id: Mapped[int] = mapped_column(BIGINT, primary_key=True)
    user_email: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    tg_id: Mapped[Optional[int]] = mapped_column(BIGINT, index=True, nullable=True)


class WheelStats(Base):
    """Wheel spin statistics model"""

    __tablename__ = "wheel_stats"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BIGINT, index=True, nullable=False)
    item_name: Mapped[str] = mapped_column(Text, nullable=False)
    cost_credits: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    credits_change: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True)
    date: Mapped[str] = mapped_column(Text, nullable=False, index=True)


class Auctions(Base):
    """Auction model"""

    __tablename__ = "auctions"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    starting_price: Mapped[float] = mapped_column(Float, nullable=False)
    current_price: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True)
    created_by: Mapped[int] = mapped_column(BIGINT, nullable=False)
    created_at: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True)
    is_active: Mapped[int] = mapped_column(SMALLINT, default=1, nullable=False)
    winner_id: Mapped[Optional[int]] = mapped_column(BIGINT, nullable=True)
    bid_count: Mapped[int] = mapped_column(BIGINT, default=0, nullable=False)

    # Relationship
    bids = relationship(
        "AuctionBids", back_populates="auction", cascade="all, delete-orphan"
    )


class AuctionBids(Base):
    """Auction bid model"""

    __tablename__ = "auction_bids"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    auction_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("auctions.id"), nullable=False, index=True
    )
    bidder_id: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True)
    bid_amount: Mapped[float] = mapped_column(Float, nullable=False)
    bid_time: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True)

    # Relationship
    auction = relationship("Auctions", back_populates="bids")


class LineTrafficStats(Base):
    """Line traffic statistics model"""

    __tablename__ = "line_traffic_stats"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    line: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    send_bytes: Mapped[int] = mapped_column(BIGINT, nullable=False)
    service: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    event_hash: Mapped[str] = mapped_column(Text, nullable=False)
    request_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    upstream: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    upstream_response_time: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("event_hash", name="uq_line_traffic_event_hash"),
        Index("idx_line_traffic_service_user_time", "service", "username", "timestamp"),
        Index("idx_line_traffic_line_time", "line", "timestamp"),
        Index("idx_line_traffic_line_stats", "line", "timestamp", "send_bytes"),
    )


class LineTrafficMonthlyStats(Base):
    """Monthly line traffic statistics model"""

    __tablename__ = "line_traffic_monthly_stats"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    line: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    service: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    year_month: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    total_bytes: Mapped[int] = mapped_column(BIGINT, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "line",
            "service",
            "username",
            "year_month",
            name="uq_line_service_username_month",
        ),
        Index(
            "idx_monthly_traffic_service_user_month",
            "service",
            "username",
            "year_month",
        ),
        Index("idx_monthly_traffic_line_month", "line", "year_month"),
        Index("idx_monthly_traffic_line_stats", "line", "year_month", "total_bytes"),
    )


class TreasureIssue(Base):
    """夺宝期数（Issue）

    - 每期发布一个奖项，设定总需份数（如 120），每份对应一个幸运号码。
    - 满员后立即开奖并自动结算。
    """

    __tablename__ = "treasure_issue"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)

    # 展示信息
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 规则信息
    prize_credits: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 奖池（发给中奖者）
    total_credits_required: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 总需积分（参与者总支付），差额为系统回收
    credits_per_share: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    total_shares: Mapped[int] = mapped_column(Integer, nullable=False)
    start_number: Mapped[int] = mapped_column(Integer, nullable=False, default=10000001)

    # 状态
    status: Mapped[int] = mapped_column(
        SMALLINT, nullable=False, default=1
    )  # 1=进行中 2=已开奖 3=已取消
    shares_sold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 开奖结果
    external_random_b: Mapped[Optional[int]] = mapped_column(BIGINT, nullable=True)
    winner_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    winner_tg_id: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True, index=True
    )
    settled_at: Mapped[Optional[int]] = mapped_column(BIGINT, nullable=True)  # 秒时间戳

    created_by: Mapped[Optional[int]] = mapped_column(BIGINT, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    participations = relationship(
        "TreasureParticipation",
        back_populates="issue",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("prize_credits > 0", name="ck_treasure_issue_prize_gt_0"),
        CheckConstraint(
            "total_credits_required >= prize_credits",
            name="ck_treasure_issue_total_ge_prize",
        ),
        CheckConstraint(
            "credits_per_share > 0",
            name="ck_treasure_issue_credits_per_share_gt_0",
        ),
        CheckConstraint("total_shares > 0", name="ck_treasure_issue_total_shares_gt_0"),
    )


class TreasureParticipation(Base):
    """夺宝参与记录

    - 一条记录代表用户领取了一个幸运号码。
    - created_at_ms：用于开奖算法 A 值采样（毫秒），同时落地 created_at 便于展示。
    """

    __tablename__ = "treasure_participation"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    issue_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("treasure_issue.id"), nullable=False, index=True
    )
    tg_id: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True)
    lucky_number: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_credits: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at_ms: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    issue = relationship("TreasureIssue", back_populates="participations")

    __table_args__ = (
        UniqueConstraint(
            "issue_id",
            "lucky_number",
            name="uq_treasure_participation_issue_number",
        ),
        Index(
            "idx_treasure_participation_issue_time",
            "issue_id",
            "created_at_ms",
        ),
    )


class PredictionMarket(Base):
    """预测市场题目。"""

    __tablename__ = "prediction_market"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(SMALLINT, nullable=False, default=1, index=True)
    result_option: Mapped[Optional[int]] = mapped_column(SMALLINT, nullable=True)
    betting_deadline: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True, index=True
    )

    real_yes_pool: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    real_no_pool: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    virtual_yes_pool: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    virtual_no_pool: Mapped[int] = mapped_column(Integer, nullable=False, default=500)

    fee_rate_bp: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    fee_burn_bp: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    fee_glory_bp: Mapped[int] = mapped_column(Integer, nullable=False, default=200)

    max_bet_per_user: Mapped[int] = mapped_column(Integer, nullable=False, default=500)

    total_fee_collected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fee_burned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fee_to_glory: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    resolution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(BIGINT, nullable=True)
    resolved_by: Mapped[Optional[int]] = mapped_column(BIGINT, nullable=True)
    resolved_at: Mapped[Optional[int]] = mapped_column(BIGINT, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    bets = relationship(
        "PredictionBet", back_populates="market", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("status IN (1,2,3,4)", name="ck_prediction_market_status"),
        CheckConstraint(
            "result_option IS NULL OR result_option IN (0,1)",
            name="ck_prediction_market_result_option",
        ),
        CheckConstraint(
            "real_yes_pool >= 0", name="ck_prediction_market_real_yes_nonneg"
        ),
        CheckConstraint(
            "real_no_pool >= 0", name="ck_prediction_market_real_no_nonneg"
        ),
        CheckConstraint(
            "virtual_yes_pool >= 0", name="ck_prediction_market_virtual_yes_nonneg"
        ),
        CheckConstraint(
            "virtual_no_pool >= 0", name="ck_prediction_market_virtual_no_nonneg"
        ),
        CheckConstraint(
            "fee_rate_bp >= 0 AND fee_rate_bp <= 10000",
            name="ck_prediction_market_fee_rate_bp",
        ),
        CheckConstraint(
            "fee_burn_bp >= 0 AND fee_burn_bp <= 10000",
            name="ck_prediction_market_fee_burn_bp",
        ),
        CheckConstraint(
            "fee_glory_bp >= 0 AND fee_glory_bp <= 10000",
            name="ck_prediction_market_fee_glory_bp",
        ),
        CheckConstraint(
            "fee_burn_bp + fee_glory_bp = fee_rate_bp",
            name="ck_prediction_market_fee_split",
        ),
        CheckConstraint(
            "max_bet_per_user > 0", name="ck_prediction_market_max_bet_per_user"
        ),
    )


class PredictionMarketSubmission(Base):
    """用户提交的预测题目（待管理员审核）。"""

    __tablename__ = "prediction_market_submission"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    betting_deadline: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True)
    status: Mapped[int] = mapped_column(SMALLINT, nullable=False, default=0, index=True)
    submitter_tg_id: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True)
    reviewed_by: Mapped[Optional[int]] = mapped_column(BIGINT, nullable=True)
    reviewed_at: Mapped[Optional[int]] = mapped_column(BIGINT, nullable=True)
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    market_id: Mapped[Optional[int]] = mapped_column(
        BIGINT, ForeignKey("prediction_market.id"), nullable=True, index=True
    )
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN (0,1,2)", name="ck_prediction_market_submission_status"
        ),
        CheckConstraint(
            "betting_deadline > 0",
            name="ck_prediction_market_submission_deadline_gt_0",
        ),
    )


class PredictionBet(Base):
    """预测市场押注记录。"""

    __tablename__ = "prediction_bet"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("prediction_market.id"), nullable=False, index=True
    )
    tg_id: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True)
    option: Mapped[int] = mapped_column(SMALLINT, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    market = relationship("PredictionMarket", back_populates="bets")

    __table_args__ = (
        CheckConstraint("option IN (0,1)", name="ck_prediction_bet_option"),
        CheckConstraint("amount > 0", name="ck_prediction_bet_amount_gt_0"),
        Index("idx_prediction_bet_market_user", "market_id", "tg_id"),
        Index("idx_prediction_bet_market_option", "market_id", "option"),
    )


class DonationRegistrations(Base):
    """Donation registration model"""

    __tablename__ = "donation_registrations"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("statistics.tg_id", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    payment_method: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    admin_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    processed_at: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processed_by: Mapped[Optional[int]] = mapped_column(
        BIGINT, ForeignKey("statistics.tg_id", onupdate="CASCADE"), nullable=True
    )
    is_donation_registration: Mapped[int] = mapped_column(
        SMALLINT, default=0, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "payment_method IN ('wechat', 'alipay', 'bank', 'other')",
            name="ck_payment_method",
        ),
        CheckConstraint("amount > 0", name="ck_amount_positive"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')", name="ck_status_valid"
        ),
        CheckConstraint(
            "is_donation_registration IN (0, 1)", name="ck_is_donation_registration"
        ),
        Index("idx_donation_user_status", "user_id", "status"),
        Index("idx_donation_status_created", "status", "created_at"),
    )


class CryptoDonationOrders(Base):
    """Crypto donation order model"""

    __tablename__ = "crypto_donation_orders"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("statistics.tg_id", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    trade_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)
    crypto_type: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    actual_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    payment_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    block_transaction_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(SMALLINT, nullable=False, default=1)
    payment_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expiration_time: Mapped[Optional[int]] = mapped_column(BIGINT, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    updated_at: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    paid_at: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_crypto_amount_positive"),
        CheckConstraint("status IN (1, 2, 3)", name="ck_crypto_status_valid"),
        Index("idx_crypto_order_user_status", "user_id", "status"),
        Index("idx_crypto_order_status_created", "status", "created_at"),
    )


class VaultwardenRedeemRecords(Base):
    """Vaultwarden redeem records model"""

    __tablename__ = "vaultwarden_redeem_records"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("statistics.tg_id", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    credits_cost: Mapped[float] = mapped_column(Float, nullable=False)
    redeem_date: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True)

    __table_args__ = (
        CheckConstraint("credits_cost > 0", name="ck_vw_credits_cost_positive"),
        Index("idx_vw_redeem_tg_date", "tg_id", "redeem_date"),
        Index("idx_vw_redeem_email_date", "email", "redeem_date"),
    )


class SystemConfig(Base):
    """System configuration model - unified config storage

    Supports different config types:
    - free_premium_line: Free premium lines (key=line_name, value=enabled)
    - line_tag: Line tags (key=line_name, value=comma-separated tags)
    - lucky_wheel: Lucky wheel config (key=config/randomness_config, value=json)
    """

    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    config_type: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )  # 配置类型: free_premium_line, line_tag, lucky_wheel
    config_key: Mapped[str] = mapped_column(String, nullable=False)  # 配置键
    config_value: Mapped[str] = mapped_column(Text, nullable=False)  # 配置值
    created_at: Mapped[int] = mapped_column(BIGINT, nullable=False)
    updated_at: Mapped[int] = mapped_column(BIGINT, nullable=False)

    __table_args__ = (
        UniqueConstraint("config_type", "config_key", name="uq_config_type_key"),
        Index("idx_config_type_key", "config_type", "config_key"),
    )


class LineSchedule(Base):
    """Line schedule model - time-based line binding"""

    __tablename__ = "line_schedule"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("statistics.tg_id", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    service: Mapped[str] = mapped_column(
        String, nullable=False
    )  # Service type: plex or emby
    line: Mapped[str] = mapped_column(String, nullable=False)  # Line name
    days_of_week: Mapped[str] = mapped_column(
        String, nullable=False, server_default=""
    )  # Comma-separated days: 0-6 (0=Monday, 6=Sunday)
    start_time: Mapped[str] = mapped_column(
        String, nullable=False, server_default="00:00"
    )  # HH:MM format
    end_time: Mapped[str] = mapped_column(
        String, nullable=False, server_default="00:00"
    )  # HH:MM format
    priority: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )  # Lower number = higher priority
    is_enabled: Mapped[int] = mapped_column(
        SMALLINT, default=1, nullable=False
    )  # 1=enabled, 0=disabled
    created_at: Mapped[int] = mapped_column(BIGINT, nullable=False)
    updated_at: Mapped[int] = mapped_column(BIGINT, nullable=False)

    __table_args__ = (
        CheckConstraint("service IN ('plex', 'emby')", name="ck_schedule_service"),
        CheckConstraint("is_enabled IN (0, 1)", name="ck_schedule_enabled"),
        Index("idx_schedule_user_service", "tg_id", "service"),
        Index("idx_schedule_user_service_enabled", "tg_id", "service", "is_enabled"),
    )


class Badge(Base):
    """Badge model - anniversary badges and other achievements"""

    __tablename__ = "badges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    badge_type: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )  # Badge type: anniversary_4, anniversary_5, etc.
    name: Mapped[str] = mapped_column(String, nullable=False)  # Display name
    description: Mapped[str] = mapped_column(Text, nullable=False)  # Description
    icon_url: Mapped[str] = mapped_column(Text, nullable=False)  # Icon URL or SVG path
    credits_cost: Mapped[float] = mapped_column(
        Float, nullable=False
    )  # Credits required to redeem
    bonus_percentage: Mapped[float] = mapped_column(
        Float, nullable=False, default=0
    )  # Daily credits bonus percentage (e.g., 0.18 for 18%)
    valid_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=365
    )  # Valid for N days after redemption
    is_enabled: Mapped[int] = mapped_column(
        SMALLINT, default=1, nullable=False
    )  # 1=enabled, 0=disabled
    created_at: Mapped[int] = mapped_column(BIGINT, nullable=False)
    updated_at: Mapped[int] = mapped_column(BIGINT, nullable=False)

    # Relationship
    user_badges = relationship(
        "UserBadge", back_populates="badge", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("credits_cost >= 0", name="ck_badge_credits_cost_positive"),
        CheckConstraint(
            "bonus_percentage >= 0 AND bonus_percentage <= 1",
            name="ck_badge_bonus_percentage_valid",
        ),
        CheckConstraint("valid_days > 0", name="ck_badge_valid_days_positive"),
        CheckConstraint("is_enabled IN (0, 1)", name="ck_badge_enabled"),
    )


class UserBadge(Base):
    """User badge redemption records"""

    __tablename__ = "user_badges"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("statistics.tg_id", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    badge_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("badges.id"), nullable=False, index=True
    )
    credits_cost: Mapped[float] = mapped_column(
        Float, nullable=False
    )  # Actual credits cost at redemption time
    redeemed_at: Mapped[int] = mapped_column(
        BIGINT, nullable=False, index=True
    )  # Redemption timestamp
    expires_at: Mapped[int] = mapped_column(
        BIGINT, nullable=False, index=True
    )  # Bonus expiration timestamp (badge ownership is permanent)
    is_active: Mapped[int] = mapped_column(
        SMALLINT, default=1, nullable=False
    )  # 1=owned, 0=removed (badge ownership is permanent, only bonus expires)

    # Relationship
    badge = relationship("Badge", back_populates="user_badges")

    __table_args__ = (
        UniqueConstraint("tg_id", "badge_id", name="uq_user_badge"),
        CheckConstraint("credits_cost >= 0", name="ck_user_badge_credits_cost"),
        CheckConstraint("is_active IN (0, 1)", name="ck_user_badge_active"),
        Index("idx_user_badge_tg_active", "tg_id", "is_active"),
        Index("idx_user_badge_expires", "expires_at", "is_active"),
    )


class CustomLine(Base):
    """Custom line submission model - user submitted custom lines for admin approval"""

    __tablename__ = "custom_lines"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("statistics.tg_id", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )  # 提交用户的 Telegram ID
    domain: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )  # 线路域名（用于显示和绑定的唯一标识）
    network_info: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # 三网线路情况（电信/联通/移动等）
    price_monthly: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )  # 月付价格
    price_yearly: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )  # 年付价格
    traffic_limit: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )  # 每月流量限制 (GB)
    traffic_type: Mapped[str] = mapped_column(
        String, nullable=False, default="one_way"
    )  # 流量计算类型: one_way=单向, two_way=双向
    total_traffic: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )  # 总流量包 (GB)，用于计算流量单价
    valid_days: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # 可使用天数，NULL 表示长期
    is_permanent: Mapped[int] = mapped_column(
        SMALLINT, default=0, nullable=False
    )  # 1=长期可用, 0=有期限
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", index=True
    )  # 状态: pending=待审批, approved=已批准, rejected=已拒绝, expired=已过期, offline=已下线
    auto_offline_reason: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )  # 自动下线原因: traffic_exceeded=流量超限, None=用户主动下线或其他
    admin_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 管理员备注
    user_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 用户备注
    tags: Mapped[Optional[list]] = mapped_column(
        JSON, nullable=True
    )  # 标签列表（由管理员设置）
    approved_at: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True
    )  # 批准时间戳
    approved_by: Mapped[Optional[int]] = mapped_column(
        BIGINT, ForeignKey("statistics.tg_id", onupdate="CASCADE"), nullable=True
    )  # 批准管理员的 Telegram ID
    expires_at: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True, index=True
    )  # 过期时间戳
    expiry_notified_at: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True
    )  # 最后一次发送即将过期提醒的时间戳（用于避免重复通知）
    created_at: Mapped[int] = mapped_column(
        BIGINT, nullable=False, index=True
    )  # 创建时间戳
    updated_at: Mapped[int] = mapped_column(BIGINT, nullable=False)  # 更新时间戳

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'offline')",
            name="ck_custom_line_status",
        ),
        CheckConstraint(
            "traffic_type IN ('one_way', 'two_way')",
            name="ck_custom_line_traffic_type",
        ),
        CheckConstraint("is_permanent IN (0, 1)", name="ck_custom_line_permanent"),
        Index("idx_custom_line_user_status", "tg_id", "status"),
        Index("idx_custom_line_status_created", "status", "created_at"),
        Index("idx_custom_line_expires", "expires_at", "status"),
    )


class GhostSessionLog(Base):
    """Tautulli 幽灵会话清理留档

    Plex 在部分版本下不发送 WebSocket stop 事件，Tautulli 会保持会话开启直到
    超时或重启才写入 history，产生一条时长被严重夸大的记录。清理任务识别并
    从 Tautulli 删除这类记录后在此留档，用途有二：

      1. 作为补偿时长的可靠来源——记录已从 Tautulli 删除，无法再回溯；
      2. 作为审计日志，便于事后核查判定是否误伤。
    """

    __tablename__ = "ghost_session_log"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    row_id: Mapped[int] = mapped_column(
        BIGINT, nullable=False
    )  # Tautulli history 的 row_id
    user_id: Mapped[str] = mapped_column(
        Text, nullable=False, index=True
    )  # Plex user_id
    friendly_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rating_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started: Mapped[int] = mapped_column(BIGINT, nullable=False)  # 会话开始时间戳
    stopped: Mapped[int] = mapped_column(BIGINT, nullable=False)  # 会话结束时间戳
    play_date: Mapped[str] = mapped_column(
        Text, nullable=False, index=True
    )  # 归属日期 YYYY-MM-DD，按 started 取
    raw_seconds: Mapped[int] = mapped_column(
        BIGINT, nullable=False
    )  # Tautulli 记录的原始播放时长
    media_seconds: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True
    )  # 媒体自身时长
    percent_complete: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    compensated_seconds: Mapped[int] = mapped_column(
        BIGINT, nullable=False
    )  # 按播放进度还原的真实观看时长
    deleted: Mapped[int] = mapped_column(
        SMALLINT, nullable=False, default=0
    )  # 是否已从 Tautulli 删除
    compensated: Mapped[int] = mapped_column(
        SMALLINT, nullable=False, default=0
    )  # 补偿时长是否已计入积分结算
    created_at: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("row_id", name="uq_ghost_session_row_id"),
        CheckConstraint("deleted IN (0, 1)", name="ck_ghost_session_deleted"),
        CheckConstraint("compensated IN (0, 1)", name="ck_ghost_session_compensated"),
        Index("idx_ghost_session_user_date", "user_id", "play_date"),
        Index("idx_ghost_session_pending", "compensated", "deleted"),
    )


class GiftPack(Base):
    """礼包定义 - 管理员配置的运营活动福利

    奖励项与领取资格以 JSON 文本存储，新增奖励类型只需改发放分发器，
    无需变更表结构。时间窗以 epoch 秒存储，与客户端时区无关。
    """

    __tablename__ = "gift_pack"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)  # 礼包标题
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 礼包描述
    rewards: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # 奖励项 JSON: [{"type": "credits", "amount": 100}, ...]
    eligibility: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # 领取资格 JSON: {"min_credits": 50, "require_premium": false, "require_binding": "any"}
    total_quantity: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # 限量份数，NULL 表示不限量
    claimed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # 已领取份数
    start_at: Mapped[int] = mapped_column(
        BIGINT, nullable=False, index=True
    )  # 开始时间戳
    end_at: Mapped[int] = mapped_column(
        BIGINT, nullable=False, index=True
    )  # 结束时间戳
    max_prompt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )  # 对单个用户的提醒次数上限
    is_enabled: Mapped[int] = mapped_column(
        SMALLINT, nullable=False, default=1
    )  # 1=启用, 0=停用
    expiry_notified: Mapped[int] = mapped_column(
        SMALLINT, nullable=False, default=0
    )  # 过期汇总通知是否已发送
    created_by: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True
    )  # 创建管理员的 Telegram ID
    created_at: Mapped[int] = mapped_column(BIGINT, nullable=False)
    updated_at: Mapped[int] = mapped_column(BIGINT, nullable=False)

    # Relationship
    user_states = relationship(
        "GiftPackUserState", back_populates="pack", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("end_at > start_at", name="ck_gift_pack_window"),
        CheckConstraint("claimed_count >= 0", name="ck_gift_pack_claimed_count"),
        CheckConstraint(
            "total_quantity IS NULL OR total_quantity > 0",
            name="ck_gift_pack_total_quantity",
        ),
        CheckConstraint("max_prompt_count > 0", name="ck_gift_pack_max_prompt_count"),
        CheckConstraint("is_enabled IN (0, 1)", name="ck_gift_pack_enabled"),
        CheckConstraint(
            "expiry_notified IN (0, 1)", name="ck_gift_pack_expiry_notified"
        ),
        Index("idx_gift_pack_window_enabled", "start_at", "end_at", "is_enabled"),
        Index("idx_gift_pack_expiry_scan", "end_at", "expiry_notified"),
    )


class GiftPackUserState(Base):
    """礼包的用户维度状态 - 合并「领取」与「提醒」两件事

    两者的唯一键都是 (pack_id, tg_id)，本质是同一实体的不同字段，
    合并后判定是否提醒只需单表单次查询。行按需创建：仅在首次提醒
    或首次领取时插入，不预生成。`claimed_at IS NULL` 的行即「提醒了没领」。
    """

    __tablename__ = "gift_pack_user_state"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    pack_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("gift_pack.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tg_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("statistics.tg_id", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    claimed_at: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True
    )  # 领取时间戳，NULL 表示尚未领取
    reward_snapshot: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # 本次领取实际发放内容的 JSON 快照（审计凭据）
    last_prompted_at: Mapped[Optional[int]] = mapped_column(
        BIGINT, nullable=True
    )  # 最后一次提醒时间戳
    prompt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # 已提醒次数

    # Relationship
    pack = relationship("GiftPack", back_populates="user_states")

    __table_args__ = (
        UniqueConstraint("pack_id", "tg_id", name="uq_gift_pack_user"),
        CheckConstraint("prompt_count >= 0", name="ck_gift_pack_state_prompt_count"),
        Index("idx_gift_pack_state_user_claimed", "tg_id", "claimed_at"),
    )
