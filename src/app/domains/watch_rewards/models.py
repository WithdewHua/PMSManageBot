from sqlalchemy import (
    BIGINT,
    SMALLINT,
    CheckConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class GhostSessionLog(Base):
    """Tautulli 幽灵会话清理留档

    Plex 在部分版本下不发送 WebSocket stop 事件，Tautulli 会保持会话开启直到
    超时或重启才写入 history，产生一条时长被严重夸大的记录。清理任务识别并
    从 Tautulli 删除这类记录后在此留档，用途有二：

      1. 作为补偿时长的可靠来源——记录已从 Tautulli 删除，无法再回溯；
      2. 作为审计日志，便于事后核查判定是否误伤。
    """

    __tablename__ = "ghost_session_log"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    row_id: Mapped[int] = mapped_column(
        BIGINT, nullable=False
    )  # Tautulli history 的 row_id
    user_id: Mapped[str] = mapped_column(
        Text, nullable=False, index=True
    )  # Plex user_id
    friendly_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    rating_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    started: Mapped[int] = mapped_column(BIGINT, nullable=False)  # 会话开始时间戳
    stopped: Mapped[int] = mapped_column(BIGINT, nullable=False)  # 会话结束时间戳
    play_date: Mapped[str] = mapped_column(
        Text, nullable=False, index=True
    )  # 归属日期 YYYY-MM-DD，按 started 取
    raw_seconds: Mapped[int] = mapped_column(
        BIGINT, nullable=False
    )  # Tautulli 记录的原始播放时长
    media_seconds: Mapped[int | None] = mapped_column(
        BIGINT, nullable=True
    )  # 媒体自身时长
    percent_complete: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    compensated_seconds: Mapped[int] = mapped_column(
        BIGINT, nullable=False
    )  # 按播放进度还原的真实观看时长
    deleted: Mapped[int] = mapped_column(
        SMALLINT, nullable=False, default=0
    )  # 是否已从 Tautulli 删除
    compensated: Mapped[int] = mapped_column(
        SMALLINT, nullable=False, default=0
    )  # 补偿时长是否已计入积分结算
    created_at: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("row_id", name="uq_ghost_session_row_id"),
        CheckConstraint("deleted IN (0, 1)", name="ck_ghost_session_deleted"),
        CheckConstraint("compensated IN (0, 1)", name="ck_ghost_session_compensated"),
        Index("idx_ghost_session_user_date", "user_id", "play_date"),
        Index("idx_ghost_session_pending", "compensated", "deleted"),
    )
