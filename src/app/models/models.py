#!/usr/bin/env python3
"""
SQLAlchemy ORM models for PMSManageBot
"""

from typing import Optional

from sqlalchemy import (
    BIGINT,
    SMALLINT,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
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


class Invitation(Base):
    """Invitation code model"""

    __tablename__ = "invitation"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    owner: Mapped[int] = mapped_column(BIGINT, index=True, nullable=False)
    is_used: Mapped[int] = mapped_column(SMALLINT, default=0, nullable=False)
    used_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)


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

    __table_args__ = (
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


class DonationRegistrations(Base):
    """Donation registration model"""

    __tablename__ = "donation_registrations"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("statistics.tg_id"), nullable=False, index=True
    )
    payment_method: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    admin_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    processed_at: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processed_by: Mapped[Optional[int]] = mapped_column(
        BIGINT, ForeignKey("statistics.tg_id"), nullable=True
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
        BIGINT, ForeignKey("statistics.tg_id"), nullable=False, index=True
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
        BIGINT, ForeignKey("statistics.tg_id"), nullable=False, index=True
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
