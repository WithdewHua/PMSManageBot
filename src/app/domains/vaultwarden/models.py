from sqlalchemy import BIGINT, CheckConstraint, Float, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class VaultwardenRedeemRecords(Base):
    """Vaultwarden redeem records model"""

    __tablename__ = "vaultwarden_redeem_records"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("statistics.tg_id", onupdate="CASCADE"),
        nullable=False,
        index=True,
        info={"tg_id": "user"},
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
