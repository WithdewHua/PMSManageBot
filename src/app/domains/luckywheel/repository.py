import time
from datetime import datetime, timedelta
from math import isfinite

from sqlalchemy import func, select, update

from app.core import kv as core_kv
from app.core.config import settings
from app.core.db import get_session
from app.core.kv import SystemConfig
from app.core.log import logger
from app.domains.credits import repository as credits_repository
from app.domains.credits.types import CreditAccount
from app.domains.identity.types import TgIdReassignIssue
from app.domains.invitation import repository as invitation_repository
from app.domains.luckywheel import config as wheel_config
from app.domains.luckywheel import constants as wheel_constants
from app.domains.luckywheel import rules as luckywheel_rules
from app.domains.luckywheel.exceptions import (
    insufficient_credits,
    ten_spin_insufficient_credits,
    user_not_found,
)
from app.domains.luckywheel.models import LuckywheelFreeSpin, WheelStats
from app.domains.luckywheel.types import FreeSpinProgressProvider
from app.domains.premium import repository as premium_repository

FREE_SPIN_SOURCES = frozenset({"blackjack", "gift_pack"})
REASSIGNED_TG_ID_COLUMNS: tuple[str, ...] = (
    "wheel_stats.tg_id",
    "luckywheel_free_spins.tg_id",
)
_free_spin_progress_provider: FreeSpinProgressProvider | None = None


def register_free_spin_progress_provider(provider: FreeSpinProgressProvider) -> None:
    """Register the source-owned progress provider during application assembly."""
    global _free_spin_progress_provider
    _free_spin_progress_provider = provider


def clear_free_spin_progress_provider() -> None:
    """Reset the provider for isolated tests and process teardown."""
    global _free_spin_progress_provider
    _free_spin_progress_provider = None


def grant_free_spins_tx(
    session,
    tg_id: int,
    count: int,
    *,
    source: str,
    granted_at_ms: int,
    expires_at_ms: int,
    cost_credits: float = 0.0,
) -> list[LuckywheelFreeSpin]:
    """Grant free spins in a caller-owned transaction."""
    if int(count) <= 0:
        raise ValueError("free spin count must be positive")
    if source not in FREE_SPIN_SOURCES:
        raise ValueError(f"unsupported free spin source: {source}")
    if int(expires_at_ms) <= int(granted_at_ms):
        raise ValueError("free spin expiry must be after grant time")
    normalized_cost = float(cost_credits)
    if not isfinite(normalized_cost) or normalized_cost < 0:
        raise ValueError("free spin cost must be finite and non-negative")

    wheel_stats_source = wheel_constants.wheel_source_for_free_spin(source)
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


def consume_free_spin_tx(
    session, tg_id: int, *, now_ms: int | None = None
) -> dict | None:
    """Claim the earliest available free-spin row in the caller's transaction."""
    claimed_at_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    row = (
        session.execute(
            select(LuckywheelFreeSpin)
            .where(
                LuckywheelFreeSpin.tg_id == int(tg_id),
                LuckywheelFreeSpin.used_at_ms.is_(None),
                LuckywheelFreeSpin.expires_at_ms > claimed_at_ms,
            )
            .order_by(LuckywheelFreeSpin.expires_at_ms, LuckywheelFreeSpin.id)
            .with_for_update()
            .limit(1)
        )
        .scalars()
        .one_or_none()
    )
    if row is None:
        return None
    row.used_at_ms = claimed_at_ms
    session.flush()
    return {
        "id": int(row.id),
        "expires_at_ms": int(row.expires_at_ms),
        "claimed_at_ms": claimed_at_ms,
        "source": row.source,
        "cost_credits_snapshot": float(row.cost_credits_snapshot or 0),
        "wheel_stats_source": row.wheel_stats_source
        or wheel_constants.wheel_source_for_free_spin(row.source),
    }


def add_wheel_spin_record_tx(
    session,
    tg_id: int,
    item_name: str,
    credits_change: float,
    cost_credits: float,
    source: str = "paid",
) -> None:
    """Append a wheel-statistics row to the caller's transaction."""
    session.add(
        WheelStats(
            tg_id=int(tg_id),
            item_name=item_name,
            cost_credits=float(cost_credits),
            credits_change=float(credits_change),
            timestamp=int(time.time()),
            date=datetime.now(settings.TZ).strftime("%Y-%m-%d"),
            source=source,
        )
    )
    session.flush()


