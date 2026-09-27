import json
import time
from datetime import datetime, timedelta
from math import isfinite

from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.db import get_session
from app.core.kv import SystemConfig
from app.core.log import logger
from app.domains.identity.models import Statistics
from app.domains.luckywheel.models import LuckywheelFreeSpin, WheelStats

FREE_SPIN_SOURCES = frozenset({"blackjack", "gift_pack"})


def grant_free_spins_tx(
    session,
    tg_id: int,
    count: int,
    *,
    source: str,
    granted_at_ms: int,
    expires_at_ms: int,
    cost_credits: float = 0.0,
    wheel_stats_source: str = "blackjack_free",
) -> list[LuckywheelFreeSpin]:
    """Grant free spins in a caller-owned transaction."""
    if int(count) <= 0:
        raise ValueError("free spin count must be positive")
    if source not in FREE_SPIN_SOURCES:
        raise ValueError(f"unsupported free spin source: {source}")
    if not wheel_stats_source.strip():
        raise ValueError("wheel stats source must not be empty")
    if int(expires_at_ms) <= int(granted_at_ms):
        raise ValueError("free spin expiry must be after grant time")
    normalized_cost = float(cost_credits)
    if not isfinite(normalized_cost) or normalized_cost < 0:
        raise ValueError("free spin cost must be finite and non-negative")

    rows = [
        LuckywheelFreeSpin(
            tg_id=int(tg_id),
            source=source,
            cost_credits_snapshot=normalized_cost,
            wheel_stats_source=wheel_stats_source,
            granted_at_ms=int(granted_at_ms),
            expires_at_ms=int(expires_at_ms),
        )
        for _ in range(int(count))
    ]
    session.add_all(rows)
    session.flush()
    return rows


def count_blackjack_freespins_since_tx(session, tg_id: int, since_ms: int) -> int:
    """Count blackjack-sourced free spins granted to a user since a timestamp."""
    return int(
        session.execute(
            select(func.count(LuckywheelFreeSpin.id)).where(
                LuckywheelFreeSpin.tg_id == int(tg_id),
                LuckywheelFreeSpin.source == "blackjack",
                LuckywheelFreeSpin.granted_at_ms >= int(since_ms),
            )
        ).scalar_one()
        or 0
    )


def consume_blackjack_freespin(tg_id: int) -> dict | None:
    """Atomically claim the earliest available free-spin ledger row."""
    now_ms = int(time.time() * 1000)
    try:
        with get_session() as session:
            spin_id = (
                session.execute(
                    select(LuckywheelFreeSpin.id)
                    .where(
                        LuckywheelFreeSpin.tg_id == int(tg_id),
                        LuckywheelFreeSpin.used_at_ms.is_(None),
                        LuckywheelFreeSpin.expires_at_ms > now_ms,
                    )
                    .order_by(LuckywheelFreeSpin.expires_at_ms, LuckywheelFreeSpin.id)
                    .limit(1)
                )
                .scalars()
                .one_or_none()
            )
            if spin_id is None:
                return None
            claimed = session.execute(
                update(LuckywheelFreeSpin)
                .where(
                    LuckywheelFreeSpin.id == int(spin_id),
                    LuckywheelFreeSpin.used_at_ms.is_(None),
                )
                .values(used_at_ms=now_ms)
            )
            if claimed.rowcount == 0:
                return None
            row = session.get(LuckywheelFreeSpin, int(spin_id))
            return {
                "id": int(spin_id),
                "expires_at_ms": int(row.expires_at_ms),
                "claimed_at_ms": now_ms,
                "source": row.source or "blackjack",
                "cost_credits_snapshot": float(row.cost_credits_snapshot or 0),
                "wheel_stats_source": row.wheel_stats_source
                or (
                    "gift_pack_free" if row.source == "gift_pack" else "blackjack_free"
                ),
            }
    except Exception as exc:
        logger.error(f"认领免费大转盘机会失败 (tg_id={tg_id}): {exc}")
        return None


