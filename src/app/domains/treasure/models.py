from sqlalchemy import (
    BIGINT,
    SMALLINT,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class TreasureIssue(Base):
    """夺宝期数（Issue）

    - 每期发布一个奖项，设定总需份数（如 120），每份对应一个幸运号码。
    - 满员后立即开奖并自动结算。
    """

    __tablename__ = "treasure_issue"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)

    # 展示信息
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    external_random_b: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    winner_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    winner_tg_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True, index=True)
    settled_at: Mapped[int | None] = mapped_column(BIGINT, nullable=True)  # 秒时间戳
    auto_reopen_due_at: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    auto_reopen_issue_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)

    created_by: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
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
        Index(
            "ix_treasure_issue_reopen_due",
            "auto_reopen_due_at",
            "auto_reopen_issue_id",
        ),
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