def spin_tx(
    session,
    *,
    tg_id: int,
    config,
    winner_name: str,
    winner_probability: float,
    use_free_spin: bool = True,
    enforce_minimum: bool = True,
    cost_credits_override: float | None = None,
    source_override: str | None = None,
) -> dict:
    """Execute one complete spin inside the caller-owned transaction."""
    free_spin = consume_free_spin_tx(session, tg_id) if use_free_spin else None
    balance_before, _ = credits_repository.get_tx(
        session, CreditAccount.tg(int(tg_id)), for_update=True
    )

    if free_spin is None:
        if enforce_minimum and balance_before < float(config.min_credits_required):
            raise insufficient_credits(float(config.min_credits_required))
        cost_credits = (
            float(config.cost_credits)
            if cost_credits_override is None
            else float(cost_credits_override)
        )
        if cost_credits > 0:
            paid = credits_repository.deduct_tx(
                session, CreditAccount.tg(int(tg_id)), cost_credits
            )
            balance_after_cost = paid.after
        else:
            balance_after_cost = balance_before
        source = source_override or "paid"
        free_spin_source = wheel_constants.WHEEL_SOURCE_TO_FREE_SPIN_SOURCE.get(source)
    else:
        balance_after_cost = balance_before
        cost_credits = float(free_spin.get("cost_credits_snapshot") or 0)
        source = str(
            free_spin.get("wheel_stats_source") or source_override or "blackjack_free"
        )
        free_spin_source = str(free_spin.get("source") or "blackjack")

    effects = luckywheel_rules.prize_effects(winner_name, balance_after_cost)
    privileged = False
    issued_codes: list[str] = []
    if effects.invite_codes:
        wheel_config.ensure_wheel_config_tx(session, config)
        privileged = wheel_config.consume_privileged_code_toggle_tx(session)
        issued_codes = invitation_repository.issue_codes_tx(
            session, int(tg_id), effects.invite_codes, privileged=privileged
        )
    premium_services: list[str] = []
    if effects.premium_days:
        for service in ("plex", "emby"):
            try:
                new_expiry = premium_repository.grant_premium_days_tx(
                    session, int(tg_id), service, effects.premium_days
                )
            except NameError:
                continue
            if new_expiry is not None:
                premium_services.append(service)

    target_credits = max(0.0, round(balance_after_cost + effects.credits_change, 2))
    actual_credits_change = round(target_credits - balance_after_cost, 2)
    if actual_credits_change > 0:
        credits_repository.add_tx(
            session, CreditAccount.tg(int(tg_id)), actual_credits_change
        )
    elif actual_credits_change < 0:
        credits_repository.deduct_tx(
            session, CreditAccount.tg(int(tg_id)), -actual_credits_change
        )

    add_wheel_spin_record_tx(
        session,
        int(tg_id),
        winner_name,
        actual_credits_change,
        cost_credits,
        source,
    )
    final_credits, _ = credits_repository.get_tx(
        session, CreditAccount.tg(int(tg_id)), for_update=True
    )
    return {
        "item_name": winner_name,
        "item_probability": float(winner_probability),
        "credits_change": actual_credits_change,
        "current_credits": final_credits,
        "cost_credits": cost_credits,
        "source": source,
        "free_spin_source": free_spin_source,
        "used_free_spin": free_spin is not None or source != "paid",
        "invite_awarded": bool(effects.invite_codes),
        "privileged": privileged,
        "issued_codes": issued_codes,
        "premium_services": premium_services,
    }


def spin(
    *,
    tg_id: int,
    config,
    winner_name: str,
    winner_probability: float,
    use_free_spin: bool = True,
    enforce_minimum: bool = True,
    cost_credits_override: float | None = None,
    source_override: str | None = None,
) -> dict:
    """Repository-owned transaction wrapper for a complete single spin."""
    try:
        with get_session() as session:
            return spin_tx(
                session,
                tg_id=int(tg_id),
                config=config,
                winner_name=winner_name,
                winner_probability=winner_probability,
                use_free_spin=use_free_spin,
                enforce_minimum=enforce_minimum,
                cost_credits_override=cost_credits_override,
                source_override=source_override,
            )
    except ValueError as error:
        if error.__class__.__name__ == "CreditAccountNotFound":
            raise user_not_found(int(tg_id)) from error
        raise


def spin_ten(
    *,
    tg_id: int,
    config,
    winners: list[tuple[str, float]],
) -> list[dict]:
    """Run ten paid spins in one repository-owned transaction."""
    try:
        with get_session() as session:
            balance, _ = credits_repository.get_tx(
                session, CreditAccount.tg(int(tg_id)), for_update=True
            )
            required = (
                float(config.min_credits_required) + float(config.cost_credits)
            ) * 10
            if balance < required:
                raise ten_spin_insufficient_credits(required)
            return [
                spin_tx(
                    session,
                    tg_id=int(tg_id),
                    config=config,
                    winner_name=name,
                    winner_probability=probability,
                    use_free_spin=False,
                    enforce_minimum=False,
                )
                for name, probability in winners
            ]
    except ValueError as error:
        if error.__class__.__name__ == "CreditAccountNotFound":
            raise user_not_found(int(tg_id)) from error
        raise


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