def release_blackjack_freespin(spin_id: int, *, claimed_at_ms: int) -> bool:
    """Release a free-spin claim only when its CAS timestamp still matches."""
    try:
        with get_session() as session:
            released = session.execute(
                update(LuckywheelFreeSpin)
                .where(
                    LuckywheelFreeSpin.id == int(spin_id),
                    LuckywheelFreeSpin.used_at_ms == int(claimed_at_ms),
                )
                .values(used_at_ms=None)
            )
            return released.rowcount == 1
    except Exception as exc:
        logger.error(f"归还免费大转盘机会失败 (spin_id={spin_id}): {exc}")
        return False


def get_blackjack_freespin_summary(tg_id: int) -> dict:
    """Return free-spin availability and progress without importing blackjack."""
    now_ms = int(time.time() * 1000)
    try:
        with get_session() as session:
            raw = session.execute(
                select(SystemConfig.config_value).where(
                    SystemConfig.config_type == "blackjack",
                    SystemConfig.config_key == "config",
                )
            ).scalar_one_or_none()
            config = json.loads(raw) if raw else {}
            enabled = bool(config.get("freespins_enabled", True))
            threshold = int(config.get("freespins_hand_threshold", 20) or 0)
            spins = (
                session.execute(
                    select(LuckywheelFreeSpin.expires_at_ms)
                    .where(
                        LuckywheelFreeSpin.tg_id == int(tg_id),
                        LuckywheelFreeSpin.used_at_ms.is_(None),
                        LuckywheelFreeSpin.expires_at_ms > now_ms,
                    )
                    .order_by(LuckywheelFreeSpin.expires_at_ms)
                )
                .scalars()
                .all()
            )
            stats = session.get(Statistics, int(tg_id))
            hands = int(stats.blackjack_hands_since_freespin or 0) if stats else 0
        return {
            "enabled": enabled,
            "available": len(spins),
            "expires_at_ms_list": [int(value) for value in spins],
            "hands_since_freespin": hands,
            "hand_threshold": threshold,
        }
    except Exception as exc:
        logger.error(f"读取免费机会概览失败 (tg_id={tg_id}): {exc}")
        return {
            "enabled": False,
            "available": 0,
            "expires_at_ms_list": [],
            "hands_since_freespin": 0,
            "hand_threshold": 0,
        }


def grant_free_spins(
    tg_id: int,
    count: int,
    *,
    source: str,
    granted_at_ms: int,
    expires_at_ms: int,
    cost_credits: float = 0.0,
    wheel_stats_source: str = "blackjack_free",
) -> list[LuckywheelFreeSpin]:
    """Grant free spins in a repository-owned transaction."""
    with get_session() as session:
        return grant_free_spins_tx(
            session,
            tg_id,
            count,
            source=source,
            granted_at_ms=granted_at_ms,
            expires_at_ms=expires_at_ms,
            cost_credits=cost_credits,
            wheel_stats_source=wheel_stats_source,
        )


