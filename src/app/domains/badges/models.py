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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


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
