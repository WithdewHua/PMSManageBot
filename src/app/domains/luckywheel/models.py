from sqlalchemy import BIGINT, CheckConstraint, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class WheelStats(Base):
    """Wheel spin statistics model"""

    __tablename__ = "wheel_stats"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BIGINT, index=True, nullable=False)
    item_name: Mapped[str] = mapped_column(Text, nullable=False)
    cost_credits: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    credits_change: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True)
    date: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    # 参与来源：'paid'（正常付费）/ 'blackjack_free'（21 点打满手数获得的
    # 免费机会）/ 'gift_pack_free'（礼包发放的免费机会）。独立于 cost_credits
    # 标识——管理员把参与费调为 0 后，两者将无法区分，而免费机会的发放成本
    # 需要可审计
    source: Mapped[str | None] = mapped_column(
        Text, nullable=True, default="paid", server_default="paid"
    )


class LuckywheelFreeSpin(Base):
    """免费大转盘机会 - 一行代表一次获得

    来源由 source 区分：21 点打满手数（'blackjack'）、礼包发放（'gift_pack'）。
    消耗、概览、到期提醒对所有来源一视同仁；只针对 21 点的逻辑（周上限、
    获得通知、对账）按 source == 'blackjack' 过滤。发放与使用都留痕：
    used_at 为空即未用。过期作废由可用性查询的过滤实现（未用且未过期），
    行本身永久保留作发放台账——对账脚本按周核算让利率依赖它。

    周配额由「本周一以来的行数」推导而非计数器：任何计数器都需要周界
    重置逻辑，而「按 granted_at 过滤」天然正确且无漂移。

    免费机会不设使用时的最低积分门槛（普通转盘要求 ≥30）：参与费既已
    豁免，负分奖品的余额截断已提供保护——这正是跌破 21 点参与门槛后的
    回流路径：0 余额玩家转免费盘只会赢不会输。
    """

    __tablename__ = "luckywheel_free_spins"

    # Integer 而非 BIGINT：SQLite 上 BIGINT 主键不自增（见 conftest 注释），
    # 本表由结算事务内的生产代码插入（无显式 id），须两种方言都可自增。
    # 行量为「发放次数」量级（周上限封顶），Integer 无溢出之虞
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("statistics.tg_id", onupdate="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(Text, nullable=False, default="blackjack")
    cost_credits_snapshot: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, server_default="0"
    )
    wheel_stats_source: Mapped[str] = mapped_column(
        Text, nullable=False, default="blackjack_free", server_default="blackjack_free"
    )
    granted_at_ms: Mapped[int] = mapped_column(BIGINT, nullable=False)
    expires_at_ms: Mapped[int] = mapped_column(BIGINT, nullable=False)
    used_at_ms: Mapped[int | None] = mapped_column(BIGINT, nullable=True)

    __table_args__ = (
        # 周配额推导（tg_id + granted_at 前缀）与可用机会查询（tg_id 前缀）
        Index("idx_luckywheel_free_spins_user", "tg_id", "granted_at_ms"),
        # 到期提醒任务：扫次日将到期的未用行（行不删除，见类 docstring）
        Index("idx_luckywheel_free_spins_expiry", "expires_at_ms"),
        CheckConstraint(
            "expires_at_ms > granted_at_ms",
            name="ck_luckywheel_free_spins_expiry_after_grant",
        ),
    )
