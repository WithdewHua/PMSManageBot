from sqlalchemy import BIGINT, SMALLINT, CheckConstraint, Float, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


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
    trade_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    crypto_type: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    actual_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    payment_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    block_transaction_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(SMALLINT, nullable=False, default=1)
    payment_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    expiration_time: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    updated_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_crypto_amount_positive"),
        CheckConstraint("status IN (1, 2, 3)", name="ck_crypto_status_valid"),
        Index("idx_crypto_order_user_status", "user_id", "status"),
        Index("idx_crypto_order_status_created", "status", "created_at"),
    )
