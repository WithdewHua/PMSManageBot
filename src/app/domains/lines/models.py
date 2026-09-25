from sqlalchemy import (
    BIGINT,
    SMALLINT,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class LineSchedule(Base):
    """Line schedule model - time-based line binding"""

    __tablename__ = "line_schedule"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("statistics.tg_id", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    service: Mapped[str] = mapped_column(
        String, nullable=False
    )  # Service type: plex or emby
    line: Mapped[str] = mapped_column(String, nullable=False)  # Line name
    days_of_week: Mapped[str] = mapped_column(
        String, nullable=False, server_default=""
    )  # Comma-separated days: 0-6 (0=Monday, 6=Sunday)
    start_time: Mapped[str] = mapped_column(
        String, nullable=False, server_default="00:00"
    )  # HH:MM format
    end_time: Mapped[str] = mapped_column(
        String, nullable=False, server_default="00:00"
    )  # HH:MM format
    priority: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )  # Lower number = higher priority
    is_enabled: Mapped[int] = mapped_column(
        SMALLINT, default=1, nullable=False
    )  # 1=enabled, 0=disabled
    created_at: Mapped[int] = mapped_column(BIGINT, nullable=False)
    updated_at: Mapped[int] = mapped_column(BIGINT, nullable=False)

    __table_args__ = (
        CheckConstraint("service IN ('plex', 'emby')", name="ck_schedule_service"),
        CheckConstraint("is_enabled IN (0, 1)", name="ck_schedule_enabled"),
        Index("idx_schedule_user_service", "tg_id", "service"),
        Index("idx_schedule_user_service_enabled", "tg_id", "service", "is_enabled"),
    )
