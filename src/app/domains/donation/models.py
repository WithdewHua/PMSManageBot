from sqlalchemy import BIGINT, SMALLINT, CheckConstraint, Float, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


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
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    processed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_by: Mapped[int | None] = mapped_column(
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
