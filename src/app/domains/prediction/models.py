from sqlalchemy import (
    BIGINT,
    SMALLINT,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class PredictionMarket(Base):
    """预测市场题目。"""

    __tablename__ = "prediction_market"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(SMALLINT, nullable=False, default=1, index=True)
    result_option: Mapped[int | None] = mapped_column(SMALLINT, nullable=True)
    betting_deadline: Mapped[int | None] = mapped_column(
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

    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BIGINT, nullable=True, info={"tg_id": "admin"}
    )
    resolved_by: Mapped[int | None] = mapped_column(
        BIGINT, nullable=True, info={"tg_id": "admin"}
    )
    resolved_at: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
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
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    betting_deadline: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True)
    status: Mapped[int] = mapped_column(SMALLINT, nullable=False, default=0, index=True)
    submitter_tg_id: Mapped[int] = mapped_column(
        BIGINT, nullable=False, index=True, info={"tg_id": "user"}
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        BIGINT, nullable=True, info={"tg_id": "admin"}
    )
    reviewed_at: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_id: Mapped[int | None] = mapped_column(
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
    tg_id: Mapped[int] = mapped_column(
        BIGINT, nullable=False, index=True, info={"tg_id": "user"}
    )
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