class LuckywheelRepository:
    def add_wheel_spin_record(
        self,
        tg_id: int,
        item_name: str,
        credits_change: float,
        cost_credits: float,
        source: str = "paid",
    ) -> bool:
        """记录转盘旋转记录。

        source 区分参与来源：'paid'（正常付费）/ 'blackjack_free'
        （21 点打满手数获得的免费机会）/ 'gift_pack_free'（礼包发放的免费机会）。免费机会的发放成本需要可审计，
        不能只靠 cost_credits=0 判断——管理员把参与费调为 0 后两者会混同。
        """
        try:
            with get_session() as session:
                timestamp = int(time.time())
                date = datetime.now(settings.TZ).strftime("%Y-%m-%d")

                wheel_record = WheelStats(
                    tg_id=tg_id,
                    item_name=item_name,
                    cost_credits=cost_credits,
                    credits_change=credits_change,
                    timestamp=timestamp,
                    date=date,
                    source=source,
                )
                session.add(wheel_record)
                return True
        except Exception as e:
            logger.error(f"Error adding wheel spin record: {e}")
            return False

    def get_wheel_stats(self) -> dict:
        """获取转盘统计数据"""
        try:
            with get_session() as session:
                today = datetime.now(settings.TZ).strftime("%Y-%m-%d")
                week_ago = (datetime.now(settings.TZ) - timedelta(days=7)).strftime(
                    "%Y-%m-%d"
                )

                # 总抽奖次数
                total_spins = session.execute(
                    select(func.count(WheelStats.id))
                ).scalar()

                # 参与用户数（去重）
                active_users = session.execute(
                    select(func.count(func.distinct(WheelStats.tg_id)))
                ).scalar()

                # 今日抽奖次数
                today_spins = session.execute(
                    select(func.count(WheelStats.id)).where(WheelStats.date == today)
                ).scalar()

                # 本周抽奖次数
                week_spins = session.execute(
                    select(func.count(WheelStats.id)).where(WheelStats.date >= week_ago)
                ).scalar()

                # 转盘总积分变化
                total_credits_change = (
                    session.execute(
                        select(func.sum(WheelStats.credits_change))
                    ).scalar()
                    or 0.0
                )

                # 转盘参与总消耗积分
                total_cost_credits = (
                    session.execute(select(func.sum(WheelStats.cost_credits))).scalar()
                    or 0.0
                )

                # 总邀请码发放数
                total_invite_codes = (
                    session.execute(
                        select(func.count(WheelStats.id)).where(
                            WheelStats.item_name == "邀请码 1 枚"
                        )
                    ).scalar()
                    or 0
                )

                return {
                    "totalSpins": total_spins,
                    "activeUsers": active_users,
                    "todaySpins": today_spins,
                    "lastWeekSpins": week_spins,
                    "totalCreditsChange": float(total_credits_change),
                    "totalCostCredits": float(total_cost_credits),
                    "totalInviteCodes": total_invite_codes,
                }
        except Exception as e:
            logger.error(f"Error getting wheel stats: {e}")
            return {
                "totalSpins": 0,
                "activeUsers": 0,
                "todaySpins": 0,
                "lastWeekSpins": 0,
                "totalCreditsChange": 0.0,
                "totalCostCredits": 0.0,
                "totalInviteCodes": 0,
            }

    def get_user_wheel_stats(self, tg_id: int) -> dict:
        """获取用户个人转盘统计数据"""
        try:
            with get_session() as session:
                today = datetime.now(settings.TZ).strftime("%Y-%m-%d")
                week_ago = (datetime.now(settings.TZ) - timedelta(days=7)).strftime(
                    "%Y-%m-%d"
                )

                # 用户今日游戏次数
                today_spins = session.execute(
                    select(func.count(WheelStats.id)).where(
                        WheelStats.tg_id == tg_id, WheelStats.date == today
                    )
                ).scalar()

                # 用户总游戏次数
                total_spins = session.execute(
                    select(func.count(WheelStats.id)).where(WheelStats.tg_id == tg_id)
                ).scalar()

                # 用户本周游戏次数
                week_spins = session.execute(
                    select(func.count(WheelStats.id)).where(
                        WheelStats.tg_id == tg_id, WheelStats.date >= week_ago
                    )
                ).scalar()

                # 用户总积分变化
                total_credits_change = (
                    session.execute(
                        select(func.sum(WheelStats.credits_change)).where(
                            WheelStats.tg_id == tg_id
                        )
                    ).scalar()
                    or 0.0
                )

                # 用户总参与消耗积分
                total_cost_credits = (
                    session.execute(
                        select(func.sum(WheelStats.cost_credits)).where(
                            WheelStats.tg_id == tg_id
                        )
                    ).scalar()
                    or 0.0
                )

                # 用户今日积分变化
                today_credits_change = (
                    session.execute(
                        select(func.sum(WheelStats.credits_change)).where(
                            WheelStats.tg_id == tg_id, WheelStats.date == today
                        )
                    ).scalar()
                    or 0.0
                )

                # 用户今日参与消耗积分
                today_cost_credits = (
                    session.execute(
                        select(func.sum(WheelStats.cost_credits)).where(
                            WheelStats.tg_id == tg_id, WheelStats.date == today
                        )
                    ).scalar()
                    or 0.0
                )

                # 用户本周积分变化
                week_credits_change = (
                    session.execute(
                        select(func.sum(WheelStats.credits_change)).where(
                            WheelStats.tg_id == tg_id, WheelStats.date >= week_ago
                        )
                    ).scalar()
                    or 0.0
                )

                # 用户本周参与消耗积分
                week_cost_credits = (
                    session.execute(
                        select(func.sum(WheelStats.cost_credits)).where(
                            WheelStats.tg_id == tg_id, WheelStats.date >= week_ago
                        )
                    ).scalar()
                    or 0.0
                )

                # 用户获得的邀请码数量
                invite_codes_earned = session.execute(
                    select(func.count(WheelStats.id)).where(
                        WheelStats.tg_id == tg_id, WheelStats.item_name == "邀请码 1 枚"
                    )
                ).scalar()

                # 用户今日获得的邀请码数量
                today_invite_codes = session.execute(
                    select(func.count(WheelStats.id)).where(
                        WheelStats.tg_id == tg_id,
                        WheelStats.item_name == "邀请码 1 枚",
                        WheelStats.date == today,
                    )
                ).scalar()

                # 用户本周获得的邀请码数量
                week_invite_codes = session.execute(
                    select(func.count(WheelStats.id)).where(
                        WheelStats.tg_id == tg_id,
                        WheelStats.item_name == "邀请码 1 枚",
                        WheelStats.date >= week_ago,
                    )
                ).scalar()

                # 最近5次游戏记录
                stmt = (
                    select(
                        WheelStats.item_name,
                        WheelStats.cost_credits,
                        WheelStats.credits_change,
                        WheelStats.date,
                        WheelStats.timestamp,
                    )
                    .where(WheelStats.tg_id == tg_id)
                    .order_by(WheelStats.timestamp.desc())
                    .limit(5)
                )
                recent_games_result = session.execute(stmt).fetchall()

                recent_games_list = [
                    {
                        "item_name": game[0],
                        "cost_credits": float(game[1] or 0),
                        "credits_change": game[2],
                        "date": game[3],
                        "timestamp": game[4],
                    }
                    for game in recent_games_result
                ]

                return {
                    "today_spins": today_spins,
                    "total_spins": total_spins,
                    "week_spins": week_spins,
                    "total_credits_change": float(total_credits_change),
                    "today_credits_change": float(today_credits_change),
                    "week_credits_change": float(week_credits_change),
                    "total_cost_credits": float(total_cost_credits),
                    "today_cost_credits": float(today_cost_credits),
                    "week_cost_credits": float(week_cost_credits),
                    "total_invite_codes": invite_codes_earned,
                    "today_invite_codes": today_invite_codes,
                    "week_invite_codes": week_invite_codes,
                    "recent_games": recent_games_list,
                }
        except Exception as e:
            logger.error(f"Error getting user wheel stats: {e}")
            return {
                "today_spins": 0,
                "total_spins": 0,
                "week_spins": 0,
                "total_credits_change": 0.0,
                "today_credits_change": 0.0,
                "week_credits_change": 0.0,
                "total_cost_credits": 0.0,
                "today_cost_credits": 0.0,
                "week_cost_credits": 0.0,
                "total_invite_codes": 0,
                "today_invite_codes": 0,
                "week_invite_codes": 0,
                "recent_games": [],
            }

    def get_lucky_wheel_config(self, config_key: str = "config") -> str | None:
        """
        获取幸运大转盘配置

        Args:
            config_key: 配置键 (config 或 randomness_config)

        Returns:
            配置的 JSON 字符串
        """
        return self.get_system_config("lucky_wheel", config_key)

    def set_lucky_wheel_config(self, config_key: str, config_json: str) -> bool:
        """
        设置幸运大转盘配置

        Args:
            config_key: 配置键 (config 或 randomness_config)
            config_json: 配置的 JSON 字符串

        Returns:
            是否成功
        """
        return self.set_system_config("lucky_wheel", config_key, config_json)