def consume_free_spin(tg_id: int) -> dict | None:
    """Repository-owned wrapper around the source-agnostic transaction helper."""
    try:
        with get_session() as session:
            return consume_free_spin_tx(session, tg_id)
    except Exception as exc:
        logger.error(f"认领免费大转盘机会失败 (tg_id={tg_id}): {exc}")
        return None


def release_free_spin(spin_id: int, *, claimed_at_ms: int) -> bool:
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


def free_spin_summary(tg_id: int) -> dict:
    """Return ledger availability plus progress supplied by the registered source."""
    now_ms = int(time.time() * 1000)
    try:
        with get_session() as session:
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
        progress = (
            _free_spin_progress_provider(int(tg_id))
            if _free_spin_progress_provider is not None
            else None
        )
        return {
            "enabled": bool(progress.enabled) if progress else False,
            "available": len(spins),
            "expires_at_ms_list": [int(value) for value in spins],
            "hands_since_freespin": (
                int(progress.hands_since_freespin) if progress else 0
            ),
            "hand_threshold": int(progress.hand_threshold) if progress else 0,
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
        return core_kv.get("lucky_wheel", config_key)

    def set_lucky_wheel_config(self, config_key: str, config_json: str) -> bool:
        """
        设置幸运大转盘配置

        Args:
            config_key: 配置键 (config 或 randomness_config)
            config_json: 配置的 JSON 字符串

        Returns:
            是否成功
        """
        core_kv.upsert("lucky_wheel", config_key, config_json)
        return True


_repository = LuckywheelRepository()


def add_wheel_spin_record(
    tg_id: int,
    item_name: str,
    credits_change: float,
    cost_credits: float,
    source: str = "paid",
) -> bool:
    return _repository.add_wheel_spin_record(
        tg_id, item_name, credits_change, cost_credits, source
    )


def get_wheel_stats() -> dict:
    return _repository.get_wheel_stats()


def get_user_wheel_stats(tg_id: int) -> dict:
    return _repository.get_user_wheel_stats(int(tg_id))


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


# ---------------------------------------------------------------- 礼包条件取数
#
# 转盘次数列属于 luckywheel，礼包只通过这些 `*_tx` 取数（design D2）。


def count_paid_spins_tx(
    session, tg_id: int, since: int, until: int, *, paid_only: bool = True
) -> int:
    """指定时间窗内的转盘次数（闭区间，秒级时间戳）。

    默认只数付费转盘（`paid_only=True`），礼包条件里显式写了
    `paid_only: false` 时按全部转盘计。
    """
    stmt = select(func.count(WheelStats.id)).where(
        WheelStats.tg_id == int(tg_id),
        WheelStats.timestamp >= int(since),
        WheelStats.timestamp <= int(until),
    )
    if paid_only:
        stmt = stmt.where(WheelStats.source == "paid")
    return int(session.execute(stmt).scalar_one())


def count_badge_spins(tg_id: int) -> int:
    """Count every recorded spin, including free spins, as the legacy badge did."""
    with get_session() as session:
        return int(
            session.execute(
                select(func.count(WheelStats.id)).where(WheelStats.tg_id == tg_id)
            ).scalar_one()
        )


def list_badge_eligible_tg_ids(min_spins: int) -> list[int]:
    with get_session() as session:
        return list(
            session.execute(
                select(WheelStats.tg_id)
                .group_by(WheelStats.tg_id)
                .having(func.count(WheelStats.id) >= min_spins)
            ).scalars()
        )


def get_wheel_invite_code_rank() -> list[tuple[int, int]]:
    """获取幸运大转盘邀请码获得排行榜 [(tg_id, invite_count), ...]"""
    with get_session() as session:
        invite_count = func.count(WheelStats.id).label("invite_count")
        stmt = (
            select(WheelStats.tg_id, invite_count)
            .where(WheelStats.item_name == "邀请码 1 枚")
            .group_by(WheelStats.tg_id)
            .order_by(invite_count.desc())
        )
        results = session.execute(stmt).fetchall()
        return [(int(r[0]), int(r[1] or 0)) for r in results if int(r[1] or 0) > 0]


def check_tg_id_reassign_tx(
    session, old_tg_id: int, new_tg_id: int
) -> list[TgIdReassignIssue]:
    """Check for in-flight lucky wheel activities or conflicts (none exist)."""
    return []


def reassign_tg_id_tx(session, old_tg_id: int, new_tg_id: int) -> dict[str, int]:
    """Reassign lucky wheel stats and free spin records to new identity."""
    res_stats = session.execute(
        update(WheelStats)
        .where(WheelStats.tg_id == int(old_tg_id))
        .values(tg_id=int(new_tg_id))
    )
    res_free_spins = session.execute(
        update(LuckywheelFreeSpin)
        .where(LuckywheelFreeSpin.tg_id == int(old_tg_id))
        .values(tg_id=int(new_tg_id))
    )
    return {
        "wheel_stats.tg_id": res_stats.rowcount,
        "luckywheel_free_spins.tg_id": res_free_spins.rowcount,
    }
