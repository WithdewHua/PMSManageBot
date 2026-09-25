from sqlalchemy import BIGINT, SMALLINT, Float, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


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
    winner_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
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
