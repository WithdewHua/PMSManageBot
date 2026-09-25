from sqlalchemy import BIGINT, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class LineTrafficStats(Base):
    """Line traffic statistics model"""

    __tablename__ = "line_traffic_stats"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    line: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    send_bytes: Mapped[int] = mapped_column(BIGINT, nullable=False)
    service: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    event_hash: Mapped[str] = mapped_column(Text, nullable=False)
    request_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    upstream: Mapped[str | None] = mapped_column(Text, nullable=True)
    upstream_response_time: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("event_hash", name="uq_line_traffic_event_hash"),
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
    user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
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