FREESPIN_NOTIFY_CURSOR_KEY = "freespin_notify_cursor"


def _read_blackjack_freespin_cursor(session) -> tuple[SystemConfig | None, int]:
    row = (
        session.execute(
            select(SystemConfig).where(
                SystemConfig.config_type == "blackjack",
                SystemConfig.config_key == FREESPIN_NOTIFY_CURSOR_KEY,
            )
        )
        .scalars()
        .one_or_none()
    )
    try:
        cursor = int(float(row.config_value)) if row else 0
    except (TypeError, ValueError):
        cursor = 0
    return row, cursor


def _write_blackjack_freespin_cursor(
    session, row: SystemConfig | None, value: int
) -> None:
    now_ts = int(time.time())
    if row is None:
        session.add(
            SystemConfig(
                config_type="blackjack",
                config_key=FREESPIN_NOTIFY_CURSOR_KEY,
                config_value=str(int(value)),
                created_at=now_ts,
                updated_at=now_ts,
            )
        )
    else:
        row.config_value = str(int(value))
        row.updated_at = now_ts
    session.flush()


def claim_unnotified_blackjack_freespins() -> list[dict]:
    """Claim settled-enough free-spin grants for best-effort notification."""
    try:
        with get_session() as session:
            cursor_row, cursor = _read_blackjack_freespin_cursor(session)
            safe_before_ms = int(time.time() * 1000) - 60 * 1000
            rows = session.execute(
                select(
                    LuckywheelFreeSpin.id,
                    LuckywheelFreeSpin.tg_id,
                    LuckywheelFreeSpin.expires_at_ms,
                    LuckywheelFreeSpin.source,
                )
                .where(
                    LuckywheelFreeSpin.id > cursor,
                    LuckywheelFreeSpin.granted_at_ms <= safe_before_ms,
                )
                .order_by(LuckywheelFreeSpin.id)
            ).all()
            frontier = int(rows[-1][0]) if rows else cursor
            _write_blackjack_freespin_cursor(session, cursor_row, frontier)
            if cursor_row is None:
                if frontier:
                    logger.info(f"免费机会通知游标初始化为 {frontier}，不回溯历史发放")
                return []
            return [
                {"id": int(row[0]), "tg_id": int(row[1]), "expires_at_ms": int(row[2])}
                for row in rows
                if row[3] == "blackjack"
            ]
    except Exception as exc:
        logger.error(f"认领待通知的免费机会发放失败: {exc}")
        return []


def list_expiring_blackjack_freespins(*, within_ms: int = 86400 * 1000) -> list[dict]:
    """List unused free spins expiring within a window, grouped by user."""
    now_ms = int(time.time() * 1000)
    try:
        with get_session() as session:
            rows = session.execute(
                select(LuckywheelFreeSpin.tg_id, LuckywheelFreeSpin.expires_at_ms)
                .where(
                    LuckywheelFreeSpin.used_at_ms.is_(None),
                    LuckywheelFreeSpin.expires_at_ms > now_ms,
                    LuckywheelFreeSpin.expires_at_ms <= now_ms + int(within_ms),
                )
                .order_by(LuckywheelFreeSpin.expires_at_ms)
            ).all()
        merged: dict[int, list[int]] = {}
        for tg_id, expires_at_ms in rows:
            merged.setdefault(int(tg_id), []).append(int(expires_at_ms))
        return [
            {"tg_id": tg_id, "expires_at_ms_list": expiries}
            for tg_id, expiries in merged.items()
        ]
    except Exception as exc:
        logger.error(f"查询即将过期的免费机会失败: {exc}")
        return []
