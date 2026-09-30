from sqlalchemy import (
    BIGINT,
    SMALLINT,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class LineCatalog(Base):
    """Line catalog model - ordinary and premium streaming backends."""

    __tablename__ = "line_catalog"

    id: Mapped[int] = mapped_column(
        BIGINT().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    tags: Mapped[str] = mapped_column(
        Text, default="[]", server_default="[]", nullable=False
    )
    free_open: Mapped[int] = mapped_column(
        SMALLINT, default=0, server_default="0", nullable=False
    )
    created_at: Mapped[int] = mapped_column(BIGINT, nullable=False)
    updated_at: Mapped[int] = mapped_column(BIGINT, nullable=False)

    __table_args__ = (
        UniqueConstraint("name", name="uq_line_catalog_name"),
        UniqueConstraint("kind", "position", name="uq_line_catalog_kind_position"),
        CheckConstraint("kind IN ('normal', 'premium')", name="ck_line_catalog_kind"),
        CheckConstraint("position >= 0", name="ck_line_catalog_position"),
        CheckConstraint(
            "free_open IN (0, 1) AND (free_open = 0 OR kind = 'premium')",
            name="ck_line_catalog_free_open",
        ),
    )


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
