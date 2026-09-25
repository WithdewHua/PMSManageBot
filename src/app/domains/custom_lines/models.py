from sqlalchemy import (
    BIGINT,
    JSON,
    SMALLINT,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


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
    price_monthly: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # 月付价格
    price_yearly: Mapped[float | None] = mapped_column(Float, nullable=True)  # 年付价格
    traffic_limit: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # 每月流量限制 (GB)
    traffic_type: Mapped[str] = mapped_column(
        String, nullable=False, default="one_way"
    )  # 流量计算类型: one_way=单向, two_way=双向
    total_traffic: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # 总流量包 (GB)，用于计算流量单价
    valid_days: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 可使用天数，NULL 表示长期
    is_permanent: Mapped[int] = mapped_column(
        SMALLINT, default=0, nullable=False
    )  # 1=长期可用, 0=有期限
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", index=True
    )  # 状态: pending=待审批, approved=已批准, rejected=已拒绝, expired=已过期, offline=已下线
    auto_offline_reason: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # 自动下线原因: traffic_exceeded=流量超限, None=用户主动下线或其他
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 管理员备注
    user_note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 用户备注
    tags: Mapped[list | None] = mapped_column(
        JSON, nullable=True
    )  # 标签列表（由管理员设置）
    approved_at: Mapped[int | None] = mapped_column(BIGINT, nullable=True)  # 批准时间戳
    approved_by: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("statistics.tg_id", onupdate="CASCADE"), nullable=True
    )  # 批准管理员的 Telegram ID
    expires_at: Mapped[int | None] = mapped_column(
        BIGINT, nullable=True, index=True
    )  # 过期时间戳
    expiry_notified_at: Mapped[int | None] = mapped_column(
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
