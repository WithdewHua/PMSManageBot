from sqlalchemy import (
    BIGINT,
    SMALLINT,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class GiftPack(Base):
    """礼包定义 - 管理员配置的运营活动福利

    奖励项与领取资格以 JSON 文本存储，新增奖励类型只需改发放分发器，
    无需变更表结构。时间窗以 epoch 秒存储，与客户端时区无关。
    """

    __tablename__ = "gift_pack"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)  # 礼包标题
    description: Mapped[str | None] = mapped_column(Text, nullable=True)  # 礼包描述
    rewards: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # 奖励项 JSON: [{"type": "credits", "amount": 100}, ...]
    eligibility: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # 旧礼包的领取资格 JSON；只供读取兼容
    audience: Mapped[str | None] = mapped_column(Text, nullable=True)  # 受众条件 JSON
    requirements: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # 领取条件 JSON
    task_end_at: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    total_quantity: Mapped[int | None] = mapped_column(
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
    )  # 对单个用户的领取提醒次数上限
    max_task_prompt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )  # 旧礼包不发任务提醒；新礼包由请求 schema 默认设为 2
    notify_audience_on_start: Mapped[int] = mapped_column(
        SMALLINT, nullable=False, default=0, server_default="0"
    )
    is_enabled: Mapped[int] = mapped_column(
        SMALLINT, nullable=False, default=1
    )  # 1=启用, 0=停用
    expiry_notified: Mapped[int] = mapped_column(
        SMALLINT, nullable=False, default=0
    )  # 过期汇总通知是否已发送
    created_by: Mapped[int | None] = mapped_column(
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
        CheckConstraint(
            "task_end_at IS NULL OR (task_end_at > start_at AND task_end_at <= end_at)",
            name="ck_gift_pack_task_window",
        ),
        CheckConstraint(
            "max_task_prompt_count >= 0", name="ck_gift_pack_max_task_prompt_count"
        ),
        CheckConstraint(
            "notify_audience_on_start IN (0, 1)",
            name="ck_gift_pack_notify_audience_on_start",
        ),
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
    claimed_at: Mapped[int | None] = mapped_column(
        BIGINT, nullable=True
    )  # 领取时间戳，NULL 表示尚未领取
    reward_snapshot: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # 本次领取实际发放内容的 JSON 快照（审计凭据）
    last_prompted_at: Mapped[int | None] = mapped_column(
        BIGINT, nullable=True
    )  # 最后一次提醒时间戳
    prompt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # 已提醒次数
    audience_locked_at: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    task_prompt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_task_prompted_at: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    start_dm_sent_at: Mapped[int | None] = mapped_column(BIGINT, nullable=True)

    # Relationship
    pack = relationship("GiftPack", back_populates="user_states")

    __table_args__ = (
        UniqueConstraint("pack_id", "tg_id", name="uq_gift_pack_user"),
        CheckConstraint("prompt_count >= 0", name="ck_gift_pack_state_prompt_count"),
        CheckConstraint(
            "task_prompt_count >= 0", name="ck_gift_pack_state_task_prompt_count"
        ),
        Index("idx_gift_pack_state_user_claimed", "tg_id", "claimed_at"),
    )
