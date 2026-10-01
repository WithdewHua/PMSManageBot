"""
SQLAlchemy ORM models for PMSManageBot
"""

from sqlalchemy import BIGINT, SMALLINT, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PlexUser(Base):
    """Plex user model"""

    __tablename__ = "plex_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plex_id: Mapped[int | None] = mapped_column(
        BIGINT, unique=True, index=True, nullable=True
    )
    tg_id: Mapped[int | None] = mapped_column(
        BIGINT,
        unique=True,
        index=True,
        nullable=True,
        info={"tg_id": "user"},
    )
    credits: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    plex_email: Mapped[str | None] = mapped_column(
        String, unique=True, index=True, nullable=True
    )
    plex_username: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    all_lib: Mapped[int] = mapped_column(SMALLINT, default=0, nullable=False)
    unlock_time: Mapped[str | None] = mapped_column(String, nullable=True)
    watched_time: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    plex_line: Mapped[str | None] = mapped_column(String, nullable=True)
    is_premium: Mapped[int] = mapped_column(SMALLINT, default=0, nullable=False)
    premium_expiry_time: Mapped[str | None] = mapped_column(String, nullable=True)
    premium_status_updated_at: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    # Line schedule feature unlock
    line_schedule_unlocked: Mapped[int] = mapped_column(
        SMALLINT, default=0, nullable=False
    )  # 0=not unlocked, 1=unlocked
    line_schedule_unlock_time: Mapped[int | None] = mapped_column(
        BIGINT, nullable=True
    )  # Timestamp when unlocked
    # Last viewed time
    last_viewed_at: Mapped[int | None] = mapped_column(
        BIGINT, nullable=True
    )  # Timestamp of last viewing activity
    # Download/Sync permission unlock
    sync_unlocked: Mapped[int] = mapped_column(
        SMALLINT, default=0, nullable=False
    )  # 0=not unlocked, 1=unlocked
    sync_unlock_time: Mapped[int | None] = mapped_column(
        BIGINT, nullable=True
    )  # Timestamp when unlocked
    premium_traffic_debt_bytes: Mapped[int] = mapped_column(
        BIGINT, default=0, nullable=False
    )
    premium_traffic_debt_updated_date: Mapped[str | None] = mapped_column(
        String, nullable=True
    )


class EmbyUser(Base):
    """Emby user model"""

    __tablename__ = "emby_user"

    emby_username: Mapped[str] = mapped_column(String, primary_key=True)
    emby_id: Mapped[str | None] = mapped_column(
        String, unique=True, index=True, nullable=True
    )
    tg_id: Mapped[int | None] = mapped_column(
        BIGINT, unique=True, index=True, nullable=True, info={"tg_id": "user"}
    )
    emby_is_unlock: Mapped[int] = mapped_column(SMALLINT, default=0, nullable=False)
    emby_unlock_time: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    emby_watched_time: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    emby_credits: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    emby_line: Mapped[str | None] = mapped_column(String, nullable=True)
    is_premium: Mapped[int] = mapped_column(SMALLINT, default=0, nullable=False)
    premium_expiry_time: Mapped[str | None] = mapped_column(String, nullable=True)
    premium_status_updated_at: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    # Line schedule feature unlock
    line_schedule_unlocked: Mapped[int] = mapped_column(
        SMALLINT, default=0, nullable=False
    )  # 0=not unlocked, 1=unlocked
    line_schedule_unlock_time: Mapped[int | None] = mapped_column(
        BIGINT, nullable=True
    )  # Timestamp when unlocked
    # Last viewed time
    last_viewed_at: Mapped[int | None] = mapped_column(
        BIGINT, nullable=True
    )  # Timestamp of last viewing activity
    # Download permission unlock
    download_unlocked: Mapped[int] = mapped_column(
        SMALLINT, default=0, nullable=False
    )  # 0=not unlocked, 1=unlocked
    download_unlock_time: Mapped[int | None] = mapped_column(
        BIGINT, nullable=True
    )  # Timestamp when unlocked
    premium_traffic_debt_bytes: Mapped[int] = mapped_column(
        BIGINT, default=0, nullable=False
    )
    premium_traffic_debt_updated_date: Mapped[str | None] = mapped_column(
        String, nullable=True
    )


class Statistics(Base):
    """User statistics model"""

    __tablename__ = "statistics"

    tg_id: Mapped[int] = mapped_column(BIGINT, primary_key=True, info={"tg_id": "user"})
    donation: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    credits: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    # 争霸赛余额：21 点周损失返还的发放去向，仅可支付锦标赛报名费，
    # 不可提现、兑换或转移。与 credits 同行同事务更新——报名校验与扣款
    # 天然一致，无需跨行锁（若独立钱包表则报名时需锁两行，收益为零）
    tournament_wallet_credits: Mapped[float] = mapped_column(
        Float, default=0, server_default="0", nullable=False
    )
    # 连败计数：自最近一次判胜以来的现金局判负手数（平局与投降不改变）。
    # 存列而非从 blackjack_hand 回溯推导：每次结算都需读它，存储列 O(1)，
    # 反向扫描对长连败用户成本无界。救济金额落 blackjack_hand.relief_credits，
    # 故可离线对账
    blackjack_lose_streak: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    # 免费大转盘机会的累计手数（自上次转换后已结算的现金局手牌数，
    # 不分胜负）。周配额不存计数器——由 luckywheel_free_spins 行按
    # granted_at 推导，避免周界重置逻辑与漂移
    blackjack_hands_since_freespin: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )


class Overseerr(Base):
    """Overseerr user model"""

    __tablename__ = "overseerr"

    user_id: Mapped[int] = mapped_column(
        BIGINT, primary_key=True, info={"tg_id": False}
    )
    user_email: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    tg_id: Mapped[int | None] = mapped_column(
        BIGINT, index=True, nullable=True, info={"tg_id": "user"}
    )
