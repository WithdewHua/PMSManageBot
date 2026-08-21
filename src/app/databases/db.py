#!/usr/bin/env python3
"""
ORM-based database operations using SQLAlchemy
"""

import json
import secrets
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from app.config import settings
from app.databases.cache import user_info_cache
from app.databases.session import get_session
from app.log import logger
from app.models.models import (
    AuctionBids,
    Auctions,
    Badge,
    BlackjackHand,
    CryptoDonationOrders,
    CustomLine,
    DonationRegistrations,
    EmbyUser,
    GhostSessionLog,
    GiftPack,
    GiftPackUserState,
    Invitation,
    LineSchedule,
    LineTrafficMonthlyStats,
    LineTrafficStats,
    Overseerr,
    PlexUser,
    PredictionBet,
    PredictionMarket,
    PredictionMarketSubmission,
    Statistics,
    SystemConfig,
    TreasureIssue,
    TreasureParticipation,
    UserBadge,
    VaultwardenRedeemRecords,
    WheelStats,
)
from app.utils.number import normalize_external_random_b
from sqlalchemy import case, delete, distinct, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

# 21 点默认配置。首次读取时落库，之后由管理员在面板上调整。
# 首次上线默认停用（enabled=False），待管理员核对配置与小范围试玩后再开放。
DEFAULT_BLACKJACK_CONFIG = {
    "enabled": False,  # 服务端停用开关：停用时拒绝新发牌，进行中手牌仍可正常结算
    "bet_options": [5, 15, 30],  # 注额档位，档位之外的注额一律拒绝
    "min_credits": 30,  # 参与门槛
    "rake_bp_on_profit": 300,  # 抽水比率（基点），仅对净赢利计取；300 = 3%
    "rake_burn_bp": 180,  # 抽水中直接销毁的部分（基点），180/300 = 60%
    "rake_jackpot_bp": 120,  # 抽水中注入幸运奖池的部分（基点），120/300 = 40%
    "dealer_hits_soft_17": False,  # 庄家软 17 是否继续要牌；False 即软 17 停牌
    "blackjack_payout": 1.5,  # 天胡赔率，3:2
    "hand_timeout_minutes": 15,  # 手牌超时时限（分钟），超时按停牌自动结算
    "min_deal_interval_seconds": 1,  # 两次发牌的最小间隔，压制脚本化高频刷牌
    # 幸运奖池：由抽水供养、不增发积分，双层触发
    "jackpot_enabled": True,
    "jackpot_suited_bj_pct": 10,  # 同花天胡派发余额的百分比（约 83 手一次）
    # 三张 7 派发全部余额（约 5525 手一次），无需比例参数
    "jackpot_notify_enabled": True,  # 中奖时向群组播报，用于吸引更多人参与
    # 每日免抽水手数：低成本的习惯钩子，无条件发放，不需下注解锁
    "free_hands_per_day": 1,
    # 榜单最低手数门槛：样本量不足的用户不入准确率榜与胜率榜
    "rank_min_hands": 100,
    # 游戏王勋章的 21 点双条件
    "badge_min_hands": 2000,
    "badge_min_accuracy": 80,  # 决策准确率（百分比）
}

# 幸运奖池余额的存放位置。与大预言家的荣耀奖池
# `(prediction_market, glory_fund)` **完全无关**：21 点的抽水只进这个池子。
JACKPOT_CONFIG_TYPE = "blackjack"
JACKPOT_CONFIG_KEY = "jackpot_fund"

# 群播报的进度游标：已播报到的手牌 ID。
#
# 为什么用游标轮询而不在结算处挂钩子：奖池派彩散落在发牌（同花天胡直接结算）、
# 停牌、加倍、超时任务、定时兜底、以及发牌与查询时的惰性清理共六条路径上，
# 逐条挂钩既啰嗦又极易漏——而漏掉的恰恰会是最该播报的那次。游标把「谁结算的」
# 这件事完全解耦：只要派彩落了库，下一轮轮询必然看见它，且看见且仅看见一次。
JACKPOT_NOTIFY_CURSOR_KEY = "jackpot_notify_cursor"


class DatabaseORM:
    """
    基于 ORM 的数据库操作类
    """

    class _CurWrapper:
        """A tiny compatibility wrapper so existing code that calls
        `db.cur.execute(...).fetchall()` keeps working while we migrate
        everything to ORM/session usage. It translates simple SQL strings
        (including positional `?` params) to SQLAlchemy `text()` calls.
        """

        def __init__(self, parent: "DatabaseORM"):
            self._parent = parent
            self._last_rows = []

        def _prepare(self, query: str, params=None):
            # Convert DB-API positional `?` placeholders to SQLAlchemy named
            # parameters (:p0, :p1, ...). If params is a dict, assume it's
            # already named and pass through.
            from sqlalchemy import text

            if params is None:
                return text(query), None

            # If params is a dict, pass directly
            if isinstance(params, dict):
                return text(query), params

            # Assume sequence/tuple positional params and convert `?` placeholders
            if isinstance(params, (list, tuple)):
                # quick replacement: replace each '?' with :p{i}
                parts = query.split("?")
                if len(parts) - 1 != len(params):
                    # fallback: don't transform, let SQLAlchemy try to bind
                    return text(query), params
                new_query = []
                for i, part in enumerate(parts[:-1]):
                    new_query.append(part)
                    new_query.append(f":p{i}")
                new_query.append(parts[-1])
                named = {f"p{i}": params[i] for i in range(len(params))}
                return text("".join(new_query)), named

            # Unknown param style: pass as-is
            return text(query), params

        def execute(self, query: str, params=None):
            stmt, bound_params = self._prepare(query, params)
            # Use a session to execute; fetch all rows and store them
            try:
                with get_session() as session:
                    if bound_params is not None:
                        res = session.execute(stmt, bound_params)
                    else:
                        res = session.execute(stmt)
                    # SQLAlchemy 1.4+ returns Row objects; convert to tuples
                    rows = res.fetchall()
                    # keep as list of tuples for compatibility
                    self._last_rows = [tuple(r) for r in rows]
            except Exception:
                # On any failure just set empty and re-raise so caller sees it
                self._last_rows = []
                raise
            return self

        def fetchall(self):
            return self._last_rows

        def fetchone(self):
            return self._last_rows[0] if self._last_rows else None

    @property
    def cur(self):
        # Return a long-lived wrapper instance per DatabaseORM instance
        if not hasattr(self, "_cur"):
            self._cur = DatabaseORM._CurWrapper(self)
        return self._cur

    # ==================== Plex User Operations ====================

    def add_plex_user(
        self,
        plex_id: Optional[int] = None,
        tg_id: Optional[int] = None,
        plex_email: Optional[str] = None,
        plex_username: Optional[str] = None,
        credits: float = 0,
        all_lib: int = 0,
        unlock_time: Optional[str] = None,
        watched_time: float = 0,
        plex_line: Optional[str] = None,
        is_premium: int = 0,
        premium_expiry_time: Optional[str] = None,
    ) -> bool:
        """添加 Plex 用户"""
        try:
            with get_session() as session:
                user = PlexUser(
                    plex_id=plex_id,
                    tg_id=tg_id,
                    credits=credits,
                    plex_email=plex_email,
                    plex_username=plex_username,
                    all_lib=all_lib,
                    unlock_time=unlock_time,
                    watched_time=watched_time,
                    plex_line=plex_line,
                    is_premium=is_premium,
                    premium_expiry_time=premium_expiry_time,
                )
                session.add(user)

                # 更新缓存
                if plex_username:
                    user_info_cache.put(
                        f"plex:{plex_username.lower()}",
                        json.dumps(
                            {
                                "plex_id": plex_id,
                                "tg_id": tg_id,
                                "plex_email": plex_email,
                                "plex_username": plex_username,
                                "is_premium": is_premium,
                            }
                        ),
                    )
                return True
        except Exception as e:
            logger.error(f"Error adding plex user: {e}")
            return False

    def delete_plex_user(self, plex_email: str) -> bool:
        """删除 Plex 用户"""
        try:
            with get_session() as session:
                session.execute(
                    delete(PlexUser).where(
                        func.lower(PlexUser.plex_email) == plex_email.lower()
                    )
                )
                return True
        except Exception as e:
            logger.error(f"Error deleting plex user: {e}")
            return False

    def get_plex_users_num(self) -> int:
        """获取 Plex 用户数量"""
        with get_session() as session:
            stmt = select(func.count(PlexUser.plex_id))
            return session.execute(stmt).scalar()

    def get_plex_info_by_tg_id(self, tg_id: int) -> Optional[Tuple]:
        """通过 Telegram ID 获取 Plex 用户信息"""
        with get_session() as session:
            stmt = select(PlexUser).where(PlexUser.tg_id == tg_id)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (
                    user.plex_id,
                    user.tg_id,
                    user.credits,
                    user.plex_email,
                    user.plex_username,
                    user.all_lib,
                    user.unlock_time,
                    user.watched_time,
                    user.plex_line,
                    user.is_premium,
                    user.premium_expiry_time,
                    user.last_viewed_at,
                )
            return None

    def get_plex_info_by_plex_id(self, plex_id: int) -> Optional[Tuple]:
        """通过 Plex ID 获取用户信息"""
        with get_session() as session:
            stmt = select(PlexUser).where(PlexUser.plex_id == plex_id)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (
                    user.plex_id,
                    user.tg_id,
                    user.credits,
                    user.plex_email,
                    user.plex_username,
                    user.all_lib,
                    user.unlock_time,
                    user.watched_time,
                    user.plex_line,
                    user.is_premium,
                    user.premium_expiry_time,
                    user.last_viewed_at,
                )
            return None

    def get_plex_info_by_plex_username(self, plex_username: str) -> Optional[Tuple]:
        """通过 Plex 用户名获取用户信息"""
        with get_session() as session:
            stmt = select(PlexUser).where(
                func.lower(PlexUser.plex_username) == plex_username.lower()
            )
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (
                    user.plex_id,
                    user.tg_id,
                    user.credits,
                    user.plex_email,
                    user.plex_username,
                    user.all_lib,
                    user.unlock_time,
                    user.watched_time,
                    user.plex_line,
                    user.is_premium,
                    user.premium_expiry_time,
                    user.last_viewed_at,
                )
            return None

    def get_plex_info_by_plex_email(self, plex_email: str) -> Optional[Tuple]:
        """通过 Plex 邮箱获取用户信息"""
        with get_session() as session:
            stmt = select(PlexUser).where(
                func.lower(PlexUser.plex_email) == plex_email.lower()
            )
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (
                    user.plex_id,
                    user.tg_id,
                    user.credits,
                    user.plex_email,
                    user.plex_username,
                    user.all_lib,
                    user.unlock_time,
                    user.watched_time,
                    user.plex_line,
                    user.is_premium,
                    user.premium_expiry_time,
                    user.last_viewed_at,
                )
            return None

    # ==================== Emby User Operations ====================

    def add_emby_user(
        self,
        emby_username: str,
        emby_id: Optional[str] = None,
        tg_id: Optional[int] = None,
        emby_is_unlock: int = 0,
        emby_unlock_time: Optional[int] = None,
        emby_watched_time: float = 0,
        emby_credits: float = 0,
        emby_line: Optional[str] = None,
        is_premium: int = 0,
        premium_expiry_time: Optional[str] = None,
    ) -> bool:
        """添加 Emby 用户"""
        try:
            with get_session() as session:
                user = EmbyUser(
                    emby_username=emby_username,
                    emby_id=emby_id,
                    tg_id=tg_id,
                    emby_is_unlock=emby_is_unlock,
                    emby_unlock_time=emby_unlock_time,
                    emby_watched_time=emby_watched_time,
                    emby_credits=emby_credits,
                    emby_line=emby_line,
                    is_premium=is_premium,
                    premium_expiry_time=premium_expiry_time,
                )
                session.add(user)

                # 更新缓存
                user_info_cache.put(
                    f"emby:{emby_username.lower()}",
                    json.dumps(
                        {
                            "emby_id": emby_id,
                            "tg_id": tg_id,
                            "emby_username": emby_username,
                            "is_premium": is_premium,
                        }
                    ),
                )
                return True
        except Exception as e:
            logger.error(f"Error adding emby user: {e}")
            return False

    def get_emby_users_num(self) -> int:
        """获取 Emby 用户数量"""
        with get_session() as session:
            stmt = select(func.count(EmbyUser.emby_username))
            return session.execute(stmt).scalar()

    def get_nsfw_unlocked_users_num(self) -> int:
        """获取 NSFW 解锁用户数量"""
        with get_session() as session:
            # Plex 用户中已解锁 NSFW 的数量
            plex_stmt = select(func.count(PlexUser.id)).where(PlexUser.all_lib == 1)
            plex_count = session.execute(plex_stmt).scalar() or 0

            # Emby 用户中已解锁 NSFW 的数量
            emby_stmt = select(func.count(EmbyUser.emby_username)).where(
                EmbyUser.emby_is_unlock == 1
            )
            emby_count = session.execute(emby_stmt).scalar() or 0

            return plex_count + emby_count

    def get_line_schedule_unlocked_users_num(self) -> int:
        """获取线路调度解锁用户数量"""
        with get_session() as session:
            # Plex 用户中已解锁线路调度的数量
            plex_stmt = select(func.count(PlexUser.id)).where(
                PlexUser.line_schedule_unlocked == 1
            )
            plex_count = session.execute(plex_stmt).scalar() or 0

            # Emby 用户中已解锁线路调度的数量
            emby_stmt = select(func.count(EmbyUser.emby_username)).where(
                EmbyUser.line_schedule_unlocked == 1
            )
            emby_count = session.execute(emby_stmt).scalar() or 0

            return plex_count + emby_count

    def get_vaultwarden_redeemed_users_num(self) -> int:
        """获取 Vaultwarden 兑换次数"""
        with get_session() as session:
            # 统计总兑换次数
            stmt = select(func.count(VaultwardenRedeemRecords.id))
            return session.execute(stmt).scalar() or 0

    def get_emby_info_by_emby_username(self, username: str) -> Optional[Tuple]:
        """通过 Emby 用户名获取用户信息"""
        with get_session() as session:
            stmt = select(EmbyUser).where(
                func.lower(EmbyUser.emby_username) == username.lower()
            )
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (
                    user.emby_username,
                    user.emby_id,
                    user.tg_id,
                    user.emby_is_unlock,
                    user.emby_unlock_time,
                    user.emby_watched_time,
                    user.emby_credits,
                    user.emby_line,
                    user.is_premium,
                    user.premium_expiry_time,
                    user.last_viewed_at,
                )
            return None

    def get_emby_info_by_tg_id(self, tg_id: int) -> Optional[Tuple]:
        """通过 Telegram ID 获取 Emby 用户信息"""
        with get_session() as session:
            stmt = select(EmbyUser).where(EmbyUser.tg_id == tg_id)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (
                    user.emby_username,
                    user.emby_id,
                    user.tg_id,
                    user.emby_is_unlock,
                    user.emby_unlock_time,
                    user.emby_watched_time,
                    user.emby_credits,
                    user.emby_line,
                    user.is_premium,
                    user.premium_expiry_time,
                    user.last_viewed_at,
                )
            return None

    def get_emby_info_by_emby_id(self, emby_id: str) -> Optional[Tuple]:
        """通过 Emby ID 获取用户信息"""
        with get_session() as session:
            stmt = select(EmbyUser).where(EmbyUser.emby_id == emby_id)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (
                    user.emby_username,
                    user.emby_id,
                    user.tg_id,
                    user.emby_is_unlock,
                    user.emby_unlock_time,
                    user.emby_watched_time,
                    user.emby_credits,
                    user.emby_line,
                    user.is_premium,
                    user.premium_expiry_time,
                    user.last_viewed_at,
                )
            return None

    def get_plex_premium_quota_status(self, plex_id: int) -> dict:
        """获取 Plex 用户今日 Premium 免费额度状态"""
        try:
            today = datetime.now(settings.TZ)
            with get_session() as session:
                user = session.execute(
                    select(
                        PlexUser.is_premium,
                        PlexUser.premium_traffic_debt_bytes,
                        PlexUser.premium_traffic_debt_updated_date,
                    ).where(PlexUser.plex_id == plex_id)
                ).fetchone()

            if not user:
                return {
                    "daily_limit": 0,
                    "current_debt": 0,
                    "remaining_free": 0,
                }

            daily_limit = (
                settings.PREMIUM_USER_TRAFFIC_LIMIT
                if user[0]
                else settings.USER_TRAFFIC_LIMIT
            )
            current_debt = int(user[1] or 0)
            debt_updated_date = user[2]

            if debt_updated_date:
                try:
                    debt_day = datetime.strptime(debt_updated_date, "%Y-%m-%d").replace(
                        tzinfo=settings.TZ
                    )
                    gap_days = max((today.date() - debt_day.date()).days - 1, 0)
                    current_debt = max(current_debt - gap_days * daily_limit, 0)
                except ValueError:
                    logger.warning(
                        f"Invalid Plex premium debt date for {plex_id}: {debt_updated_date}"
                    )

            return {
                "daily_limit": daily_limit,
                "current_debt": current_debt,
                "remaining_free": max(daily_limit - current_debt, 0),
            }
        except Exception as e:
            logger.error(f"Error getting Plex premium quota status for {plex_id}: {e}")
            return {"daily_limit": 0, "current_debt": 0, "remaining_free": 0}

    def get_emby_premium_quota_status(self, emby_username: str) -> dict:
        """获取 Emby 用户今日 Premium 免费额度状态"""
        try:
            today = datetime.now(settings.TZ)
            with get_session() as session:
                user = session.execute(
                    select(
                        EmbyUser.is_premium,
                        EmbyUser.premium_traffic_debt_bytes,
                        EmbyUser.premium_traffic_debt_updated_date,
                    ).where(func.lower(EmbyUser.emby_username) == emby_username.lower())
                ).fetchone()

            if not user:
                return {
                    "daily_limit": 0,
                    "current_debt": 0,
                    "remaining_free": 0,
                }

            daily_limit = (
                settings.PREMIUM_USER_TRAFFIC_LIMIT
                if user[0]
                else settings.USER_TRAFFIC_LIMIT
            )
            current_debt = int(user[1] or 0)
            debt_updated_date = user[2]

            if debt_updated_date:
                try:
                    debt_day = datetime.strptime(debt_updated_date, "%Y-%m-%d").replace(
                        tzinfo=settings.TZ
                    )
                    gap_days = max((today.date() - debt_day.date()).days - 1, 0)
                    current_debt = max(current_debt - gap_days * daily_limit, 0)
                except ValueError:
                    logger.warning(
                        f"Invalid Emby premium debt date for {emby_username}: {debt_updated_date}"
                    )

            return {
                "daily_limit": daily_limit,
                "current_debt": current_debt,
                "remaining_free": max(daily_limit - current_debt, 0),
            }
        except Exception as e:
            logger.error(
                f"Error getting Emby premium quota status for {emby_username}: {e}"
            )
            return {"daily_limit": 0, "current_debt": 0, "remaining_free": 0}

    # ==================== Statistics Operations ====================

    def add_user_data(
        self, tg_id: int, credits: float = 0, donation: float = 0
    ) -> bool:
        """添加用户统计数据"""
        try:
            with get_session() as session:
                stats = Statistics(tg_id=tg_id, credits=credits, donation=donation)
                session.add(stats)
                return True
        except Exception as e:
            logger.error(f"Error adding user data: {e}")
            return False

    def get_stats_by_tg_id(self, tg_id: int) -> Optional[Tuple]:
        """通过 Telegram ID 获取统计信息"""
        with get_session() as session:
            stmt = select(Statistics).where(Statistics.tg_id == tg_id)
            stats = session.execute(stmt).scalar_one_or_none()
            if stats:
                return (stats.tg_id, stats.donation, stats.credits)
            return None

    def get_user_credits(self, tg_id: int) -> Optional[float]:
        """获取用户积分"""
        with get_session() as session:
            stmt = select(Statistics).where(Statistics.tg_id == tg_id)
            stats = session.execute(stmt).scalar_one_or_none()
            return stats.credits if stats else None

    def update_user_donation(self, donation: float, tg_id: int) -> bool:
        """更新用户捐赠金额"""
        try:
            with get_session() as session:
                session.execute(
                    update(Statistics)
                    .where(Statistics.tg_id == tg_id)
                    .values(donation=donation)
                )
                return True
        except Exception as e:
            logger.error(f"Error updating user donation: {e}")
            return False

    # ==================== Invitation Operations ====================

    def add_invitation_code(
        self, code: str, owner: int, is_used: int = 0, used_by: Optional[int] = None
    ) -> bool:
        """添加邀请码"""
        try:
            with get_session() as session:
                invitation = Invitation(
                    code=code, owner=owner, is_used=is_used, used_by=used_by
                )
                session.add(invitation)
                return True
        except Exception as e:
            logger.error(f"Error adding invitation code: {e}")
            return False

    def update_invitation_status(
        self,
        code: str,
        used_by: str,
        service: Optional[str] = None,
        plex_id: Optional[int] = None,
        emby_id: Optional[str] = None,
    ) -> bool:
        """更新邀请码状态"""
        try:
            with get_session() as session:
                session.execute(
                    update(Invitation)
                    .where(Invitation.code == code)
                    .values(
                        is_used=1,
                        used_by=used_by,
                        service=service,
                        plex_id=plex_id,
                        emby_id=emby_id,
                    )
                )
                return True
        except Exception as e:
            logger.error(f"Error updating invitation status: {e}")
            return False

    def update_invitation_plex_id(self, plex_email: str, plex_id: int) -> bool:
        """通过 plex_email（used_by）更新对应邀请码的 plex_id 字段"""
        try:
            with get_session() as session:
                session.execute(
                    update(Invitation)
                    .where(
                        Invitation.used_by == plex_email,
                        Invitation.service == "plex",
                        Invitation.plex_id.is_(None),
                    )
                    .values(plex_id=plex_id)
                )
                return True
        except Exception as e:
            logger.error(f"Error updating invitation plex_id: {e}")
            return False

    def get_inviter_tg_id_by_plex_id(self, plex_id: int) -> Optional[int]:
        """通过被邀请人的 plex_id 查找邀请人的 tg_id"""
        with get_session() as session:
            stmt = select(Invitation.owner).where(
                Invitation.plex_id == plex_id,
                Invitation.service == "plex",
                Invitation.is_used == 1,
            )
            return session.execute(stmt).scalar_one_or_none()

    def get_inviter_tg_id_by_emby_id(self, emby_id: str) -> Optional[int]:
        """通过被邀请人的 emby_id 查找邀请人的 tg_id"""
        with get_session() as session:
            stmt = select(Invitation.owner).where(
                Invitation.emby_id == emby_id,
                Invitation.service == "emby",
                Invitation.is_used == 1,
            )
            return session.execute(stmt).scalar_one_or_none()

    # ==================== Overseerr Operations ====================

    def add_overseerr_user(self, user_id: int, user_email: str, tg_id: int) -> bool:
        """添加 Overseerr 用户"""
        try:
            with get_session() as session:
                user = Overseerr(user_id=user_id, user_email=user_email, tg_id=tg_id)
                session.add(user)
                return True
        except Exception as e:
            logger.error(f"Error adding overseerr user: {e}")
            return False

    def get_overseerr_info_by_tg_id(self, tg_id: int) -> Optional[Tuple]:
        """通过 Telegram ID 获取 Overseerr 用户信息"""
        with get_session() as session:
            stmt = select(Overseerr).where(Overseerr.tg_id == tg_id)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (user.user_id, user.user_email, user.tg_id)
            return None

    # ==================== Update Operations ====================

    def update_user_tg_id(
        self, tg_id: int, plex_id: Optional[int] = None, emby_id: Optional[str] = None
    ) -> bool:
        """更新用户 Telegram ID"""
        try:
            with get_session() as session:
                if plex_id is not None:
                    session.execute(
                        update(PlexUser)
                        .where(PlexUser.plex_id == plex_id)
                        .values(tg_id=tg_id)
                    )
                if emby_id is not None:
                    session.execute(
                        update(EmbyUser)
                        .where(EmbyUser.emby_id == emby_id)
                        .values(tg_id=tg_id)
                    )
                return True
        except Exception as e:
            logger.error(f"Error updating user tg_id: {e}")
            return False

    def rebind_user_tg_id(
        self,
        new_tg_id: int,
        plex_email: Optional[str] = None,
        emby_username: Optional[str] = None,
    ) -> bool:
        """
        换绑用户 Telegram ID
        通过 plex_email 或 emby_username 查找用户并更新其 tg_id
        会同时更新所有相关表（PlexUser/EmbyUser, Statistics, Overseerr, WheelStats,
        VaultwardenRedeemRecords, LineSchedule, UserBadge, Invitation, Auctions,
        AuctionBids, DonationRegistrations, CryptoDonationOrders, TreasureIssue,
        TreasureParticipation, PredictionMarket, PredictionMarketSubmission,
        PredictionBet, CustomLine）

        Args:
            new_tg_id: 新的 Telegram ID
            plex_email: Plex 用户邮箱（可选）
            emby_username: Emby 用户名（可选）

        Returns:
            bool: 操作是否成功
        """
        if plex_email is None and emby_username is None:
            logger.error("Error: plex_email and emby_username cannot both be None")
            return False

        try:
            with get_session() as session:
                old_tg_ids = set()
                updated = False

                # 处理 Plex 用户
                if plex_email is not None:
                    # 先获取旧的 tg_id
                    stmt = select(PlexUser.tg_id).where(
                        func.lower(PlexUser.plex_email) == plex_email.lower()
                    )
                    old_tg_id = session.execute(stmt).scalar_one_or_none()

                    # 更新 PlexUser 表
                    result = session.execute(
                        update(PlexUser)
                        .where(func.lower(PlexUser.plex_email) == plex_email.lower())
                        .values(tg_id=new_tg_id)
                    )
                    if result.rowcount > 0:
                        updated = True
                        if old_tg_id is not None:
                            old_tg_ids.add(old_tg_id)
                        logger.info(
                            f"Updated tg_id for Plex user '{plex_email}' to {new_tg_id}"
                        )
                    else:
                        logger.warning(f"No Plex user found with email '{plex_email}'")

                # 处理 Emby 用户
                if emby_username is not None:
                    # 先获取旧的 tg_id
                    stmt = select(EmbyUser.tg_id).where(
                        EmbyUser.emby_username == emby_username
                    )
                    old_tg_id = session.execute(stmt).scalar_one_or_none()

                    # 更新 EmbyUser 表
                    result = session.execute(
                        update(EmbyUser)
                        .where(EmbyUser.emby_username == emby_username)
                        .values(tg_id=new_tg_id)
                    )
                    if result.rowcount > 0:
                        updated = True
                        if old_tg_id is not None:
                            old_tg_ids.add(old_tg_id)
                        logger.info(
                            f"Updated tg_id for Emby user '{emby_username}' to {new_tg_id}"
                        )
                    else:
                        logger.warning(
                            f"No Emby user found with username '{emby_username}'"
                        )

                # 更新所有其他相关表的 tg_id
                if updated and old_tg_ids:
                    # 引用 statistics.tg_id 但未建外键约束的列：任何换绑场景都需显式迁移
                    plain_ref_columns = [
                        (Overseerr, "tg_id"),
                        (WheelStats, "tg_id"),
                        (Invitation, "owner"),
                        (Auctions, "created_by"),
                        (Auctions, "winner_id"),
                        (AuctionBids, "bidder_id"),
                        (TreasureIssue, "winner_tg_id"),
                        (TreasureIssue, "created_by"),
                        (TreasureParticipation, "tg_id"),
                        (PredictionMarket, "created_by"),
                        (PredictionMarket, "resolved_by"),
                        (PredictionMarketSubmission, "submitter_tg_id"),
                        (PredictionMarketSubmission, "reviewed_by"),
                        (PredictionBet, "tg_id"),
                    ]
                    # 设有 statistics.tg_id 外键（ON UPDATE CASCADE）的列：
                    # 换绑到全新 ID 时随 statistics 主键更新自动级联，无需显式迁移；
                    # 合并到已存在 ID 时不触发级联，需显式迁移
                    fk_ref_columns = [
                        (VaultwardenRedeemRecords, "tg_id"),
                        (LineSchedule, "tg_id"),
                        (UserBadge, "tg_id"),
                        (DonationRegistrations, "user_id"),
                        (DonationRegistrations, "processed_by"),
                        (CryptoDonationOrders, "user_id"),
                        (CustomLine, "tg_id"),
                        (CustomLine, "approved_by"),
                    ]

                    for old_tg_id in old_tg_ids:
                        # tg_id 未变化时无需迁移
                        if old_tg_id == new_tg_id:
                            continue

                        old_stat = session.get(Statistics, old_tg_id)
                        new_stat = session.get(Statistics, new_tg_id)
                        merging = old_stat is not None and new_stat is not None

                        # 无外键约束的列在任何场景都需显式迁移
                        columns_to_migrate = list(plain_ref_columns)

                        if old_stat is not None and new_stat is None:
                            # 目标为全新 ID：直接改 statistics 主键，
                            # 引用它且设了 ON UPDATE CASCADE 的子表会自动跟随
                            old_stat.tg_id = new_tg_id
                            session.flush()
                            logger.info(
                                f"Migrated Statistics tg_id (cascade): {old_tg_id} -> {new_tg_id}"
                            )
                        elif merging:
                            # 目标 ID 已存在：合并积分；外键列不触发级联，需显式迁移
                            new_stat.donation += old_stat.donation
                            new_stat.credits += old_stat.credits
                            session.flush()
                            columns_to_migrate += fk_ref_columns

                        for model, attr in columns_to_migrate:
                            column = getattr(model, attr)
                            result = session.execute(
                                update(model)
                                .where(column == old_tg_id)
                                .values({column: new_tg_id})
                            )
                            if result.rowcount > 0:
                                logger.info(
                                    f"Migrated {result.rowcount} {model.__tablename__}.{attr}: {old_tg_id} -> {new_tg_id}"
                                )

                        if merging:
                            # 外键引用均已迁出，删除旧 Statistics 记录
                            session.delete(old_stat)
                            session.flush()
                            logger.info(
                                f"Removed merged Statistics record: {old_tg_id} -> {new_tg_id}"
                            )

                return updated
        except Exception as e:
            logger.error(f"Error rebinding user tg_id: {e}")
            traceback.print_exc()
            return False

    def update_user_credits(
        self,
        credits: float,
        plex_id: Optional[int] = None,
        emby_id: Optional[str] = None,
        tg_id: Optional[int] = None,
    ) -> bool:
        """更新用户积分"""
        try:
            with get_session() as session:
                if tg_id is not None:
                    session.execute(
                        update(Statistics)
                        .where(Statistics.tg_id == tg_id)
                        .values(credits=credits)
                    )
                elif plex_id is not None:
                    session.execute(
                        update(PlexUser)
                        .where(PlexUser.plex_id == plex_id)
                        .values(credits=credits)
                    )
                elif emby_id is not None:
                    session.execute(
                        update(EmbyUser)
                        .where(EmbyUser.emby_id == emby_id)
                        .values(emby_credits=credits)
                    )
                else:
                    logger.error("Error: there is no enough params")
                    return False
                return True
        except Exception as e:
            logger.error(f"Error updating user credits: {e}")
            return False

    def update_all_lib_flag(
        self,
        all_lib: int,
        unlock_time: Optional[str] = None,
        plex_id: Optional[int] = None,
        emby_id: Optional[str] = None,
        tg_id: Optional[int] = None,
        media_server: str = "plex",
    ) -> bool:
        """更新全库权限标志"""
        try:
            with get_session() as session:
                if media_server.lower() == "plex":
                    if plex_id is not None:
                        session.execute(
                            update(PlexUser)
                            .where(PlexUser.plex_id == plex_id)
                            .values(all_lib=all_lib, unlock_time=unlock_time)
                        )
                    elif tg_id is not None:
                        session.execute(
                            update(PlexUser)
                            .where(PlexUser.tg_id == tg_id)
                            .values(all_lib=all_lib, unlock_time=unlock_time)
                        )
                elif media_server.lower() == "emby":
                    if emby_id is not None:
                        session.execute(
                            update(EmbyUser)
                            .where(EmbyUser.emby_id == emby_id)
                            .values(
                                emby_is_unlock=all_lib, emby_unlock_time=unlock_time
                            )
                        )
                    elif tg_id is not None:
                        session.execute(
                            update(EmbyUser)
                            .where(EmbyUser.tg_id == tg_id)
                            .values(
                                emby_is_unlock=all_lib, emby_unlock_time=unlock_time
                            )
                        )
                else:
                    logger.error("Error: please specify correct media server")
                    return False
                return True
        except Exception as e:
            logger.error(f"Error updating all_lib_flag: {e}")
            return False

    def get_overseerr_info_by_email(self, email: str) -> Optional[Tuple]:
        """通过邮箱获取 Overseerr 用户信息"""
        with get_session() as session:
            stmt = select(Overseerr).where(Overseerr.user_email == email)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return (user.user_id, user.user_email, user.tg_id)
            return None

    # ==================== Rank Operations ====================

    # ==================== Treasure (夺宝) Operations ====================

    def create_treasure_issue(
        self,
        title: str,
        prize_credits: int,
        total_credits_required: int,
        credits_per_share: int = 10,
        start_number: Optional[int] = None,
        description: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> int:
        """创建夺宝期数，返回 issue_id。"""
        total_shares = int(total_credits_required // credits_per_share)
        if total_shares <= 0:
            raise ValueError("total_shares must be > 0")
        if total_credits_required % credits_per_share != 0:
            raise ValueError(
                "total_credits_required must be divisible by credits_per_share"
            )
        if prize_credits <= 0 or total_credits_required < prize_credits:
            raise ValueError("invalid credits settings")

        with get_session() as session:
            # 起始幸运号：如果前端未传，则随机生成一个 8 位起始号。
            # 需要保证号段长度为 total_shares，且 number_high >= number_low。
            if start_number is None:
                lower = 10_000_001
                upper = 99_999_999 - int(total_shares) + 1
                if upper < lower:
                    # 极端情况下（总份数过大）退化为固定起点
                    start_number = lower
                else:
                    # 尝试避免与历史期数 start_number 完全重复（非强需求，尽量即可）
                    used = set(
                        n
                        for (n,) in session.execute(
                            select(TreasureIssue.start_number)
                            .order_by(TreasureIssue.id.desc())
                            .limit(500)
                        ).all()
                    )
                    for _ in range(30):
                        candidate = lower + secrets.randbelow(int(upper - lower + 1))
                        if int(candidate) not in used:
                            start_number = int(candidate)
                            break
                    else:
                        start_number = lower + secrets.randbelow(int(upper - lower + 1))
            else:
                start_number = int(start_number)
                if start_number <= 0:
                    raise ValueError("start_number must be > 0")

            # 最终范围校验
            number_low = int(start_number)
            number_high = int(start_number) + int(total_shares) - 1
            if number_high < number_low:
                raise ValueError("invalid number range")

            issue = TreasureIssue(
                title=title,
                description=description,
                prize_credits=int(prize_credits),
                total_credits_required=int(total_credits_required),
                credits_per_share=int(credits_per_share),
                total_shares=int(total_shares),
                start_number=int(start_number),
                status=1,
                shares_sold=0,
                created_by=created_by,
            )
            session.add(issue)
            session.flush()
            return int(issue.id)

    def get_treasure_issue_by_id(self, issue_id: int) -> Optional[dict]:
        with get_session() as session:
            stmt = select(TreasureIssue).where(TreasureIssue.id == issue_id)
            issue = session.execute(stmt).scalar_one_or_none()
            if not issue:
                return None
            return {
                "id": int(issue.id),
                "title": issue.title,
                "description": issue.description,
                "prize_credits": int(issue.prize_credits),
                "total_credits_required": int(issue.total_credits_required),
                "credits_per_share": int(issue.credits_per_share),
                "total_shares": int(issue.total_shares),
                "start_number": int(issue.start_number),
                "status": int(issue.status),
                "shares_sold": int(issue.shares_sold),
                "external_random_b": int(issue.external_random_b)
                if issue.external_random_b is not None
                else None,
                "winner_number": int(issue.winner_number)
                if issue.winner_number is not None
                else None,
                "winner_tg_id": int(issue.winner_tg_id)
                if issue.winner_tg_id is not None
                else None,
                "settled_at": int(issue.settled_at)
                if issue.settled_at is not None
                else None,
                "created_by": int(issue.created_by)
                if issue.created_by is not None
                else None,
                "created_at": issue.created_at,
            }

    def list_treasure_issues(
        self, limit: int = 50, include_closed: bool = True
    ) -> List[dict]:
        with get_session() as session:
            active_first = case((TreasureIssue.status == 1, 1), else_=0).desc()

            stmt = (
                select(TreasureIssue)
                .order_by(active_first, TreasureIssue.id.desc())
                .limit(limit)
            )
            if not include_closed:
                stmt = (
                    select(TreasureIssue)
                    .where(TreasureIssue.status == 1)
                    .order_by(TreasureIssue.id.desc())
                    .limit(limit)
                )
            issues = session.execute(stmt).scalars().all()
            return [
                {
                    "id": int(i.id),
                    "title": i.title,
                    "prize_credits": int(i.prize_credits),
                    "total_credits_required": int(i.total_credits_required),
                    "credits_per_share": int(i.credits_per_share),
                    "total_shares": int(i.total_shares),
                    "start_number": int(i.start_number),
                    "shares_sold": int(i.shares_sold),
                    "status": int(i.status),
                    "winner_number": int(i.winner_number)
                    if i.winner_number is not None
                    else None,
                    "winner_tg_id": int(i.winner_tg_id)
                    if i.winner_tg_id is not None
                    else None,
                    "created_at": i.created_at,
                }
                for i in issues
            ]

    def list_treasure_participations(
        self, issue_id: int, limit: int = 200
    ) -> List[dict]:
        from app.utils.utils import get_user_name_from_tg_id

        with get_session() as session:
            issue_seq = (
                func.row_number()
                .over(
                    partition_by=TreasureParticipation.issue_id,
                    order_by=TreasureParticipation.id.asc(),
                )
                .label("issue_seq")
            )
            stmt = (
                select(
                    TreasureParticipation.id,
                    TreasureParticipation.issue_id,
                    TreasureParticipation.tg_id,
                    TreasureParticipation.lucky_number,
                    TreasureParticipation.cost_credits,
                    TreasureParticipation.created_at_ms,
                    TreasureParticipation.created_at,
                    issue_seq,
                )
                .where(TreasureParticipation.issue_id == issue_id)
                .order_by(TreasureParticipation.id.desc())
                .limit(limit)
            )
            rows = session.execute(stmt).all()
            return [
                {
                    "id": int(p.id),
                    "issue_id": int(p.issue_id),
                    "issue_seq": int(p.issue_seq),
                    "tg_id": int(p.tg_id),
                    "tg_username": str(
                        get_user_name_from_tg_id(int(p.tg_id)) or p.tg_id
                    ),
                    "lucky_number": int(p.lucky_number),
                    "cost_credits": int(p.cost_credits),
                    "created_at_ms": int(p.created_at_ms),
                    "created_at": p.created_at,
                }
                for p in rows
            ]

    def join_treasure_issue(
        self,
        issue_id: int,
        tg_id: int,
        external_random_b: Optional[int] = None,
        timestamp_ms: Optional[int] = None,
        quantity: int = 1,
        sample_last_n_ratio: float = 0.4,
        sample_last_n_min: int = 10,
        sample_last_n_max: int = 50,
    ) -> dict:
        """参与夺宝：扣积分 -> 分配幸运号码 -> 若满员则开奖结算。

        并发安全：对 issue 行加 FOR UPDATE 锁，确保 shares_sold 增量与号码分配唯一。

        Returns: {participation, issue, settled(bool), winner_number?, winner_tg_id?}
        """
        if quantity <= 0:
            raise ValueError("quantity must be > 0")
        if quantity > 100:
            raise ValueError("quantity too large")

        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)

        with get_session() as session:
            issue = (
                session.execute(
                    select(TreasureIssue)
                    .where(TreasureIssue.id == issue_id)
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not issue:
                raise ValueError("issue not found")
            if int(issue.status) != 1:
                raise ValueError("issue not active")
            if int(issue.shares_sold) >= int(issue.total_shares):
                raise ValueError("issue already full")

            remaining = int(issue.total_shares) - int(issue.shares_sold)
            buy_qty = min(int(quantity), int(remaining))
            if buy_qty <= 0:
                raise ValueError("issue already full")

            # 单用户累计购买上限：不超过总份数的 20%（分批/单次都限制）
            max_per_user = max(1, int(int(issue.total_shares) * 0.2))
            user_bought = session.execute(
                select(func.count(TreasureParticipation.id)).where(
                    TreasureParticipation.issue_id == int(issue.id),
                    TreasureParticipation.tg_id == int(tg_id),
                )
            ).scalar_one()
            if int(user_bought) + int(buy_qty) > int(max_per_user):
                raise ValueError(
                    f"purchase limit exceeded: max {max_per_user} shares per user"
                )

            # 费用
            cost_per_share = int(issue.credits_per_share)
            total_cost = int(cost_per_share) * int(buy_qty)

            # 扣用户积分（仅 tg 用户体系）
            stats = (
                session.execute(
                    select(Statistics)
                    .where(Statistics.tg_id == tg_id)
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not stats:
                raise ValueError("user stats not found")
            if float(stats.credits) < float(total_cost):
                raise ValueError("insufficient credits")
            stats.credits = round(float(stats.credits) - float(total_cost), 2)

            participations: list[TreasureParticipation] = []
            lucky_numbers: list[int] = []

            # 分配幸运号码（随机，从剩余未占用号码中选，事务内保证并发安全）
            import random

            number_low = int(issue.start_number)
            number_high = int(issue.start_number) + int(issue.total_shares) - 1
            if number_high < number_low:
                raise ValueError("invalid number range")

            # 当前已占用号码集合（在 issue FOR UPDATE 锁下读取即可）
            existing_numbers = set(
                n
                for (n,) in session.execute(
                    select(TreasureParticipation.lucky_number).where(
                        TreasureParticipation.issue_id == int(issue.id)
                    )
                ).all()
            )

            available = [
                n
                for n in range(number_low, number_high + 1)
                if n not in existing_numbers
            ]
            if len(available) < int(buy_qty):
                raise ValueError("issue already full")

            chosen_numbers = random.sample(available, k=int(buy_qty))

            for i, lucky_number in enumerate(chosen_numbers):
                p = TreasureParticipation(
                    issue_id=int(issue.id),
                    tg_id=int(tg_id),
                    lucky_number=int(lucky_number),
                    cost_credits=int(cost_per_share),
                    created_at_ms=int(timestamp_ms) + i,
                )
                session.add(p)
                participations.append(p)
                lucky_numbers.append(int(lucky_number))
                issue.shares_sold = int(issue.shares_sold) + 1

            participation = participations[-1]  # 兼容旧字段
            settled = False
            winner_number = None
            winner_tg_id = None

            # 满员则开奖
            if int(issue.shares_sold) >= int(issue.total_shares):
                # 幂等保护：再次检查 status
                if int(issue.status) == 1:
                    settled = True

                    # 计算采样数 N：按参与人数百分比，限定 [min,max]
                    total = int(issue.total_shares)
                    n = int(
                        max(
                            sample_last_n_min,
                            min(sample_last_n_max, round(total * sample_last_n_ratio)),
                        )
                    )
                    n = min(n, total)

                    # 取最后 N 条参与记录的 created_at_ms
                    last_rows = session.execute(
                        select(
                            TreasureParticipation.created_at_ms,
                            TreasureParticipation.tg_id,
                        )
                        .where(TreasureParticipation.issue_id == int(issue.id))
                        .order_by(TreasureParticipation.id.desc())
                        .limit(n)
                    ).all()
                    a = sum(int(r[0]) for r in last_rows)
                    b = normalize_external_random_b(
                        int(external_random_b)
                        if external_random_b is not None
                        else int(issue.external_random_b or 0),
                        default=0,
                    )

                    # 中奖号码：((A+B) % total_shares) + start_number
                    offset = (a + b) % int(issue.total_shares)
                    winner_number = int(issue.start_number) + int(offset)

                    # 找到赢家（号码唯一）
                    win_part = (
                        session.execute(
                            select(TreasureParticipation).where(
                                TreasureParticipation.issue_id == int(issue.id),
                                TreasureParticipation.lucky_number
                                == int(winner_number),
                            )
                        )
                        .scalars()
                        .one()
                    )
                    winner_tg_id = int(win_part.tg_id)

                    # 发奖：给中奖者加 prize_credits
                    winner_stats = (
                        session.execute(
                            select(Statistics)
                            .where(Statistics.tg_id == winner_tg_id)
                            .with_for_update()
                        )
                        .scalars()
                        .one_or_none()
                    )
                    if winner_stats:
                        winner_stats.credits = round(
                            float(winner_stats.credits) + float(issue.prize_credits), 2
                        )
                    else:
                        # 如果赢家没有统计记录，创建一条（兼容极端情况）
                        session.add(
                            Statistics(
                                tg_id=winner_tg_id,
                                donation=0,
                                credits=float(issue.prize_credits),
                            )
                        )

                    # 写回期数结果
                    issue.status = 2
                    issue.external_random_b = b
                    issue.winner_number = int(winner_number)
                    issue.winner_tg_id = int(winner_tg_id)
                    issue.settled_at = int(time.time())

            session.flush()

            return {
                "participation": {
                    "id": int(participation.id) if participation.id else None,
                    "issue_id": int(issue.id),
                    "tg_id": int(tg_id),
                    "lucky_number": int(lucky_numbers[-1]),
                    "cost_credits": int(cost_per_share),
                    "created_at_ms": int(timestamp_ms) + (buy_qty - 1),
                },
                "participations": [
                    {
                        "id": int(p.id) if p.id else None,
                        "issue_id": int(issue.id),
                        "tg_id": int(tg_id),
                        "lucky_number": int(n),
                        "cost_credits": int(cost_per_share),
                        "created_at_ms": int(timestamp_ms) + idx,
                    }
                    for idx, (p, n) in enumerate(zip(participations, lucky_numbers))
                ],
                "issue": {
                    "id": int(issue.id),
                    "shares_sold": int(issue.shares_sold),
                    "total_shares": int(issue.total_shares),
                    "status": int(issue.status),
                    "winner_number": int(issue.winner_number)
                    if issue.winner_number is not None
                    else None,
                    "winner_tg_id": int(issue.winner_tg_id)
                    if issue.winner_tg_id is not None
                    else None,
                },
                "settled": settled,
                "winner_number": int(winner_number)
                if winner_number is not None
                else None,
                "winner_tg_id": int(winner_tg_id) if winner_tg_id is not None else None,
            }

    def cancel_treasure_issue(self, issue_id: int) -> dict:
        """管理员取消进行中的夺宝期数，并退还参与者积分。

        规则：
        - 仅 status==1（进行中）允许取消
        - 退还每位参与者已支付的 cost_credits 之和
        - 删除所有参与记录
        - 将期数标记为 status=3（已取消），shares_sold 置 0（便于展示）

        返回：{issue_id, refunded_total, refunded_users, participation_count}
        """
        with get_session() as session:
            issue = (
                session.execute(
                    select(TreasureIssue)
                    .where(TreasureIssue.id == issue_id)
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not issue:
                raise ValueError("issue not found")
            if int(issue.status) != 1:
                raise ValueError("issue not active")

            # 统计需要退还的积分（按 tg_id 聚合）
            rows = session.execute(
                select(
                    TreasureParticipation.tg_id,
                    func.count(TreasureParticipation.id),
                    func.coalesce(func.sum(TreasureParticipation.cost_credits), 0),
                )
                .where(TreasureParticipation.issue_id == int(issue.id))
                .group_by(TreasureParticipation.tg_id)
            ).all()

            refunded_total = 0.0
            refunded_users = 0
            participation_count = 0

            for tg_id, cnt, sum_cost in rows:
                refund = float(sum_cost or 0)
                refunded_total += refund
                participation_count += int(cnt or 0)
                if refund <= 0:
                    continue

                stats = (
                    session.execute(
                        select(Statistics)
                        .where(Statistics.tg_id == int(tg_id))
                        .with_for_update()
                    )
                    .scalars()
                    .one_or_none()
                )
                if stats:
                    stats.credits = round(float(stats.credits) + refund, 2)
                else:
                    session.add(
                        Statistics(
                            tg_id=int(tg_id),
                            donation=0,
                            credits=float(refund),
                        )
                    )
                refunded_users += 1

            # 删除参与记录
            session.execute(
                delete(TreasureParticipation).where(
                    TreasureParticipation.issue_id == int(issue.id)
                )
            )

            # 标记取消
            issue.status = 3
            issue.shares_sold = 0
            issue.external_random_b = None
            issue.winner_number = None
            issue.winner_tg_id = None
            issue.settled_at = None

            session.flush()

            return {
                "issue_id": int(issue.id),
                "refunded_total": round(float(refunded_total), 2),
                "refunded_users": int(refunded_users),
                "participation_count": int(participation_count),
            }

    def get_user_treasure_stats(self, tg_id: int) -> dict:
        """获取用户个人夺宝统计数据。"""
        try:
            with get_session() as session:
                participated_issues = (
                    session.execute(
                        select(
                            func.count(distinct(TreasureParticipation.issue_id))
                        ).where(TreasureParticipation.tg_id == int(tg_id))
                    ).scalar()
                    or 0
                )

                total_cost_credits = (
                    session.execute(
                        select(func.sum(TreasureParticipation.cost_credits)).where(
                            TreasureParticipation.tg_id == int(tg_id)
                        )
                    ).scalar()
                    or 0
                )

                win_count = (
                    session.execute(
                        select(func.count(TreasureIssue.id)).where(
                            TreasureIssue.winner_tg_id == int(tg_id),
                            TreasureIssue.status == 2,
                        )
                    ).scalar()
                    or 0
                )

                total_prize_credits = (
                    session.execute(
                        select(func.sum(TreasureIssue.prize_credits)).where(
                            TreasureIssue.winner_tg_id == int(tg_id),
                            TreasureIssue.status == 2,
                        )
                    ).scalar()
                    or 0
                )

                recent_rows = session.execute(
                    select(
                        TreasureParticipation.issue_id,
                        TreasureParticipation.cost_credits,
                        TreasureParticipation.lucky_number,
                        TreasureParticipation.created_at,
                        TreasureIssue.winner_tg_id,
                        TreasureIssue.prize_credits,
                        TreasureIssue.status,
                    )
                    .join(
                        TreasureIssue,
                        TreasureIssue.id == TreasureParticipation.issue_id,
                    )
                    .where(TreasureParticipation.tg_id == int(tg_id))
                    .order_by(TreasureParticipation.id.desc())
                    .limit(10)
                ).all()

                recent_participations = []
                for row in recent_rows:
                    is_winner = (
                        int(row.winner_tg_id) == int(tg_id)
                        if row.winner_tg_id is not None
                        else False
                    )
                    recent_participations.append(
                        {
                            "issue_id": int(row.issue_id),
                            "cost_credits": int(row.cost_credits),
                            "lucky_number": int(row.lucky_number),
                            "is_winner": bool(is_winner),
                            "won_credits": int(row.prize_credits)
                            if is_winner and int(row.status) == 2
                            else 0,
                            "created_at": row.created_at,
                        }
                    )

                return {
                    "participated_issues": int(participated_issues),
                    "total_cost_credits": int(total_cost_credits),
                    "win_count": int(win_count),
                    "total_prize_credits": int(total_prize_credits),
                    "recent_participations": recent_participations,
                }
        except Exception as e:
            logger.error(f"Error getting user treasure stats: {e}")
            return {
                "participated_issues": 0,
                "total_cost_credits": 0,
                "win_count": 0,
                "total_prize_credits": 0,
                "recent_participations": [],
            }

    # ==================== Prediction Market (预测游戏) Operations ====================

    def _calc_prediction_odds(
        self,
        real_yes: int,
        real_no: int,
        virtual_yes: int,
        virtual_no: int,
    ) -> tuple[float, float]:
        total_pool = float(real_yes + real_no + virtual_yes + virtual_no)
        yes_den = float(real_yes + virtual_yes)
        no_den = float(real_no + virtual_no)
        yes_odds = round(total_pool / yes_den, 4) if yes_den > 0 else 0.0
        no_odds = round(total_pool / no_den, 4) if no_den > 0 else 0.0
        return yes_odds, no_odds

    def submit_prediction_market(
        self,
        title: str,
        betting_deadline: int,
        submitter_tg_id: int,
        description: Optional[str] = None,
    ) -> int:
        if not str(title or "").strip():
            raise ValueError("title is required")

        now_ts = int(time.time())
        if int(betting_deadline) <= int(now_ts):
            raise ValueError("betting_deadline must be in the future")

        with get_session() as session:
            submission = PredictionMarketSubmission(
                title=str(title).strip(),
                description=description,
                betting_deadline=int(betting_deadline),
                status=0,
                submitter_tg_id=int(submitter_tg_id),
            )
            session.add(submission)
            session.flush()
            return int(submission.id)

    def list_prediction_submissions(
        self,
        status: Optional[int] = None,
        limit: int = 50,
        submitter_tg_id: Optional[int] = None,
    ) -> list[dict]:
        with get_session() as session:
            stmt = select(PredictionMarketSubmission)
            if status is not None:
                stmt = stmt.where(PredictionMarketSubmission.status == int(status))
            if submitter_tg_id is not None:
                stmt = stmt.where(
                    PredictionMarketSubmission.submitter_tg_id == int(submitter_tg_id)
                )
            stmt = stmt.order_by(PredictionMarketSubmission.id.desc()).limit(limit)

            rows = session.execute(stmt).scalars().all()
            return [
                {
                    "id": int(r.id),
                    "title": str(r.title or ""),
                    "description": r.description,
                    "betting_deadline": int(r.betting_deadline),
                    "status": int(r.status),
                    "submitter_tg_id": int(r.submitter_tg_id),
                    "reviewed_by": int(r.reviewed_by)
                    if r.reviewed_by is not None
                    else None,
                    "reviewed_at": int(r.reviewed_at)
                    if r.reviewed_at is not None
                    else None,
                    "review_note": r.review_note,
                    "market_id": int(r.market_id) if r.market_id is not None else None,
                    "created_at": r.created_at,
                }
                for r in rows
            ]

    def review_prediction_submission(
        self,
        submission_id: int,
        admin_tg_id: int,
        approved: bool,
        review_note: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        betting_deadline: Optional[int] = None,
    ) -> dict:
        with get_session() as session:
            submission = (
                session.execute(
                    select(PredictionMarketSubmission)
                    .where(PredictionMarketSubmission.id == int(submission_id))
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not submission:
                raise ValueError("submission not found")
            if int(submission.status) != 0:
                raise ValueError("submission already reviewed")

            now_ts = int(time.time())
            final_title = str(
                title if title is not None else submission.title or ""
            ).strip()
            final_description = (
                description if description is not None else submission.description
            )
            final_deadline = int(
                betting_deadline
                if betting_deadline is not None
                else int(submission.betting_deadline)
            )

            if not final_title:
                raise ValueError("title is required")
            if final_deadline <= int(now_ts):
                raise ValueError("betting_deadline must be in the future")

            market_id: Optional[int] = None
            if bool(approved):
                market = PredictionMarket(
                    title=final_title,
                    description=final_description,
                    status=1,
                    betting_deadline=final_deadline,
                    real_yes_pool=0,
                    real_no_pool=0,
                    virtual_yes_pool=500,
                    virtual_no_pool=500,
                    fee_rate_bp=500,
                    fee_burn_bp=300,
                    fee_glory_bp=200,
                    max_bet_per_user=500,
                    created_by=int(admin_tg_id),
                )
                session.add(market)
                session.flush()
                market_id = int(market.id)
                submission.status = 1
                submission.market_id = int(market_id)
            else:
                submission.status = 2

            submission.title = final_title
            submission.description = final_description
            submission.betting_deadline = final_deadline
            submission.reviewed_by = int(admin_tg_id)
            submission.reviewed_at = int(now_ts)
            submission.review_note = review_note

            session.flush()

            return {
                "submission_id": int(submission.id),
                "status": int(submission.status),
                "market_id": int(submission.market_id)
                if submission.market_id is not None
                else None,
                "title": str(submission.title or ""),
                "betting_deadline": int(submission.betting_deadline),
                "submitter_tg_id": int(submission.submitter_tg_id),
            }

    def create_prediction_market(
        self,
        title: str,
        description: Optional[str] = None,
        betting_deadline: Optional[int] = None,
        created_by: Optional[int] = None,
        virtual_yes_pool: int = 500,
        virtual_no_pool: int = 500,
        fee_rate_bp: int = 500,
        fee_burn_bp: int = 300,
        fee_glory_bp: int = 200,
        max_bet_per_user: int = 500,
    ) -> int:
        if not title.strip():
            raise ValueError("title is required")
        if int(fee_burn_bp) + int(fee_glory_bp) != int(fee_rate_bp):
            raise ValueError("invalid fee split")
        if betting_deadline is None:
            raise ValueError("betting_deadline is required")
        now_ts = int(time.time())
        if int(betting_deadline) <= int(now_ts):
            raise ValueError("betting_deadline must be in the future")

        with get_session() as session:
            market = PredictionMarket(
                title=title.strip(),
                description=description,
                status=1,
                betting_deadline=int(betting_deadline) if betting_deadline else None,
                real_yes_pool=0,
                real_no_pool=0,
                virtual_yes_pool=int(max(0, virtual_yes_pool)),
                virtual_no_pool=int(max(0, virtual_no_pool)),
                fee_rate_bp=int(fee_rate_bp),
                fee_burn_bp=int(fee_burn_bp),
                fee_glory_bp=int(fee_glory_bp),
                max_bet_per_user=int(max_bet_per_user),
                created_by=created_by,
            )
            session.add(market)
            session.flush()
            return int(market.id)

    def list_prediction_markets(
        self, limit: int = 50, include_closed: bool = True
    ) -> list[dict]:
        with get_session() as session:
            active_first = case((PredictionMarket.status == 1, 1), else_=0).desc()
            stmt = (
                select(PredictionMarket)
                .order_by(active_first, PredictionMarket.id.desc())
                .limit(limit)
            )
            if not include_closed:
                stmt = (
                    select(PredictionMarket)
                    .where(PredictionMarket.status.in_([1, 2]))
                    .order_by(active_first, PredictionMarket.id.desc())
                    .limit(limit)
                )

            rows = session.execute(stmt).scalars().all()
            items: list[dict] = []
            for m in rows:
                yes_odds, no_odds = self._calc_prediction_odds(
                    int(m.real_yes_pool),
                    int(m.real_no_pool),
                    int(m.virtual_yes_pool),
                    int(m.virtual_no_pool),
                )
                items.append(
                    {
                        "id": int(m.id),
                        "title": m.title,
                        "description": m.description,
                        "status": int(m.status),
                        "result_option": int(m.result_option)
                        if m.result_option is not None
                        else None,
                        "betting_deadline": int(m.betting_deadline)
                        if m.betting_deadline is not None
                        else None,
                        "real_yes_pool": int(m.real_yes_pool),
                        "real_no_pool": int(m.real_no_pool),
                        "virtual_yes_pool": int(m.virtual_yes_pool),
                        "virtual_no_pool": int(m.virtual_no_pool),
                        "yes_odds": yes_odds,
                        "no_odds": no_odds,
                        "max_bet_per_user": int(m.max_bet_per_user),
                        "created_at": m.created_at,
                    }
                )
            return items

    def get_prediction_market_by_id(
        self, market_id: int, tg_id: Optional[int] = None
    ) -> Optional[dict]:
        with get_session() as session:
            m = (
                session.execute(
                    select(PredictionMarket).where(
                        PredictionMarket.id == int(market_id)
                    )
                )
                .scalars()
                .one_or_none()
            )
            if not m:
                return None

            yes_odds, no_odds = self._calc_prediction_odds(
                int(m.real_yes_pool),
                int(m.real_no_pool),
                int(m.virtual_yes_pool),
                int(m.virtual_no_pool),
            )

            my_yes = 0
            my_no = 0
            if tg_id is not None:
                rows = session.execute(
                    select(
                        PredictionBet.option,
                        func.coalesce(func.sum(PredictionBet.amount), 0),
                    )
                    .where(
                        PredictionBet.market_id == int(market_id),
                        PredictionBet.tg_id == int(tg_id),
                    )
                    .group_by(PredictionBet.option)
                ).all()
                for option, total in rows:
                    if int(option) == 1:
                        my_yes = int(total or 0)
                    else:
                        my_no = int(total or 0)

            return {
                "id": int(m.id),
                "title": m.title,
                "description": m.description,
                "status": int(m.status),
                "result_option": int(m.result_option)
                if m.result_option is not None
                else None,
                "betting_deadline": int(m.betting_deadline)
                if m.betting_deadline is not None
                else None,
                "real_yes_pool": int(m.real_yes_pool),
                "real_no_pool": int(m.real_no_pool),
                "virtual_yes_pool": int(m.virtual_yes_pool),
                "virtual_no_pool": int(m.virtual_no_pool),
                "yes_odds": yes_odds,
                "no_odds": no_odds,
                "max_bet_per_user": int(m.max_bet_per_user),
                "fee_rate_bp": int(m.fee_rate_bp),
                "fee_burn_bp": int(m.fee_burn_bp),
                "fee_glory_bp": int(m.fee_glory_bp),
                "resolution_note": m.resolution_note,
                "total_fee_collected": int(m.total_fee_collected),
                "fee_burned": int(m.fee_burned),
                "fee_to_glory": int(m.fee_to_glory),
                "my_yes_amount": int(my_yes),
                "my_no_amount": int(my_no),
                "created_at": m.created_at,
            }

    def place_prediction_bet(
        self,
        market_id: int,
        tg_id: int,
        option: int,
        amount: int,
    ) -> dict:
        if int(option) not in [0, 1]:
            raise ValueError("invalid option")
        if int(amount) <= 0:
            raise ValueError("amount must be > 0")

        now_ts = int(time.time())
        with get_session() as session:
            market = (
                session.execute(
                    select(PredictionMarket)
                    .where(PredictionMarket.id == int(market_id))
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not market:
                raise ValueError("market not found")
            if int(market.status) != 1:
                raise ValueError("market not open")
            if market.betting_deadline and int(now_ts) >= int(market.betting_deadline):
                raise ValueError("betting closed")

            user_total = session.execute(
                select(func.coalesce(func.sum(PredictionBet.amount), 0)).where(
                    PredictionBet.market_id == int(market.id),
                    PredictionBet.tg_id == int(tg_id),
                )
            ).scalar_one()
            if int(user_total or 0) + int(amount) > int(market.max_bet_per_user):
                raise ValueError("max bet per user exceeded")

            stats = (
                session.execute(
                    select(Statistics)
                    .where(Statistics.tg_id == int(tg_id))
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not stats:
                raise ValueError("user stats not found")
            if float(stats.credits) < float(amount):
                raise ValueError("insufficient credits")

            stats.credits = round(float(stats.credits) - float(amount), 2)

            bet = PredictionBet(
                market_id=int(market.id),
                tg_id=int(tg_id),
                option=int(option),
                amount=int(amount),
            )
            session.add(bet)

            if int(option) == 1:
                market.real_yes_pool = int(market.real_yes_pool) + int(amount)
            else:
                market.real_no_pool = int(market.real_no_pool) + int(amount)

            session.flush()

            yes_odds, no_odds = self._calc_prediction_odds(
                int(market.real_yes_pool),
                int(market.real_no_pool),
                int(market.virtual_yes_pool),
                int(market.virtual_no_pool),
            )

            return {
                "bet": {
                    "id": int(bet.id),
                    "market_id": int(market.id),
                    "tg_id": int(tg_id),
                    "option": int(option),
                    "amount": int(amount),
                },
                "market": {
                    "id": int(market.id),
                    "title": market.title,
                    "description": market.description,
                    "status": int(market.status),
                    "result_option": int(market.result_option)
                    if market.result_option is not None
                    else None,
                    "betting_deadline": int(market.betting_deadline)
                    if market.betting_deadline is not None
                    else None,
                    "real_yes_pool": int(market.real_yes_pool),
                    "real_no_pool": int(market.real_no_pool),
                    "virtual_yes_pool": int(market.virtual_yes_pool),
                    "virtual_no_pool": int(market.virtual_no_pool),
                    "yes_odds": yes_odds,
                    "no_odds": no_odds,
                    "max_bet_per_user": int(market.max_bet_per_user),
                    "fee_rate_bp": int(market.fee_rate_bp),
                    "fee_burn_bp": int(market.fee_burn_bp),
                    "fee_glory_bp": int(market.fee_glory_bp),
                    "resolution_note": market.resolution_note,
                    "total_fee_collected": int(market.total_fee_collected),
                    "fee_burned": int(market.fee_burned),
                    "fee_to_glory": int(market.fee_to_glory),
                    "my_yes_amount": int(user_total or 0) + int(amount)
                    if int(option) == 1
                    else 0,
                    "my_no_amount": int(user_total or 0) + int(amount)
                    if int(option) == 0
                    else 0,
                    "created_at": market.created_at,
                },
                "user_credits": round(float(stats.credits), 2),
            }

    def list_prediction_bets(self, market_id: int, limit: int = 100) -> list[dict]:
        from app.utils.utils import get_user_name_from_tg_id

        with get_session() as session:
            rows = (
                session.execute(
                    select(PredictionBet)
                    .where(PredictionBet.market_id == int(market_id))
                    .order_by(PredictionBet.id.desc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [
                {
                    "id": int(r.id),
                    "market_id": int(r.market_id),
                    "tg_id": int(r.tg_id),
                    "tg_username": str(
                        get_user_name_from_tg_id(int(r.tg_id)) or r.tg_id
                    ),
                    "option": int(r.option),
                    "amount": int(r.amount),
                    "created_at": r.created_at,
                }
                for r in rows
            ]

    def list_prediction_user_positions(self, market_id: int) -> list[dict]:
        """按用户聚合某个预测题目的 YES/NO 持仓。"""
        with get_session() as session:
            rows = session.execute(
                select(
                    PredictionBet.tg_id,
                    PredictionBet.option,
                    func.coalesce(func.sum(PredictionBet.amount), 0),
                )
                .where(PredictionBet.market_id == int(market_id))
                .group_by(PredictionBet.tg_id, PredictionBet.option)
            ).all()

            user_positions: dict[int, dict] = {}
            for tg_id, option, amount in rows:
                uid = int(tg_id)
                if uid not in user_positions:
                    user_positions[uid] = {
                        "tg_id": uid,
                        "yes_amount": 0,
                        "no_amount": 0,
                    }
                if int(option) == 1:
                    user_positions[uid]["yes_amount"] = int(amount or 0)
                else:
                    user_positions[uid]["no_amount"] = int(amount or 0)

            return list(user_positions.values())

    def close_prediction_market_betting(self, market_id: int) -> dict:
        with get_session() as session:
            market = (
                session.execute(
                    select(PredictionMarket)
                    .where(PredictionMarket.id == int(market_id))
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not market:
                raise ValueError("market not found")
            if int(market.status) != 1:
                raise ValueError("market not open")

            market.status = 2
            session.flush()
            return {"market_id": int(market.id), "status": int(market.status)}

    def resolve_prediction_market(
        self,
        market_id: int,
        result_option: int,
        resolved_by: int,
        resolution_note: Optional[str] = None,
    ) -> dict:
        if int(result_option) not in [0, 1]:
            raise ValueError("invalid result option")

        now_ts = int(time.time())
        with get_session() as session:
            market = (
                session.execute(
                    select(PredictionMarket)
                    .where(PredictionMarket.id == int(market_id))
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not market:
                raise ValueError("market not found")
            if int(market.status) in [3, 4]:
                raise ValueError("market already settled")

            total_real_pool = int(market.real_yes_pool) + int(market.real_no_pool)
            fee_burned = int(total_real_pool * int(market.fee_burn_bp) / 10000)
            fee_to_glory = int(total_real_pool * int(market.fee_glory_bp) / 10000)
            total_fee = int(fee_burned + fee_to_glory)
            base_payout_pool = int(total_real_pool - total_fee)

            winner_pool = (
                int(market.real_yes_pool)
                if int(result_option) == 1
                else int(market.real_no_pool)
            )
            loser_pool = int(total_real_pool - winner_pool)

            cfg = (
                session.execute(
                    select(SystemConfig)
                    .where(
                        SystemConfig.config_type == "prediction_market",
                        SystemConfig.config_key == "glory_fund",
                    )
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            # 荣耀奖池为**跨活动共用**的单一余额：除本活动的手续费外，21 点的抽水
            # 亦按比例注入其中（见 blackjack_engine 与 _settle_blackjack_hand）。
            # config_type 沿用 prediction_market 属历史命名，未迁移是为了不改动
            # 已上线的结算逻辑。
            #
            # 余额以**小数**字符串存储：21 点的单手注入天然为小数（注 5 普通胜的
            # 荣耀份额为 0.06），故此处必须用 float 解析——用 int() 会在读到小数
            # 时抛错并把余额静默清零。既有的整数字符串余额亦可被 float() 正常读入。
            if cfg:
                try:
                    current_glory = float(cfg.config_value or "0")
                except Exception:
                    current_glory = 0.0
            else:
                current_glory = 0.0

            # 默认：按常规 95% 奖池分发
            payout_pool = int(base_payout_pool)
            glory_pool_extra_in = 0
            glory_pool_extra_out = 0

            # 情况1：没有胜方（开奖侧无人押中）
            # 95% 奖池不再分发，全部并入荣耀奖池。
            if int(winner_pool) <= 0 and int(base_payout_pool) > 0:
                glory_pool_extra_in = int(base_payout_pool)
                payout_pool = 0
            # 情况2：全部为胜方、没有败方
            # 从荣耀奖池提取手续费 1.5 倍用于补偿发放（余额不足则按余额发放）。
            elif int(winner_pool) > 0 and int(loser_pool) <= 0 and int(total_fee) > 0:
                target_compensation = int(float(total_fee) * 1.5)
                # 补偿以整数积分发放，故可用额向下取整；余额的小数部分留在池中
                available_glory = max(0, int(current_glory))
                glory_pool_extra_out = min(
                    int(target_compensation), int(available_glory)
                )
                payout_pool = int(base_payout_pool + glory_pool_extra_out)

            payout_map: dict[int, float] = {}
            winner_count = 0
            if winner_pool > 0 and payout_pool > 0:
                winner_rows = session.execute(
                    select(
                        PredictionBet.tg_id,
                        func.coalesce(func.sum(PredictionBet.amount), 0),
                    )
                    .where(
                        PredictionBet.market_id == int(market.id),
                        PredictionBet.option == int(result_option),
                    )
                    .group_by(PredictionBet.tg_id)
                ).all()

                winner_count = len(winner_rows)
                for tg_id, user_amt in winner_rows:
                    ratio = float(user_amt) / float(winner_pool)
                    payout = round(float(payout_pool) * ratio, 2)
                    payout_map[int(tg_id)] = payout

                if payout_map:
                    stats_rows = (
                        session.execute(
                            select(Statistics)
                            .where(Statistics.tg_id.in_(list(payout_map.keys())))
                            .with_for_update()
                        )
                        .scalars()
                        .all()
                    )
                    stats_map = {int(s.tg_id): s for s in stats_rows}
                    for uid, payout in payout_map.items():
                        stats = stats_map.get(int(uid))
                        if stats:
                            stats.credits = round(
                                float(stats.credits) + float(payout), 2
                            )
                        else:
                            session.add(
                                Statistics(
                                    tg_id=int(uid), donation=0, credits=float(payout)
                                )
                            )

            market.status = 3
            market.result_option = int(result_option)
            market.resolution_note = resolution_note
            market.total_fee_collected = int(total_real_pool - payout_pool)
            market.fee_burned = int(fee_burned)
            market.fee_to_glory = int(fee_to_glory)
            market.resolved_by = int(resolved_by)
            market.resolved_at = int(now_ts)

            final_glory_balance = round(
                float(current_glory)
                + float(fee_to_glory)
                + float(glory_pool_extra_in)
                - float(glory_pool_extra_out),
                2,
            )
            if cfg:
                cfg.config_value = str(final_glory_balance)
                cfg.updated_at = int(now_ts)
            else:
                session.add(
                    SystemConfig(
                        config_type="prediction_market",
                        config_key="glory_fund",
                        config_value=str(final_glory_balance),
                        created_at=int(now_ts),
                        updated_at=int(now_ts),
                    )
                )

            session.flush()

            return {
                "market_id": int(market.id),
                "status": int(market.status),
                "result_option": int(result_option),
                "total_real_pool": int(total_real_pool),
                "total_fee": int(total_fee),
                "fee_burned": int(fee_burned),
                "fee_to_glory": int(fee_to_glory),
                "winner_count": int(winner_count),
                "payout_pool": int(payout_pool),
            }

    def _get_prediction_settled_market_meta(
        self, session
    ) -> tuple[dict[int, dict], dict[int, int]]:
        """获取已结算预测市场的元信息与中奖侧总池。"""
        market_rows = session.execute(
            select(
                PredictionMarket.id,
                PredictionMarket.title,
                PredictionMarket.result_option,
                PredictionMarket.status,
                PredictionMarket.real_yes_pool,
                PredictionMarket.real_no_pool,
                PredictionMarket.total_fee_collected,
                PredictionMarket.resolved_at,
            ).where(
                PredictionMarket.status == 3,
                PredictionMarket.result_option.isnot(None),
            )
        ).all()

        market_map: dict[int, dict] = {}
        for row in market_rows:
            market_id = int(row[0])
            total_real_pool = int(row[4] or 0) + int(row[5] or 0)
            total_fee = int(row[6] or 0)
            payout_pool = max(0.0, float(total_real_pool - total_fee))
            market_map[market_id] = {
                "market_id": market_id,
                "title": str(row[1] or ""),
                "result_option": int(row[2]),
                "payout_pool": payout_pool,
                "resolved_at": int(row[7]) if row[7] is not None else None,
            }

        winner_pool_rows = session.execute(
            select(
                PredictionBet.market_id,
                func.coalesce(func.sum(PredictionBet.amount), 0),
            )
            .join(
                PredictionMarket,
                PredictionBet.market_id == PredictionMarket.id,
            )
            .where(
                PredictionMarket.status == 3,
                PredictionMarket.result_option.isnot(None),
                PredictionBet.option == PredictionMarket.result_option,
            )
            .group_by(PredictionBet.market_id)
        ).all()
        winner_pool_map = {int(r[0]): int(r[1] or 0) for r in winner_pool_rows}

        return market_map, winner_pool_map

    def get_prediction_user_stats(self, tg_id: int) -> dict:
        """获取用户大预言家个人统计（已结算净盈亏/胜率/最近结算记录）。"""
        try:
            with get_session() as session:
                market_map, winner_pool_map = self._get_prediction_settled_market_meta(
                    session
                )

                settled_positions = session.execute(
                    select(
                        PredictionBet.market_id,
                        func.coalesce(
                            func.sum(
                                case(
                                    (PredictionBet.option == 1, PredictionBet.amount),
                                    else_=0,
                                )
                            ),
                            0,
                        ).label("yes_amount"),
                        func.coalesce(
                            func.sum(
                                case(
                                    (PredictionBet.option == 0, PredictionBet.amount),
                                    else_=0,
                                )
                            ),
                            0,
                        ).label("no_amount"),
                    )
                    .join(
                        PredictionMarket, PredictionBet.market_id == PredictionMarket.id
                    )
                    .where(
                        PredictionBet.tg_id == int(tg_id),
                        PredictionMarket.status == 3,
                        PredictionMarket.result_option.isnot(None),
                    )
                    .group_by(PredictionBet.market_id)
                    .order_by(PredictionBet.market_id.desc())
                ).all()

                total_bet_amount = 0.0
                total_payout_amount = 0.0
                settled_markets = 0
                win_markets = 0
                recent_settlements = []

                for market_id_raw, yes_amount_raw, no_amount_raw in settled_positions:
                    market_id = int(market_id_raw)
                    market_meta = market_map.get(market_id)
                    if not market_meta:
                        continue

                    yes_amount = int(yes_amount_raw or 0)
                    no_amount = int(no_amount_raw or 0)
                    bet_amount = float(yes_amount + no_amount)
                    result_option = int(market_meta["result_option"])
                    win_amount = yes_amount if result_option == 1 else no_amount
                    winner_pool = int(winner_pool_map.get(market_id, 0))
                    payout_pool = float(market_meta["payout_pool"])

                    payout_amount = 0.0
                    if winner_pool > 0 and payout_pool > 0 and win_amount > 0:
                        payout_amount = round(
                            (payout_pool * float(win_amount)) / float(winner_pool), 2
                        )

                    net_profit = round(payout_amount - bet_amount, 2)

                    settled_markets += 1
                    total_bet_amount += bet_amount
                    total_payout_amount += payout_amount
                    if win_amount > 0 and payout_amount > 0:
                        win_markets += 1

                    if len(recent_settlements) < 10:
                        recent_settlements.append(
                            {
                                "market_id": market_id,
                                "title": market_meta["title"],
                                "result_option": result_option,
                                "yes_amount": yes_amount,
                                "no_amount": no_amount,
                                "bet_amount": round(bet_amount, 2),
                                "payout_amount": round(payout_amount, 2),
                                "net_profit": net_profit,
                                "is_win": win_amount > 0 and payout_amount > 0,
                                "resolved_at": market_meta["resolved_at"],
                            }
                        )

                unsettled = session.execute(
                    select(
                        func.count(func.distinct(PredictionBet.market_id)),
                        func.coalesce(func.sum(PredictionBet.amount), 0),
                    )
                    .join(
                        PredictionMarket, PredictionBet.market_id == PredictionMarket.id
                    )
                    .where(
                        PredictionBet.tg_id == int(tg_id),
                        PredictionMarket.status.in_([1, 2]),
                    )
                ).one()
                unsettled_markets = int(unsettled[0] or 0)
                unsettled_bet_amount = round(float(unsettled[1] or 0), 2)

                net_profit_total = round(total_payout_amount - total_bet_amount, 2)
                win_rate = (
                    round((float(win_markets) / float(settled_markets)) * 100, 2)
                    if settled_markets > 0
                    else 0.0
                )

                return {
                    "settled_markets": int(settled_markets),
                    "win_markets": int(win_markets),
                    "win_rate": float(win_rate),
                    "total_bet_amount": round(float(total_bet_amount), 2),
                    "total_payout_amount": round(float(total_payout_amount), 2),
                    "net_profit": float(net_profit_total),
                    "unsettled_markets": int(unsettled_markets),
                    "unsettled_bet_amount": float(unsettled_bet_amount),
                    "recent_settlements": recent_settlements,
                }
        except Exception as e:
            logger.error(f"Error getting prediction user stats: {e}")
            return {
                "settled_markets": 0,
                "win_markets": 0,
                "win_rate": 0.0,
                "total_bet_amount": 0.0,
                "total_payout_amount": 0.0,
                "net_profit": 0.0,
                "unsettled_markets": 0,
                "unsettled_bet_amount": 0.0,
                "recent_settlements": [],
            }

    def _get_prediction_user_rank_stats(self) -> list[dict]:
        """聚合所有用户在已结算预测题目的统计。"""
        with get_session() as session:
            market_map, winner_pool_map = self._get_prediction_settled_market_meta(
                session
            )
            if not market_map:
                return []

            positions = session.execute(
                select(
                    PredictionBet.tg_id,
                    PredictionBet.market_id,
                    func.coalesce(
                        func.sum(
                            case(
                                (PredictionBet.option == 1, PredictionBet.amount),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("yes_amount"),
                    func.coalesce(
                        func.sum(
                            case(
                                (PredictionBet.option == 0, PredictionBet.amount),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("no_amount"),
                )
                .join(PredictionMarket, PredictionBet.market_id == PredictionMarket.id)
                .where(
                    PredictionMarket.status == 3,
                    PredictionMarket.result_option.isnot(None),
                )
                .group_by(PredictionBet.tg_id, PredictionBet.market_id)
            ).all()

            stats_map: Dict[int, dict] = {}
            for tg_id_raw, market_id_raw, yes_amount_raw, no_amount_raw in positions:
                tg_id = int(tg_id_raw)
                market_id = int(market_id_raw)
                market_meta = market_map.get(market_id)
                if not market_meta:
                    continue

                yes_amount = int(yes_amount_raw or 0)
                no_amount = int(no_amount_raw or 0)
                bet_amount = float(yes_amount + no_amount)
                result_option = int(market_meta["result_option"])
                win_amount = yes_amount if result_option == 1 else no_amount
                winner_pool = int(winner_pool_map.get(market_id, 0))
                payout_pool = float(market_meta["payout_pool"])

                payout_amount = 0.0
                if winner_pool > 0 and payout_pool > 0 and win_amount > 0:
                    payout_amount = round(
                        (payout_pool * float(win_amount)) / float(winner_pool), 2
                    )

                item = stats_map.setdefault(
                    tg_id,
                    {
                        "tg_id": tg_id,
                        "settled_markets": 0,
                        "win_markets": 0,
                        "total_bet_amount": 0.0,
                        "total_payout_amount": 0.0,
                        "net_profit": 0.0,
                        "win_rate": 0.0,
                    },
                )

                item["settled_markets"] += 1
                item["total_bet_amount"] = round(
                    item["total_bet_amount"] + bet_amount, 2
                )
                item["total_payout_amount"] = round(
                    item["total_payout_amount"] + payout_amount, 2
                )
                if win_amount > 0 and payout_amount > 0:
                    item["win_markets"] += 1

            for data in stats_map.values():
                data["net_profit"] = round(
                    float(data["total_payout_amount"])
                    - float(data["total_bet_amount"]),
                    2,
                )
                settled_markets = int(data["settled_markets"])
                win_markets = int(data["win_markets"])
                data["win_rate"] = (
                    round((float(win_markets) / float(settled_markets)) * 100, 2)
                    if settled_markets > 0
                    else 0.0
                )

            return list(stats_map.values())

    def get_prediction_net_profit_rank(self) -> list[dict]:
        """获取大预言家净盈亏排行榜。"""
        try:
            stats = self._get_prediction_user_rank_stats()
            stats.sort(
                key=lambda x: (
                    float(x.get("net_profit", 0)),
                    int(x.get("settled_markets", 0)),
                ),
                reverse=True,
            )
            return stats
        except Exception as e:
            logger.error(f"Error getting prediction net profit rank: {e}")
            return []

    def get_prediction_win_rate_rank(self) -> list[dict]:
        """获取大预言家胜率排行榜。"""
        try:
            stats = self._get_prediction_user_rank_stats()
            stats = [item for item in stats if int(item.get("settled_markets", 0)) > 0]
            stats.sort(
                key=lambda x: (
                    float(x.get("win_rate", 0)),
                    int(x.get("settled_markets", 0)),
                    float(x.get("net_profit", 0)),
                ),
                reverse=True,
            )
            return stats
        except Exception as e:
            logger.error(f"Error getting prediction win rate rank: {e}")
            return []

    def get_credits_rank(self) -> list:
        """获取积分排行"""
        with get_session() as session:
            stmt = select(Statistics.tg_id, Statistics.credits).order_by(
                Statistics.credits.desc()
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1]) for r in results]

    def get_donation_rank(self) -> list:
        """获取捐赠排行"""
        with get_session() as session:
            stmt = select(Statistics.tg_id, Statistics.donation).order_by(
                Statistics.donation.desc()
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1]) for r in results]

    def get_plex_watched_time_rank(self) -> list:
        """获取 Plex 观看时长排行"""
        with get_session() as session:
            stmt = select(
                PlexUser.plex_id,
                PlexUser.tg_id,
                PlexUser.plex_username,
                PlexUser.watched_time,
                PlexUser.is_premium,
            ).order_by(PlexUser.watched_time.desc())
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1], r[2], r[3], r[4]) for r in results]

    def get_emby_watched_time_rank(self) -> list:
        """获取 Emby 观看时长排行"""
        with get_session() as session:
            stmt = select(
                EmbyUser.emby_id,
                EmbyUser.emby_username,
                EmbyUser.emby_watched_time,
                EmbyUser.is_premium,
                EmbyUser.tg_id,
            ).order_by(EmbyUser.emby_watched_time.desc())
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1], r[2], r[3], r[4]) for r in results]

    def get_invitation_rank(self) -> list:
        """获取邀请排行榜数据"""
        with get_session() as session:
            stmt = (
                select(
                    Invitation.owner,
                    func.count(func.distinct(Invitation.used_by)).label("invite_count"),
                )
                .where(Invitation.is_used == 1, Invitation.used_by.isnot(None))
                .group_by(Invitation.owner)
                .order_by(func.count(func.distinct(Invitation.used_by)).desc())
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1]) for r in results]

    def get_wheel_credits_rank(self) -> list:
        """获取幸运大转盘积分变动排行榜（统计所有游戏结果）"""
        with get_session() as session:
            total_credits_change = func.sum(WheelStats.credits_change).label(
                "total_credits_change"
            )
            play_count = func.count(WheelStats.id).label("play_count")
            stmt = (
                select(WheelStats.tg_id, total_credits_change, play_count)
                .group_by(WheelStats.tg_id)
                .order_by(total_credits_change.desc())
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], float(r[1] or 0), int(r[2] or 0)) for r in results]

    def get_wheel_invite_code_rank(self) -> list:
        """获取幸运大转盘邀请码获得排行榜"""
        with get_session() as session:
            invite_count = func.count(WheelStats.id).label("invite_count")
            stmt = (
                select(WheelStats.tg_id, invite_count)
                .where(WheelStats.item_name == "邀请码 1 枚")
                .group_by(WheelStats.tg_id)
                .order_by(invite_count.desc())
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], int(r[1] or 0)) for r in results if int(r[1] or 0) > 0]

    def _blackjack_rank_rows(self, session, min_hands: int) -> list:
        """一次扫描算出准确率榜与胜率榜共用的聚合。

        两个榜单的口径只差排序字段，分开查会对同一张表做两次全表扫描。

        胜率的分母是**已结束的手数**，分子是判为玩家胜的手数（含天胡胜）；平局
        既不计胜也不计负，但仍计入分母——它确实消耗了一手。
        """
        from app import blackjack_engine as engine

        win_flag = case(
            (
                BlackjackHand.outcome.in_(
                    [engine.OUTCOME_WIN, engine.OUTCOME_BLACKJACK]
                ),
                1,
            ),
            else_=0,
        )
        hand_count = func.count(BlackjackHand.id).label("hand_count")
        wins = func.sum(win_flag).label("wins")
        dec_total = func.sum(BlackjackHand.decisions_total).label("dec_total")
        dec_correct = func.sum(BlackjackHand.decisions_correct).label("dec_correct")

        stmt = (
            select(BlackjackHand.tg_id, hand_count, wins, dec_total, dec_correct)
            .where(BlackjackHand.status.in_(engine.TERMINAL_STATUSES))
            .group_by(BlackjackHand.tg_id)
            .having(func.count(BlackjackHand.id) >= int(min_hands))
        )
        rows = []
        for r in session.execute(stmt).all():
            hands = int(r[1] or 0)
            dt = int(r[3] or 0)
            rows.append(
                {
                    "tg_id": r[0],
                    "hand_count": hands,
                    "win_rate": round(float(r[2] or 0) / hands * 100, 2)
                    if hands
                    else 0.0,
                    "decisions_total": dt,
                    "accuracy": round(float(r[4] or 0) / dt * 100, 2) if dt else 0.0,
                }
            )
        return rows

    def get_blackjack_skill_ranks(self, min_hands: Optional[int] = None) -> dict:
        """一次扫描同时算出准确率榜与胜率榜，返回 `{accuracy, win_rate}`。

        榜单接口两个榜都要，分别调用 `get_blackjack_accuracy_rank()` 与
        `get_blackjack_win_rate_rank()` 会各开一个 session、各跑一遍同样的
        GROUP BY 全表聚合，还会各读一次配置——正是 `_blackjack_rank_rows`
        当初想避免的两次扫描。故路由层应当调用本方法。
        """
        if min_hands is None:
            min_hands = int(self.get_blackjack_config_dict().get("rank_min_hands", 100))
        try:
            with get_session() as session:
                rows = self._blackjack_rank_rows(session, min_hands)
            return {
                # 没做过任何决策的用户（全是开局天胡）不入准确率榜
                "accuracy": sorted(
                    [r for r in rows if r["decisions_total"] > 0],
                    key=lambda r: r["accuracy"],
                    reverse=True,
                ),
                "win_rate": sorted(
                    list(rows), key=lambda r: r["win_rate"], reverse=True
                ),
            }
        except Exception as e:
            logger.error(f"获取 21 点技巧类排行失败: {e}")
            return {"accuracy": [], "win_rate": []}

    def get_blackjack_accuracy_rank(self, min_hands: Optional[int] = None) -> list:
        """决策准确率排行榜——21 点游戏榜的主榜。

        准确率是本游戏里唯一**零方差**的口径：同一局面的基本策略建议恒定，故它
        纯粹反映技巧，不受运气影响。这正是它取代净积分变动榜作为主榜的原因。

        设最低手数门槛，样本量不足的用户不入榜。同时需要两个榜时改用
        `get_blackjack_skill_ranks()`，避免重复扫描。

        Returns: [{tg_id, accuracy, win_rate, hand_count, decisions_total}, ...] 按准确率降序
        """
        return self.get_blackjack_skill_ranks(min_hands)["accuracy"]

    def get_blackjack_win_rate_rank(self, min_hands: Optional[int] = None) -> list:
        """胜率排行榜。按量归一化，故不奖励刷量；设最低手数门槛。

        同时需要两个榜时改用 `get_blackjack_skill_ranks()`，避免重复扫描。

        Returns: [{tg_id, win_rate, accuracy, hand_count}, ...] 按胜率降序
        """
        return self.get_blackjack_skill_ranks(min_hands)["win_rate"]

    def get_blackjack_max_win_rank(self) -> list:
        """获取 21 点单手最大赢利排行榜

        单手净赢利 = payout − 该手总押注。**不含奖池派彩**——并入的话这个榜会
        退化成奖池中奖者名单，失去「谁打出过最漂亮的一手」的意义。

        只统计已结束的手牌，且只保留净赢利为正的用户。本榜不设手数门槛：它是
        高光时刻展示而非技术排名，一手也可以上榜。

        Returns: [(tg_id, max_win, hand_count), ...] 按单手最大赢利降序
        """
        from app import blackjack_engine as engine

        with get_session() as session:
            total_stake = case(
                (BlackjackHand.doubled == 1, BlackjackHand.bet_credits * 2),
                else_=BlackjackHand.bet_credits,
            )
            max_win = func.max(
                func.coalesce(BlackjackHand.payout_credits, 0) - total_stake
            ).label("max_win")
            hand_count = func.count(BlackjackHand.id).label("hand_count")
            stmt = (
                select(BlackjackHand.tg_id, max_win, hand_count)
                .where(BlackjackHand.status.in_(engine.TERMINAL_STATUSES))
                .group_by(BlackjackHand.tg_id)
                .order_by(max_win.desc())
            )
            results = session.execute(stmt).fetchall()
            return [
                (r[0], round(float(r[1] or 0), 2), int(r[2] or 0))
                for r in results
                if float(r[1] or 0) > 0
            ]

    def get_treasure_win_issue_rank(self) -> list:
        """获取夺宝奇兵中奖期数排行榜"""
        with get_session() as session:
            win_count = func.count(TreasureIssue.id).label("win_count")
            stmt = (
                select(TreasureIssue.winner_tg_id, win_count)
                .where(
                    TreasureIssue.status == 2,
                    TreasureIssue.winner_tg_id.isnot(None),
                )
                .group_by(TreasureIssue.winner_tg_id)
                .order_by(win_count.desc())
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], int(r[1] or 0)) for r in results if int(r[1] or 0) > 0]

    def get_treasure_win_credits_rank(self) -> list:
        """获取夺宝奇兵中奖积分排行榜"""
        with get_session() as session:
            win_credits = func.sum(TreasureIssue.prize_credits).label("win_credits")
            stmt = (
                select(TreasureIssue.winner_tg_id, win_credits)
                .where(
                    TreasureIssue.status == 2,
                    TreasureIssue.winner_tg_id.isnot(None),
                )
                .group_by(TreasureIssue.winner_tg_id)
                .order_by(win_credits.desc())
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], int(r[1] or 0)) for r in results if int(r[1] or 0) > 0]

    def get_badge_rank(self) -> List[dict]:
        """
        获取勋章排行榜数据（按用户拥有的勋章数量排序）

        Returns:
            用户勋章排行数据列表，包含 tg_id, badge_count, badges 信息
        """
        try:
            with get_session() as session:
                # 查询每个用户拥有的勋章数量，并获取勋章详情
                stmt = (
                    select(
                        UserBadge.tg_id,
                        func.count(UserBadge.id).label("badge_count"),
                    )
                    .where(UserBadge.is_active == 1)
                    .group_by(UserBadge.tg_id)
                    .order_by(func.count(UserBadge.id).desc())
                )
                results = session.execute(stmt).fetchall()

                rank_data = []
                for row in results:
                    tg_id = row[0]
                    badge_count = row[1]

                    # 获取该用户的所有勋章详情
                    badges_stmt = (
                        select(UserBadge)
                        .options(joinedload(UserBadge.badge))
                        .where(UserBadge.tg_id == tg_id, UserBadge.is_active == 1)
                        .order_by(UserBadge.redeemed_at.desc())
                    )
                    user_badges = session.execute(badges_stmt).scalars().unique().all()

                    rank_data.append(
                        {
                            "tg_id": tg_id,
                            "badge_count": badge_count,
                            "badges": [
                                self._user_badge_to_dict(ub) for ub in user_badges
                            ],
                        }
                    )

                return rank_data
        except Exception as e:
            logger.error(f"获取勋章排行榜失败: {e}")
            return []

    # ==================== Blackjack (21 点) Operations ====================

    def _blackjack_hand_to_dict(self, hand: BlackjackHand) -> dict:
        """把手牌行转为字典。

        **有意包含 `deck_seed` 与 `next_card_index`**：本方法服务于服务端内部
        （路由、结算、调度任务），响应层的 schema 显式列字段、不复用本 dump，
        种子与游标不会因此泄漏到面向用户的响应里（见 schemas/blackjack.py）。
        """
        return {
            "id": int(hand.id),
            "tg_id": int(hand.tg_id),
            "status": int(hand.status),
            "bet_credits": int(hand.bet_credits),
            "doubled": int(hand.doubled),
            "deck_seed": str(hand.deck_seed),
            "next_card_index": int(hand.next_card_index),
            "player_cards": json.loads(hand.player_cards or "[]"),
            "dealer_cards": json.loads(hand.dealer_cards or "[]"),
            "outcome": hand.outcome,
            "payout_credits": float(hand.payout_credits)
            if hand.payout_credits is not None
            else None,
            "rake_credits": float(hand.rake_credits)
            if hand.rake_credits is not None
            else None,
            "jackpot_won": float(hand.jackpot_won)
            if hand.jackpot_won is not None
            else None,
            "decisions_total": int(hand.decisions_total),
            "decisions_correct": int(hand.decisions_correct),
            "rake_waived": int(hand.rake_waived) == 1,
            "rake_bp_on_profit": int(hand.rake_bp_on_profit),
            "rake_jackpot_bp": int(hand.rake_jackpot_bp),
            "blackjack_payout": float(hand.blackjack_payout),
            "dealer_hits_soft_17": int(hand.dealer_hits_soft_17),
            "hand_timeout_minutes": int(hand.hand_timeout_minutes),
            "created_at_ms": int(hand.created_at_ms),
            "settled_at": int(hand.settled_at) if hand.settled_at is not None else None,
        }

    def _settle_blackjack_hand(
        self,
        session,
        hand: BlackjackHand,
        abandoned: bool = False,
        jackpot_config: Optional[dict] = None,
    ) -> dict:
        """21 点结算的共用路径：停牌 / 加倍 / 爆牌 / 超时兜底四条入口都走这里。

        调用方**必须**已对 `hand` 行取过 FOR UPDATE。锁顺序固定为
        hand → statistics → system_config，全路径一致以避免死锁。

        `abandoned=True` 表示由超时兜底触发：结算口径与玩家停牌完全相同
        （庄家按规则补牌、正常判定胜负），只是终态记为已弃牌以便区分来源；
        绝不因超时直接判负。

        **幂等由条件 UPDATE（compare-and-swap）保证，而非读取 status 后判断。**
        终态的写入带 `WHERE status IN (非终态)` 条件，只有把手牌从非终态成功改成
        终态的那一方才继续计入积分与注入奖池；`rowcount == 0` 说明已被他人结算，
        直接返回既有结果。

        为什么不能只靠「FOR UPDATE 后读 status」：SQLite 无行级锁，
        `with_for_update()` 在该方言下是 no-op，两个并发事务可以各自读到
        status=1、各自算出赔付、再依次写入，造成**重复赔付**（已实测复现）。
        条件 UPDATE 不依赖行锁，在 SQLite 与 PostgreSQL 上都成立。

        **加锁顺序：手牌 → statistics → system_config（奖池）。**
        本方法内部据此把 Statistics 的行锁取在奖池之前。这条顺序是全局的，
        发牌与加倍路径先锁 Statistics 再进入本方法，同样成立。任何新增的写路径
        都必须遵守它——奖池是一行**全局共享**的记录，一旦有人反着来，
        PostgreSQL 上就会出现只在并发下复现的死锁。
        """
        from app import blackjack_engine as engine

        # 先做一次廉价的前置检查：多数重复请求在这里就被挡掉，省去无谓的计算。
        # 但它**不是**幂等的保证——真正的保证是下方的条件 UPDATE。
        if int(hand.status) in engine.TERMINAL_STATUSES:
            return {
                "hand": self._blackjack_hand_to_dict(hand),
                "already_settled": True,
            }

        hand_id = int(hand.id)
        tg_id = int(hand.tg_id)
        bet = int(hand.bet_credits)
        doubled = int(hand.doubled) == 1
        player_cards = json.loads(hand.player_cards or "[]")
        dealer_cards = json.loads(hand.dealer_cards or "[]")

        # 按手牌上的参数快照结算，而非读当前配置——管理员改配置不影响本手牌
        blackjack_payout = float(hand.blackjack_payout)
        hits_soft_17 = int(hand.dealer_hits_soft_17) == 1
        rake_bp = int(hand.rake_bp_on_profit)
        rake_jackpot_bp = int(hand.rake_jackpot_bp)

        # 奖池的开关与派彩比例不随手牌快照——它们是奖池自身的运营参数，
        # 而非本手牌的结算口径；奖池余额本就是全局共享、随时在变的。
        #
        # 配置由调用方在**开启事务之前**读好传入：本方法运行在调用方的事务里，
        # 若在此处调 get_blackjack_config_dict() 会另开一个 session，使每次结算
        # 同时占用两个连接（池只有 5+10），且首次读取还会在新连接上写库——外层
        # 正持有行锁时这会直接死锁。
        if jackpot_config is None:
            jackpot_config = self.get_blackjack_config_dict()
        jackpot_enabled = bool(jackpot_config.get("jackpot_enabled", True))
        jackpot_suited_pct = float(jackpot_config.get("jackpot_suited_bj_pct", 10))

        deck = engine.build_deck(str(hand.deck_seed))
        next_index = int(hand.next_card_index)

        # 庄家在两种情形下不补牌：
        #   1. 玩家爆牌——spec：庄家 SHALL NOT 补牌
        #   2. 开局任一方天胡——spec：手牌 SHALL 直接进入已结算，不经玩家回合，
        #      而庄家 SHALL 在玩家停牌或加倍后才开始补牌
        # 第 2 条曾被漏掉：天胡虽然赔付正确（resolve 优先判天胡），但庄家会照常
        # 补牌，幽灵牌被写进 dealer_cards，前端于是回放「庄家逐张补牌甚至爆牌」
        # 之后再打出「天胡」，牌面完全是编造的。
        #
        # 走到停牌/加倍/超时时双方都不可能再有天胡（天胡在发牌时就结算了），
        # 故这个判定只会在发牌路径上为真。
        settled_on_deal = engine.is_natural_blackjack(
            player_cards
        ) or engine.is_natural_blackjack(dealer_cards)
        if engine.is_bust(player_cards) or settled_on_deal:
            final_dealer_cards = dealer_cards
        else:
            final_dealer_cards, next_index = engine.play_dealer(
                deck, dealer_cards, next_index, hits_soft_17=hits_soft_17
            )

        outcome, return_multiplier, profit_multiplier = engine.resolve(
            player_cards,
            final_dealer_cards,
            doubled=doubled,
            blackjack_payout=blackjack_payout,
        )

        # 抽水仅对净赢利计取；判负与平局的 profit_multiplier 为 0，故自然零抽水。
        # 一律 round(x, 2) 而非 int()：注 5 普通胜的抽水为 0.15，取整会被抹为零，
        # 形成鼓励刷小注的偏差。
        gross_profit = round(float(profit_multiplier) * float(bet), 2)
        rake = 0.0
        if gross_profit > 0:
            rake = round(gross_profit * float(rake_bp) / 10000.0, 2)
        payout = round(float(return_multiplier) * float(bet) - rake, 2)

        final_status = engine.STATUS_ABANDONED if abandoned else engine.STATUS_SETTLED
        now_ts = int(time.time())

        # 以上都是无副作用的纯计算。真正的幂等闸门在此：只有把手牌从非终态原子地
        # 改成终态的那一方，才有权继续写积分与奖池。先把 ORM 层的挂起改动刷下去，
        # 使随后的条件 UPDATE 读到的是最新状态。
        session.flush()
        claimed = session.execute(
            update(BlackjackHand)
            .where(
                BlackjackHand.id == hand_id,
                BlackjackHand.status.notin_(engine.TERMINAL_STATUSES),
            )
            .values(
                status=final_status,
                outcome=outcome,
                payout_credits=float(payout),
                rake_credits=float(rake),
                dealer_cards=json.dumps(final_dealer_cards),
                next_card_index=int(next_index),
                settled_at=now_ts,
            )
        )
        if claimed.rowcount == 0:
            # 已被他人结算：不计积分、不动奖池，返回既有结果
            session.expire(hand)
            return {
                "hand": self._blackjack_hand_to_dict(hand),
                "already_settled": True,
            }

        # 抢占成功，本次结算生效。使 ORM 对象读到刚写入的值
        session.expire(hand)

        # 先取该用户 Statistics 的行锁，**再**去碰奖池行——全局加锁顺序统一为
        # 手牌 → statistics → system_config。
        #
        # 为什么必须在这里、且必须无条件取：本方法原先把 Statistics 的锁放在
        # 奖池之后、还包在 `if credited > 0` 里，于是同一对资源出现了两种顺序：
        #   发牌 / 加倍：statistics → system_config
        #   停牌 / 要牌 / 超时 / 兜底：system_config → statistics
        # 这是教科书式的 ABBA。它目前之所以没真的死锁，靠的是两个**没有写下来
        # 的巧合**：发牌路径的「进行中手牌」检查恰好是非加锁 SELECT（并发结算
        # 未提交时它读到旧状态并抛错退出，环因此断开），以及「同一用户至多一手
        # 进行中」使加倍路径总被手牌行锁挡在前面。任何一处改动——比如给那句
        # 计数加上 `.with_for_update()`——都会让死锁立刻成真，而且只在
        # PostgreSQL 上、只在并发下出现。
        #
        # 条件加锁不构成加锁纪律：顺序只有无条件成立才有意义，故不再放进
        # `if credited > 0`。代价只是判负时多锁一行本用户的记录，可忽略。
        stats = (
            session.execute(
                select(Statistics).where(Statistics.tg_id == tg_id).with_for_update()
            )
            .scalars()
            .one_or_none()
        )

        # 幸运奖池：先派彩、后累积。同一手牌不应吃到自己刚交的抽水，故顺序不可颠倒。
        # 派彩独立于本手胜负——拿到三张 7 却因庄家天胡判负仍照发，否则最稀有的
        # 牌型会有概率颗粒无收，而那恰是最需要正反馈的时刻。
        jackpot_won = 0.0
        if jackpot_enabled:
            if engine.is_triple_seven(player_cards):
                # 三张 7：派发全部余额。金额在锁内确定，不先无锁读一次再传进去
                jackpot_won = self._pay_from_jackpot(session, pay_all=True)
            elif engine.is_suited_blackjack(player_cards):
                # 同花天胡：派发余额的固定比例。比例的基数取无锁读到的余额即可——
                # 「当前余额的 10%」本就没有唯一正确的瞬间，且实际派发额仍受锁内
                # 余额的上限约束，不会超发。
                balance = self.read_fund_balance(
                    session, JACKPOT_CONFIG_TYPE, JACKPOT_CONFIG_KEY
                )
                target = round(balance * float(jackpot_suited_pct) / 100.0, 2)
                jackpot_won = self._pay_from_jackpot(session, target)

        # 抽水去向：一部分注入幸运奖池，其余直接销毁。
        # 销毁部分不需要落账——销毁即「不发给任何人」，未进奖池的部分自然消失；
        # 手牌上的 rake_credits 记录抽水总额供审计。
        jackpot_in = 0.0
        if rake > 0 and rake_jackpot_bp > 0:
            jackpot_in = round(rake * float(rake_jackpot_bp) / float(rake_bp), 2)
            if jackpot_in > 0:
                self._add_to_fund(
                    session, JACKPOT_CONFIG_TYPE, JACKPOT_CONFIG_KEY, jackpot_in
                )

        # 计入积分：赔付与奖池派彩一并入账，但在手牌上分列两处记账。
        # Statistics 的行锁已在奖池之前取好，此处只写不再加锁。
        credited = round(payout + jackpot_won, 2)
        if credited > 0:
            if stats:
                stats.credits = round(float(stats.credits) + credited, 2)
            else:
                session.add(
                    Statistics(tg_id=tg_id, donation=0, credits=float(credited))
                )

        if jackpot_won > 0:
            session.execute(
                update(BlackjackHand)
                .where(BlackjackHand.id == hand_id)
                .values(jackpot_won=float(jackpot_won))
            )
            session.expire(hand)

        session.flush()

        return {
            "hand": self._blackjack_hand_to_dict(hand),
            "already_settled": False,
            "outcome": outcome,
            "payout_credits": payout,
            "rake_credits": rake,
            "jackpot_won": jackpot_won,
            "jackpot_in": jackpot_in,
        }

    def _locked_fund_row(self, session, config_type: str, config_key: str):
        """取奖池余额行并加锁。行不存在时返回 None。"""
        return (
            session.execute(
                select(SystemConfig)
                .where(
                    SystemConfig.config_type == config_type,
                    SystemConfig.config_key == config_key,
                )
                .with_for_update()
            )
            .scalars()
            .one_or_none()
        )

    def _add_to_fund(
        self, session, config_type: str, config_key: str, amount: float
    ) -> float:
        """把指定金额注入某个奖池，返回注入后的余额。调用方须在事务内。

        余额以**小数**字符串存储：21 点的单手注入天然为小数（注 5 普通胜的奖池
        份额为 0.06），取整会长期为零。

        首次注入（配置行尚不存在）时并发安全：`SELECT ... FOR UPDATE` 对**不存在
        的行**锁不到任何东西，两个并发事务会各自认为需要 INSERT 并双双写入，撞上
        `uq_config_type_key` 唯一约束（此点在 PostgreSQL 上同样成立，不限于 SQLite）。
        故插入放在 SAVEPOINT 内，撞约束时回退到「重新读取 + 累加」，使先到者的注入
        不被丢弃。
        """
        if amount <= 0:
            return self.read_fund_balance(session, config_type, config_key)

        now_ts = int(time.time())

        def _accumulate(cfg) -> float:
            try:
                current = float(cfg.config_value or "0")
            except Exception:
                current = 0.0
            new_balance = round(current + float(amount), 2)
            cfg.config_value = str(new_balance)
            cfg.updated_at = now_ts
            return new_balance

        cfg = self._locked_fund_row(session, config_type, config_key)
        if cfg:
            return _accumulate(cfg)

        new_balance = round(float(amount), 2)
        try:
            with session.begin_nested():
                session.add(
                    SystemConfig(
                        config_type=config_type,
                        config_key=config_key,
                        config_value=str(new_balance),
                        created_at=now_ts,
                        updated_at=now_ts,
                    )
                )
            return new_balance
        except IntegrityError:
            # 并发的另一方已建好该行：回退到累加，不丢本次注入
            cfg = self._locked_fund_row(session, config_type, config_key)
            if cfg:
                return _accumulate(cfg)
            raise

    def read_fund_balance(self, session, config_type: str, config_key: str) -> float:
        """读奖池余额（不加锁）。行不存在或值非法时返回 0。"""
        raw = session.execute(
            select(SystemConfig.config_value).where(
                SystemConfig.config_type == config_type,
                SystemConfig.config_key == config_key,
            )
        ).scalar_one_or_none()
        try:
            return float(raw or 0)
        except Exception:
            return 0.0

    def _pay_from_jackpot(
        self, session, amount: Optional[float] = None, *, pay_all: bool = False
    ) -> float:
        """从幸运奖池扣减派彩额，返回实际派发的金额。调用方须在事务内。

        余额不足时按余额发放（而非拒发），且绝不会使余额变为负数——奖池只由抽水
        供养，派彩上限就是它自己的余额，这是「不增发积分」的硬保证。

        `pay_all=True` 表示派发全部余额（三张 7）。这个模式是必需的：若由调用方
        先无锁读一次余额、再把该数值当作 amount 传进来，两次读之间提交的抽水会
        让加锁读到的 current 大于 amount，`min` 取 amount 于是**少派**了差额，
        与 spec「三张 7 SHALL 派发全部余额」相悖。金额只在锁内确定一次。
        """
        if not pay_all and (amount is None or amount <= 0):
            return 0.0

        cfg = self._locked_fund_row(session, JACKPOT_CONFIG_TYPE, JACKPOT_CONFIG_KEY)
        if not cfg:
            return 0.0
        try:
            current = float(cfg.config_value or "0")
        except Exception:
            current = 0.0
        if current <= 0:
            return 0.0

        paid = round(current if pay_all else min(float(amount), current), 2)
        if paid <= 0:
            return 0.0
        cfg.config_value = str(round(current - paid, 2))
        cfg.updated_at = int(time.time())
        return paid

    def get_blackjack_jackpot(self) -> float:
        """读幸运奖池当前余额，供牌桌与配置接口展示。"""
        try:
            with get_session() as session:
                return self.read_fund_balance(
                    session, JACKPOT_CONFIG_TYPE, JACKPOT_CONFIG_KEY
                )
        except Exception as e:
            logger.error(f"读取 21 点幸运奖池余额失败: {e}")
            return 0.0

    def seed_blackjack_jackpot(self, amount: float) -> float:
        """由管理员手动注入奖池种子余额，返回注入后的余额。

        这是本设计里**唯一会增发积分**的路径——奖池平时只由抽水供养。故它必须是
        管理员的显式操作，绝不能自动发生。用途是上线冷启动时让奖池有个初值。
        """
        if amount <= 0:
            raise ValueError("jackpot seed must be positive")
        with get_session() as session:
            balance = self._add_to_fund(
                session, JACKPOT_CONFIG_TYPE, JACKPOT_CONFIG_KEY, float(amount)
            )
            logger.info(f"管理员向 21 点幸运奖池注入种子 {amount}，余额 → {balance}")
            return balance

    def claim_unannounced_jackpot_wins(self) -> list[dict]:
        """认领尚未播报的奖池中奖手牌，并把游标推进到本轮的安全边界。

        「认领」意味着调用方**必须**负责播报——本方法一旦返回就已推进游标，
        同一手牌不会再被返回第二次。宁可偶尔漏播一条（发送失败），也不能重复
        刷屏，故不做失败回滚。

        游标的安全边界是关键：不能简单推到当前最大手牌 ID，否则一手刚发出、
        尚未结算的牌会被游标跳过，它之后若中奖就永远播报不到。边界取
        **最小的进行中手牌 ID 减一**，没有进行中手牌时才推到最大 ID。手牌至多
        悬挂 `hand_timeout_minutes` 分钟就会被兜底结算，故边界不会长期卡住。

        依赖调度器的 `max_instances=1` 保证同一时刻只有一个实例在跑；读游标与
        写游标在同一事务内完成。
        """
        from app import blackjack_engine as engine

        try:
            with get_session() as session:
                cursor_row = session.execute(
                    select(SystemConfig).where(
                        SystemConfig.config_type == JACKPOT_CONFIG_TYPE,
                        SystemConfig.config_key == JACKPOT_NOTIFY_CURSOR_KEY,
                    )
                ).scalar_one_or_none()
                try:
                    cursor = int(float(cursor_row.config_value)) if cursor_row else 0
                except (TypeError, ValueError):
                    cursor = 0

                max_id = (
                    session.execute(select(func.max(BlackjackHand.id))).scalar() or 0
                )
                # 进行中的最小手牌 ID 即为本轮不可越过的边界
                oldest_active = session.execute(
                    select(func.min(BlackjackHand.id)).where(
                        BlackjackHand.status.notin_(engine.TERMINAL_STATUSES)
                    )
                ).scalar()
                frontier = int(oldest_active) - 1 if oldest_active else int(max_id)

                now_ts = int(time.time())
                if cursor_row is None:
                    # 首次运行：游标直接落在当前边界并**不播报任何历史中奖**。
                    # 本功能可能在活动已上线一段时间后才部署，若从 0 开始，
                    # 第一轮就会把过往全部中奖一次性倒进群里。
                    session.add(
                        SystemConfig(
                            config_type=JACKPOT_CONFIG_TYPE,
                            config_key=JACKPOT_NOTIFY_CURSOR_KEY,
                            config_value=str(frontier),
                            created_at=now_ts,
                            updated_at=now_ts,
                        )
                    )
                    logger.info(f"21 点奖池播报游标初始化为 {frontier}，不回溯历史中奖")
                    return []

                if frontier <= cursor:
                    return []

                rows = session.execute(
                    select(
                        BlackjackHand.id,
                        BlackjackHand.tg_id,
                        BlackjackHand.player_cards,
                        BlackjackHand.jackpot_won,
                        BlackjackHand.bet_credits,
                        BlackjackHand.outcome,
                    )
                    .where(
                        BlackjackHand.id > cursor,
                        BlackjackHand.id <= frontier,
                        BlackjackHand.jackpot_won > 0,
                    )
                    .order_by(BlackjackHand.id)
                ).all()

                cursor_row.config_value = str(frontier)
                cursor_row.updated_at = now_ts

                wins = []
                for hand_id, tg, cards_json, won, bet, outcome in rows:
                    cards = json.loads(cards_json or "[]")
                    wins.append(
                        {
                            "hand_id": int(hand_id),
                            "tg_id": int(tg),
                            "player_cards": cards,
                            "jackpot_won": float(won or 0),
                            "bet_credits": int(bet or 0),
                            "outcome": outcome,
                            "triple_seven": engine.is_triple_seven(cards),
                        }
                    )
                return wins
        except Exception as e:
            logger.error(f"认领待播报的 21 点奖池中奖失败: {e}")
            return []

    def sweep_timed_out_blackjack_hands(self, tg_id: Optional[int] = None) -> int:
        """结算所有已超时的进行中手牌，返回**实际结算成功**的手数。

        **每手牌自成一个事务**，不与调用方共用、也不彼此共用。两层理由：

        1. 不寄生在发牌或查询的事务里——否则调用方后续任何一次校验失败（速率、
           门槛、余额）都会把已完成的结算连带回滚，用户的赔付被丢弃。
        2. 不把整批放进一个事务——否则第 31 手上的任何异常（牌靴耗尽、约束冲突、
           瞬时连接错误）都会回滚前 30 手已经算好的赔付，而返回值仍会把它们报成
           已结算：积分没进账、手牌仍非终态、押注还扣着，日志却显示一切正常。

        `tg_id` 为空表示全量扫描，供定时兜底任务使用。为什么需要全量兜底：
        APScheduler 的 `misfire_grace_time` 会丢弃错过窗口过久的任务（重启即可
        触发），而按用户的惰性清理只在该用户自己再次操作时发生——若用户再也不
        回来，手牌会永久悬挂、押注不退，违反 spec「超时任务 SHALL 持久化，
        服务重启 SHALL NOT 导致待处置的手牌被遗漏」。

        超时判定下推到 SQL（`created_at_ms + 时限 <= now`）且只取 id：全量扫描
        每 10 分钟跑一次且永不停歇，把整表的非终态行实体化成 ORM 对象再在 Python
        里筛选，会随手牌表增长成为反复的全表水化。
        """
        from app import blackjack_engine as engine

        now_ms = int(time.time() * 1000)
        # 奖池参数在循环外读一次：它对本批所有手牌都一样，而在每手的事务内读会
        # 各自另开一个连接
        jackpot_config = self.get_blackjack_config_dict()

        try:
            with get_session() as session:
                stmt = select(BlackjackHand.id).where(
                    BlackjackHand.status.notin_(engine.TERMINAL_STATUSES),
                    BlackjackHand.created_at_ms
                    + BlackjackHand.hand_timeout_minutes * 60000
                    <= now_ms,
                )
                if tg_id is not None:
                    stmt = stmt.where(BlackjackHand.tg_id == int(tg_id))
                expired_ids = [int(r[0]) for r in session.execute(stmt).all()]
        except Exception as e:
            logger.error(f"扫描超时 21 点手牌失败 (tg_id={tg_id}): {e}")
            return 0

        swept = 0
        for hand_id in expired_ids:
            try:
                with get_session() as session:
                    hand = (
                        session.execute(
                            select(BlackjackHand)
                            .where(BlackjackHand.id == hand_id)
                            .with_for_update()
                        )
                        .scalars()
                        .one_or_none()
                    )
                    if not hand or int(hand.status) in engine.TERMINAL_STATUSES:
                        continue
                    # 先抢占再结算：与用户的并发操作撞车时先到者赢
                    if not self._claim_blackjack_hand(
                        session, hand_id, allow_dealer_turn=True
                    ):
                        continue
                    session.expire(hand)
                    self._settle_blackjack_hand(
                        session,
                        hand,
                        abandoned=True,
                        jackpot_config=jackpot_config,
                    )
                    swept += 1
            except Exception as e:
                # 单手失败只丢这一手，其余照常结算；下一轮兜底会再试
                logger.error(f"清理超时 21 点手牌失败 (hand={hand_id}): {e}")

        if swept:
            logger.info(f"已结算 {swept} 手超时的 21 点手牌 (tg_id={tg_id})")
        return swept

    def _blackjack_day_start_ms(self) -> int:
        """当日零点（`settings.TZ`）的毫秒时间戳，免抽水判定的分界。"""
        day_start = datetime.now(settings.TZ).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return int(day_start.timestamp() * 1000)

    def _count_blackjack_hands_today(self, session, tg_id: int) -> int:
        """该用户当日已发的手数（含进行中）。

        走已有的 `(tg_id, created_at_ms)` 复合索引，不新增存储也不新增查询模式。
        """
        return int(
            session.execute(
                select(func.count(BlackjackHand.id)).where(
                    BlackjackHand.tg_id == int(tg_id),
                    BlackjackHand.created_at_ms >= self._blackjack_day_start_ms(),
                )
            ).scalar_one()
            or 0
        )

    def get_blackjack_free_hands_remaining(self, tg_id: int) -> int:
        """该用户今日剩余的免抽水手数，供下注界面标示。

        仅供展示：真正是否免抽水由发牌事务内的同一口径重新判定并落到快照上，
        故本方法与发牌之间的竞态只会让提示短暂失准，不会造成错误的抽水。
        """
        try:
            with get_session() as session:
                free_hands = int(
                    self.get_blackjack_config_dict().get("free_hands_per_day", 1)
                )
                if free_hands <= 0:
                    return 0
                used = self._count_blackjack_hands_today(session, int(tg_id))
                return max(0, free_hands - used)
        except Exception as e:
            logger.error(f"获取 21 点剩余免抽水手数失败 (tg_id={tg_id}): {e}")
            return 0

    def create_blackjack_hand(self, tg_id: int, bet_credits: int) -> dict:
        """发牌：校验 → 扣注额 → 生成种子定序 → 发初始牌 → 天胡则直接结算。

        并发安全：对该用户的 `Statistics` 行取 FOR UPDATE。发牌本来就要锁这行
        来扣积分，顺带把同一用户的发牌请求串行化，于是「并发双开」「并发绕过速率
        限制」「并发绕过门槛校验」三个问题一把锁解决，无需额外锁对象。

        本方法**只锁 statistics，不锁手牌行**——见下方「进行中手牌」检查处的说明。

        Returns: {hand, settled(bool), outcome?, payout_credits?, ...}
        """
        from app import blackjack_engine as engine

        config = self.get_blackjack_config_dict()

        if not config.get("enabled", False):
            raise ValueError("blackjack disabled")

        bet_options = [int(b) for b in config.get("bet_options") or []]
        if int(bet_credits) not in bet_options:
            raise ValueError(f"invalid bet: must be one of {bet_options}")

        min_credits = int(config.get("min_credits", 30))
        timeout_minutes = int(config.get("hand_timeout_minutes", 15))
        min_interval_seconds = float(config.get("min_deal_interval_seconds", 1))

        # 惰性清理走**独立事务**并先行提交：调度任务负责及时性，本步负责最终
        # 一致性，使用户不会被永久锁在「有进行中手牌无法发新牌」的状态里。
        # 放在本次发牌的事务之外，故发牌若被后续校验拒绝，也不会把已完成的
        # 结算连带回滚、丢弃用户的赔付。
        self.sweep_timed_out_blackjack_hands(tg_id=int(tg_id))

        now_ms = int(time.time() * 1000)

        with get_session() as session:
            # 锁积分行：同时串行化同一用户的发牌
            stats = (
                session.execute(
                    select(Statistics)
                    .where(Statistics.tg_id == int(tg_id))
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not stats:
                raise ValueError("user stats not found")

            # 仍有进行中手牌则拒绝发牌，并引导用户回到该手牌。
            # 此处**只读不锁**：其余路径的加锁顺序均为 hand → statistics，
            # 若在已持有 statistics 锁时再锁手牌就构成 ABBA 死锁（超时任务持有
            # 手牌等 statistics，本方法持有 statistics 等手牌）。同一用户的手牌
            # 由 statistics 锁间接串行化，无需另外加锁。
            active_count = session.execute(
                select(func.count(BlackjackHand.id)).where(
                    BlackjackHand.tg_id == int(tg_id),
                    BlackjackHand.status.notin_(engine.TERMINAL_STATUSES),
                )
            ).scalar_one()
            if int(active_count or 0) > 0:
                raise ValueError("hand in progress")

            # 速率下限：读该用户最近一手的 created_at_ms，同一事务、同一把锁、
            # 零额外依赖，且不会因缓存失效而失效
            if min_interval_seconds > 0:
                last_ms = session.execute(
                    select(func.max(BlackjackHand.created_at_ms)).where(
                        BlackjackHand.tg_id == int(tg_id)
                    )
                ).scalar_one_or_none()
                if last_ms is not None:
                    elapsed = (now_ms - int(last_ms)) / 1000.0
                    if elapsed < min_interval_seconds:
                        raise ValueError("deal too frequent")

            # 门槛与余额。门槛按发牌前的积分判定；注额可等于门槛，
            # 故持有恰好 30 积分的用户可一次押空至 0（已确认接受的设计）。
            credits_before = float(stats.credits)
            if credits_before < float(min_credits):
                raise ValueError(f"insufficient credits: need {min_credits}")
            if credits_before < float(bet_credits):
                raise ValueError("insufficient credits")

            stats.credits = round(credits_before - float(bet_credits), 2)

            # 每日首手免抽水：低成本的习惯钩子，无条件发放，不需下注解锁。
            # 判定用当日零点（settings.TZ）之后的手数，走已有的
            # (tg_id, created_at_ms) 索引，不新增存储也不新增查询模式。
            free_hands = int(config.get("free_hands_per_day", 1))
            rake_waived = False
            if free_hands > 0:
                hands_today = self._count_blackjack_hands_today(session, int(tg_id))
                rake_waived = hands_today < free_hands

            # 免抽水直接落在快照上（rake_bp_on_profit=0），结算读的本来就是快照，
            # 于是 rake 自然为 0——**结算路径不需要加任何分支**
            snapshot_rake_bp = (
                0 if rake_waived else int(config.get("rake_bp_on_profit", 300))
            )

            # 牌靴定序：种子来自 secrets（对用户不可预测），牌序由种子唯一决定
            # （可复现）。种子随手牌落库，故服务端无法在要牌时换牌。
            deck_seed = secrets.token_hex(16)
            deck = engine.build_deck(deck_seed)
            player_cards, dealer_cards, next_index = engine.deal_initial(deck)

            hand = BlackjackHand(
                tg_id=int(tg_id),
                status=engine.STATUS_PLAYER_TURN,
                bet_credits=int(bet_credits),
                doubled=0,
                deck_seed=deck_seed,
                next_card_index=int(next_index),
                player_cards=json.dumps(player_cards),
                dealer_cards=json.dumps(dealer_cards),
                # 参数快照：结算读这些列而非读当前配置
                rake_bp_on_profit=snapshot_rake_bp,
                rake_jackpot_bp=int(config.get("rake_jackpot_bp", 120)),
                blackjack_payout=float(config.get("blackjack_payout", 1.5)),
                dealer_hits_soft_17=1
                if config.get("dealer_hits_soft_17", False)
                else 0,
                hand_timeout_minutes=timeout_minutes,
                rake_waived=1 if rake_waived else 0,
                created_at_ms=now_ms,
            )
            session.add(hand)
            session.flush()

            # 开局天胡直接结算，不经玩家回合
            initial = engine.evaluate_initial_deal(
                player_cards,
                dealer_cards,
                blackjack_payout=float(hand.blackjack_payout),
            )
            if initial is not None:
                result = self._settle_blackjack_hand(
                    session, hand, jackpot_config=config
                )
                result["settled"] = True
                return result

            return {
                "hand": self._blackjack_hand_to_dict(hand),
                "settled": False,
            }

    def _record_blackjack_decision(
        self,
        session,
        hand_id: int,
        *,
        player_cards: list,
        dealer_upcard: str,
        can_double: bool,
        hits_soft_17: bool,
        action: str,
    ) -> dict:
        """按基本策略评判玩家本次动作，累加手牌上的决策计数，返回评判结果。

        局面参数由调用方在**抢占之前**捕获后传入：抢占会把状态推进到庄家回合，
        届时 `can_double` 等判定的依据已经变了。评判要还原的是玩家做决定时看到的
        局面，不是执行之后的局面。

        `hits_soft_17` 取自该手牌的参数快照而非当前配置：否则管理员改了庄家规则，
        历史手牌的准确率会跟着漂移。
        """
        from app import blackjack_engine as engine

        recommended = engine.recommend_action(
            player_cards,
            dealer_upcard,
            can_double=can_double,
            hits_soft_17=hits_soft_17,
        )
        correct = recommended == action

        session.execute(
            update(BlackjackHand)
            .where(BlackjackHand.id == int(hand_id))
            .values(
                decisions_total=BlackjackHand.decisions_total + 1,
                decisions_correct=BlackjackHand.decisions_correct
                + (1 if correct else 0),
            )
        )
        return {"action": action, "recommended": recommended, "correct": correct}

    def _capture_decision_context(self, hand: BlackjackHand) -> dict:
        """在抢占前捕获评判所需的局面。"""
        from app import blackjack_engine as engine

        player_cards = json.loads(hand.player_cards or "[]")
        dealer_cards = json.loads(hand.dealer_cards or "[]")
        return {
            "player_cards": player_cards,
            "dealer_upcard": dealer_cards[0] if dealer_cards else None,
            "can_double": engine.can_double(player_cards, int(hand.status)),
            "hits_soft_17": int(hand.dealer_hits_soft_17) == 1,
        }

    def blackjack_hit(self, tg_id: int, hand_id: int) -> dict:
        """要牌：按游标取下一张牌；爆牌则直接结算，未爆则交还玩家回合。

        取牌只是「翻开」发牌时既已确定的牌序，不重新生成牌面。
        """
        from app import blackjack_engine as engine

        # 奖池参数在**开启事务之前**读好：本方法的事务内若再调
        # get_blackjack_config_dict() 会另开一个 session，同时占用两个连接，
        # 且首次读取还会在新连接上写库——外层正持有行锁时足以死锁。
        jackpot_config = self.get_blackjack_config_dict()

        with get_session() as session:
            hand = self._lock_blackjack_hand(session, tg_id, hand_id)

            if int(hand.status) in engine.TERMINAL_STATUSES:
                raise ValueError("hand already finished")
            if int(hand.status) != engine.STATUS_PLAYER_TURN:
                raise ValueError("not player turn")

            # 评判所需的局面必须在抢占前捕获——抢占会推进状态，届时加倍是否可用
            # 等判定依据就变了
            ctx = self._capture_decision_context(hand)

            # 先原子抢占，再动任何数据：抢不到就说明手牌已被他人推进，
            # 此时若已写入新牌，事务提交会留下与 outcome 不符的牌面
            if not self._claim_blackjack_hand(session, hand_id):
                raise ValueError("hand already finished")
            session.expire(hand)

            decision = self._record_blackjack_decision(
                session, hand_id, action=engine.ACTION_HIT, **ctx
            )

            player_cards = json.loads(hand.player_cards or "[]")
            deck = engine.build_deck(str(hand.deck_seed))
            card, next_index = engine.draw_card(deck, int(hand.next_card_index))
            player_cards.append(card)

            hand.player_cards = json.dumps(player_cards)
            hand.next_card_index = int(next_index)
            session.flush()

            if engine.is_bust(player_cards):
                result = self._settle_blackjack_hand(
                    session, hand, jackpot_config=jackpot_config
                )
                result["settled"] = bool(not result.get("already_settled"))
                result["decision"] = decision
                return result

            # 未爆：交还玩家回合，玩家可继续要牌或停牌
            self._release_blackjack_hand(session, hand_id)
            session.expire(hand)
            return {
                "hand": self._blackjack_hand_to_dict(hand),
                "settled": False,
                "decision": decision,
            }

    def blackjack_stand(self, tg_id: int, hand_id: int) -> dict:
        """停牌：转入庄家回合并结算。"""
        from app import blackjack_engine as engine

        # 奖池参数在**开启事务之前**读好：本方法的事务内若再调
        # get_blackjack_config_dict() 会另开一个 session，同时占用两个连接，
        # 且首次读取还会在新连接上写库——外层正持有行锁时足以死锁。
        jackpot_config = self.get_blackjack_config_dict()

        with get_session() as session:
            hand = self._lock_blackjack_hand(session, tg_id, hand_id)

            if int(hand.status) in engine.TERMINAL_STATUSES:
                raise ValueError("hand already finished")
            if int(hand.status) != engine.STATUS_PLAYER_TURN:
                raise ValueError("not player turn")

            ctx = self._capture_decision_context(hand)

            if not self._claim_blackjack_hand(session, hand_id):
                raise ValueError("hand already finished")
            session.expire(hand)

            decision = self._record_blackjack_decision(
                session, hand_id, action=engine.ACTION_STAND, **ctx
            )

            result = self._settle_blackjack_hand(
                session, hand, jackpot_config=jackpot_config
            )
            result["settled"] = bool(not result.get("already_settled"))
            result["decision"] = decision
            return result

    def blackjack_double(self, tg_id: int, hand_id: int) -> dict:
        """加倍：追加扣一份基础注额 → 只发一张牌 → 自动停牌结算。

        加倍要求用户另有不少于一份基础注额的可用积分。余额不足**必须**拒绝，
        否则存在把积分打成负数的路径。
        """
        from app import blackjack_engine as engine

        # 奖池参数在**开启事务之前**读好：本方法的事务内若再调
        # get_blackjack_config_dict() 会另开一个 session，同时占用两个连接，
        # 且首次读取还会在新连接上写库——外层正持有行锁时足以死锁。
        jackpot_config = self.get_blackjack_config_dict()

        with get_session() as session:
            hand = self._lock_blackjack_hand(session, tg_id, hand_id)

            if int(hand.status) in engine.TERMINAL_STATUSES:
                raise ValueError("hand already finished")
            if int(hand.status) != engine.STATUS_PLAYER_TURN:
                raise ValueError("not player turn")
            if int(hand.doubled) == 1:
                raise ValueError("already doubled")

            player_cards = json.loads(hand.player_cards or "[]")
            # 加倍仅限手中恰为初始两张牌时；已要牌后不可加倍
            if not engine.can_double(player_cards, int(hand.status)):
                raise ValueError("cannot double after hit")

            bet = int(hand.bet_credits)
            ctx = self._capture_decision_context(hand)

            # **抢占必须早于扣分**：否则抢占失败时追加的注额已被扣掉，
            # 而结算又不会赔付，用户白损失一份注额
            if not self._claim_blackjack_hand(session, hand_id):
                raise ValueError("hand already finished")
            session.expire(hand)

            stats = (
                session.execute(
                    select(Statistics)
                    .where(Statistics.tg_id == int(tg_id))
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not stats:
                raise ValueError("user stats not found")
            if float(stats.credits) < float(bet):
                # 事务回滚会把 status 恢复为玩家回合，手牌不受影响
                raise ValueError(f"insufficient credits to double: need {bet}")

            # 余额校验通过后才记决策：校验失败会整体回滚，此时不该留下决策计数
            decision = self._record_blackjack_decision(
                session, hand_id, action=engine.ACTION_DOUBLE, **ctx
            )

            stats.credits = round(float(stats.credits) - float(bet), 2)

            player_cards = json.loads(hand.player_cards or "[]")
            deck = engine.build_deck(str(hand.deck_seed))
            card, next_index = engine.draw_card(deck, int(hand.next_card_index))
            player_cards.append(card)

            hand.doubled = 1
            hand.player_cards = json.dumps(player_cards)
            hand.next_card_index = int(next_index)
            session.flush()

            # 加倍后只发一张并自动停牌；若该张牌导致爆牌，结算路径判负
            result = self._settle_blackjack_hand(
                session, hand, jackpot_config=jackpot_config
            )
            result["settled"] = bool(not result.get("already_settled"))
            result["decision"] = decision
            return result

    def _lock_blackjack_hand(self, session, tg_id: int, hand_id: int) -> BlackjackHand:
        """取手牌行并加锁，校验归属。锁顺序的第一步。"""
        hand = (
            session.execute(
                select(BlackjackHand)
                .where(BlackjackHand.id == int(hand_id))
                .with_for_update()
            )
            .scalars()
            .one_or_none()
        )
        if not hand:
            raise ValueError("hand not found")
        if int(hand.tg_id) != int(tg_id):
            raise ValueError("hand not found")
        return hand

    def _claim_blackjack_hand(
        self, session, hand_id: int, *, allow_dealer_turn: bool = False
    ) -> bool:
        """把手牌从「玩家回合」原子地推进到「庄家回合」，宣告本事务独占它。

        这是所有改动手牌的动作（要牌/停牌/加倍/超时结算）的**第一步**，必须在
        任何写操作之前完成。返回 False 说明抢占失败——手牌已被他人推进或结算，
        调用方必须立即放弃，不得做任何写入。

        为什么必须先抢占再写：`with_for_update()` 在 SQLite 上是 no-op，若沿用
        「读 status 判断 → 写 → 结算时再 CAS」的顺序，加倍会先扣掉一份注额、
        要牌会先写入一张新牌，而随后的结算 CAS 可能失败——此时事务仍会提交那些
        写入，造成**扣了钱不赔付**与**牌面和 outcome 不一致**。把闸门提到最前面，
        写操作就只发生在独占成立之后。

        `status=2`（庄家回合）在此同时充当独占标记与 spec 所述的中间状态：
        玩家回合 → 庄家回合 → 已结算。它只在事务内可见，事务回滚即恢复为 1。

        `allow_dealer_turn=True` 供超时兜底与定时清理使用，把可抢占的状态放宽到
        全部非终态。理由：判定「手牌是否还活着」的地方（兜底扫描、进行中手牌
        计数）用的都是 `status NOT IN (终态)`，而抢占只认 status=1；两个谓词一旦
        不一致，任何以 status=2 落库的行都会**既被视为进行中、又永远抢不到**，
        用户将带着已扣的押注被永久锁在活动之外且无自愈路径。正常流程下 status=2
        不会跨事务存活，故这是纯粹的恢复能力，不改变常规路径的语义。
        """
        from app import blackjack_engine as engine

        claimable = (
            [engine.STATUS_PLAYER_TURN, engine.STATUS_DEALER_TURN]
            if allow_dealer_turn
            else [engine.STATUS_PLAYER_TURN]
        )
        session.flush()
        claimed = session.execute(
            update(BlackjackHand)
            .where(
                BlackjackHand.id == int(hand_id),
                BlackjackHand.status.in_(claimable),
            )
            .values(status=engine.STATUS_DEALER_TURN)
        )
        return claimed.rowcount == 1

    def _release_blackjack_hand(self, session, hand_id: int) -> None:
        """把手牌交还「玩家回合」——要牌未爆时用，使玩家可继续操作。"""
        from app import blackjack_engine as engine

        session.execute(
            update(BlackjackHand)
            .where(
                BlackjackHand.id == int(hand_id),
                BlackjackHand.status == engine.STATUS_DEALER_TURN,
            )
            .values(status=engine.STATUS_PLAYER_TURN)
        )

    def settle_blackjack_hand_by_timeout(self, hand_id: int) -> dict:
        """超时兜底：由调度任务调用，等同于玩家停牌。

        与用户操作撞车时由抢占闸门保证只结算一次：抢不到即返回既有结果。
        """
        # 奖池参数在**开启事务之前**读好：本方法的事务内若再调
        # get_blackjack_config_dict() 会另开一个 session，同时占用两个连接，
        # 且首次读取还会在新连接上写库——外层正持有行锁时足以死锁。
        jackpot_config = self.get_blackjack_config_dict()

        with get_session() as session:
            hand = (
                session.execute(
                    select(BlackjackHand)
                    .where(BlackjackHand.id == int(hand_id))
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not hand:
                raise ValueError("hand not found")

            if not self._claim_blackjack_hand(session, int(hand_id)):
                # 用户已抢先操作或已结算，本次不再介入
                session.expire(hand)
                return {
                    "hand": self._blackjack_hand_to_dict(hand),
                    "already_settled": True,
                }
            session.expire(hand)
            return self._settle_blackjack_hand(
                session, hand, abandoned=True, jackpot_config=jackpot_config
            )

    def get_current_blackjack_hand(self, tg_id: int) -> Optional[dict]:
        """取该用户处于非终态的手牌，供恢复牌桌用。没有则返回 None。

        **本方法不是纯读操作**：它先调 `sweep_timed_out_blackjack_hands`（独立
        事务）清掉该用户已超时的手牌，那一步会改积分、动奖池。之所以仍留在这条
        读路径上：用户重新打开牌桌时必须看到正确的状态，若只依赖 10 分钟一次的
        定时兜底，最长会有 10 分钟看到一手早该结算的牌，且此期间无法开新局。

        代价是 GET 具有副作用，重试与预取都会触发结算。这一点靠幂等性兜住——
        结算由条件 UPDATE 把关，重复触发不会重复赔付，最坏情况只是多跑一次空扫描。
        """
        from app import blackjack_engine as engine

        # 先清掉该用户已超时的手牌，避免返回一手早该结算的牌
        self.sweep_timed_out_blackjack_hands(tg_id=int(tg_id))

        with get_session() as session:
            hand = (
                session.execute(
                    select(BlackjackHand)
                    .where(
                        BlackjackHand.tg_id == int(tg_id),
                        BlackjackHand.status.notin_(engine.TERMINAL_STATUSES),
                    )
                    .order_by(BlackjackHand.created_at_ms.desc())
                )
                .scalars()
                .first()
            )
            if not hand:
                return None
            return self._blackjack_hand_to_dict(hand)

    def list_active_blackjack_hands(self) -> list[dict]:
        """列出所有非终态的手牌，供启动时重建超时任务用。"""
        from app import blackjack_engine as engine

        try:
            with get_session() as session:
                rows = session.execute(
                    select(
                        BlackjackHand.id,
                        BlackjackHand.tg_id,
                        BlackjackHand.created_at_ms,
                        BlackjackHand.hand_timeout_minutes,
                    ).where(BlackjackHand.status.notin_(engine.TERMINAL_STATUSES))
                ).all()
                return [
                    {
                        "id": int(r[0]),
                        "tg_id": int(r[1]),
                        "created_at_ms": int(r[2]),
                        "hand_timeout_minutes": int(r[3]),
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"列出进行中的 21 点手牌失败: {e}")
            return []

    def get_user_blackjack_stats(self, tg_id: int) -> dict:
        """用户的 21 点个人统计。

        净积分变动 = Σ(payout − 总押注)；总押注为加倍手两份基础注额、否则一份。
        奖池派彩单独统计，不混入净积分与单手最大赢利——它衡量的是运气不是打法。
        """
        from app import blackjack_engine as engine

        empty = {
            "total_hands": 0,
            "net_credits": 0.0,
            "max_win": 0.0,
            "win_rate": 0.0,
            "accuracy": 0.0,
            "decisions_total": 0,
            "jackpot_total": 0.0,
        }
        try:
            with get_session() as session:
                total_stake = case(
                    (BlackjackHand.doubled == 1, BlackjackHand.bet_credits * 2),
                    else_=BlackjackHand.bet_credits,
                )
                net = func.coalesce(BlackjackHand.payout_credits, 0) - total_stake
                win_flag = case(
                    (
                        BlackjackHand.outcome.in_(
                            [engine.OUTCOME_WIN, engine.OUTCOME_BLACKJACK]
                        ),
                        1,
                    ),
                    else_=0,
                )
                row = session.execute(
                    select(
                        func.count(BlackjackHand.id),
                        func.coalesce(func.sum(net), 0),
                        func.coalesce(func.max(net), 0),
                        func.coalesce(func.sum(win_flag), 0),
                        func.coalesce(func.sum(BlackjackHand.decisions_total), 0),
                        func.coalesce(func.sum(BlackjackHand.decisions_correct), 0),
                        func.coalesce(func.sum(BlackjackHand.jackpot_won), 0),
                    ).where(
                        BlackjackHand.tg_id == int(tg_id),
                        BlackjackHand.status.in_(engine.TERMINAL_STATUSES),
                    )
                ).one()

                hands = int(row[0] or 0)
                dec_total = int(row[4] or 0)
                return {
                    "total_hands": hands,
                    "net_credits": round(float(row[1] or 0), 2),
                    "max_win": round(float(row[2] or 0), 2),
                    "win_rate": round(float(row[3] or 0) / hands * 100, 2)
                    if hands
                    else 0.0,
                    "accuracy": round(float(row[5] or 0) / dec_total * 100, 2)
                    if dec_total
                    else 0.0,
                    "decisions_total": dec_total,
                    "jackpot_total": round(float(row[6] or 0), 2),
                }
        except Exception as e:
            logger.error(f"获取用户 21 点统计失败 (tg_id={tg_id}): {e}")
            return empty

    def get_blackjack_admin_stats(self) -> dict:
        """21 点的运营聚合统计，供管理页卡片展示。

        **金额口径只统计终态手牌**（已结算 / 超时弃牌）。进行中的手牌押注已扣、
        赔付未定，计进去会把尚未落定的押注记成净流出，数字在手牌结算的那一刻
        又跳回来——展示值不该随一手牌的中间状态抖动。进行中手数单列，正好也是
        运营需要盯的悬挂量。

        `net_credits` 取**玩家视角**：为负说明活动在净回收积分，与设计意图一致。
        奖池派彩计入其中，因为那同样是发到玩家手上的积分；但它来自抽水积攒的池
        子而非凭空增发，故不破坏「只回收不增发」。

        一次扫描出全部聚合项。参与人数按全部手牌去重，不限终态——发过牌就算参与。
        """
        from app import blackjack_engine as engine

        empty = {
            "total_hands": 0,
            "active_hands": 0,
            "total_players": 0,
            "today_hands": 0,
            "total_wagered": 0.0,
            "total_rake": 0.0,
            "net_credits": 0.0,
            "jackpot_paid": 0.0,
            "jackpot_balance": 0.0,
        }
        try:
            with get_session() as session:
                terminal = BlackjackHand.status.in_(engine.TERMINAL_STATUSES)
                stake = case(
                    (BlackjackHand.doubled == 1, BlackjackHand.bet_credits * 2),
                    else_=BlackjackHand.bet_credits,
                )
                # 终态才计金额；用 case 折成 0 而非加 WHERE，这样手数、人数、
                # 今日手数能与金额项共用同一次扫描
                staked = case((terminal, stake), else_=0)
                paid = case(
                    (terminal, func.coalesce(BlackjackHand.payout_credits, 0)), else_=0
                )
                raked = case(
                    (terminal, func.coalesce(BlackjackHand.rake_credits, 0)), else_=0
                )
                jackpot = case(
                    (terminal, func.coalesce(BlackjackHand.jackpot_won, 0)), else_=0
                )

                row = session.execute(
                    select(
                        func.coalesce(func.sum(case((terminal, 1), else_=0)), 0),
                        func.coalesce(func.sum(case((terminal, 0), else_=1)), 0),
                        func.count(distinct(BlackjackHand.tg_id)),
                        func.coalesce(
                            func.sum(
                                case(
                                    (
                                        BlackjackHand.created_at_ms
                                        >= self._blackjack_day_start_ms(),
                                        1,
                                    ),
                                    else_=0,
                                )
                            ),
                            0,
                        ),
                        func.coalesce(func.sum(staked), 0),
                        func.coalesce(func.sum(raked), 0),
                        func.coalesce(func.sum(paid), 0),
                        func.coalesce(func.sum(jackpot), 0),
                    )
                ).one()

                wagered = float(row[4] or 0)
                payout = float(row[6] or 0)
                jackpot_paid = float(row[7] or 0)
                return {
                    "total_hands": int(row[0] or 0),
                    "active_hands": int(row[1] or 0),
                    "total_players": int(row[2] or 0),
                    "today_hands": int(row[3] or 0),
                    "total_wagered": round(wagered, 2),
                    "total_rake": round(float(row[5] or 0), 2),
                    "net_credits": round(payout + jackpot_paid - wagered, 2),
                    "jackpot_paid": round(jackpot_paid, 2),
                    # 复用同一 session 读余额。这里若改调 get_blackjack_jackpot()
                    # 会在已开事务内再取一条连接，池子只有 DB_POOL_SIZE 条
                    "jackpot_balance": self.read_fund_balance(
                        session, JACKPOT_CONFIG_TYPE, JACKPOT_CONFIG_KEY
                    ),
                }
        except Exception as e:
            logger.error(f"获取 21 点运营统计失败: {e}")
            return empty

    # ==================== Invitation Query Operations ====================

    def verify_invitation_code_is_used(self, code: str) -> Optional[Tuple]:
        """验证邀请码是否已使用"""
        with get_session() as session:
            stmt = select(Invitation.is_used, Invitation.owner).where(
                Invitation.code == code
            )
            result = session.execute(stmt).fetchone()
            return (result[0], result[1]) if result else None

    def get_invitation_code_by_owner(
        self, tg_id: int, is_available: bool = True
    ) -> list:
        """获取用户的邀请码"""
        with get_session() as session:
            if is_available:
                stmt = select(Invitation.code).where(
                    Invitation.owner == tg_id, Invitation.is_used == 0
                )
            else:
                stmt = select(Invitation.code).where(Invitation.owner == tg_id)
            results = session.execute(stmt).fetchall()
            return [r[0] for r in results]

    def get_invitee_count_by_owner(self, tg_id: int) -> int:
        """获取用户邀请的人数"""
        try:
            with get_session() as session:
                stmt = select(func.count(func.distinct(Invitation.used_by))).where(
                    Invitation.owner == tg_id,
                    Invitation.is_used == 1,
                    Invitation.used_by.isnot(None),
                )
                count = session.execute(stmt).scalar()
                return count if count else 0
        except Exception as e:
            logger.error(f"获取邀请人数失败: {e}")
            return 0

    # ==================== Line Management Operations ====================

    def set_emby_line(
        self, line: str, tg_id: Optional[int] = None, emby_id: Optional[str] = None
    ) -> bool:
        """设置 Emby 线路"""
        try:
            with get_session() as session:
                if tg_id is not None:
                    session.execute(
                        update(EmbyUser)
                        .where(EmbyUser.tg_id == tg_id)
                        .values(emby_line=line)
                    )
                elif emby_id is not None:
                    session.execute(
                        update(EmbyUser)
                        .where(EmbyUser.emby_id == emby_id)
                        .values(emby_line=line)
                    )
                return True
        except Exception as e:
            logger.error(f"Error setting emby line: {e}")
            return False

    def get_emby_line(self, tg_id: int) -> Optional[str]:
        """获取 Emby 线路"""
        with get_session() as session:
            stmt = select(EmbyUser.emby_line).where(EmbyUser.tg_id == tg_id)
            result = session.execute(stmt).scalar_one_or_none()
            return result

    def get_emby_user_with_binded_line(self) -> list:
        """获取绑定线路的 Emby 用户"""
        with get_session() as session:
            stmt = select(
                EmbyUser.emby_username,
                EmbyUser.tg_id,
                EmbyUser.emby_id,
                EmbyUser.emby_line,
                EmbyUser.is_premium,
            ).where(EmbyUser.emby_line.isnot(None))
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1], r[2], r[3], r[4]) for r in results]

    def set_plex_line(
        self, line: str, tg_id: Optional[int] = None, plex_id: Optional[int] = None
    ) -> bool:
        """设置 Plex 线路"""
        try:
            with get_session() as session:
                if tg_id is not None:
                    session.execute(
                        update(PlexUser)
                        .where(PlexUser.tg_id == tg_id)
                        .values(plex_line=line)
                    )
                elif plex_id is not None:
                    session.execute(
                        update(PlexUser)
                        .where(PlexUser.plex_id == plex_id)
                        .values(plex_line=line)
                    )
                return True
        except Exception as e:
            logger.error(f"Error setting plex line: {e}")
            return False

    def get_plex_line(self, tg_id: int) -> Optional[str]:
        """获取 Plex 线路"""
        with get_session() as session:
            stmt = select(PlexUser.plex_line).where(PlexUser.tg_id == tg_id)
            result = session.execute(stmt).scalar_one_or_none()
            return result

    def get_plex_user_with_binded_line(self) -> list:
        """获取绑定线路的 Plex 用户"""
        with get_session() as session:
            stmt = select(
                PlexUser.plex_username,
                PlexUser.tg_id,
                PlexUser.plex_id,
                PlexUser.plex_line,
                PlexUser.is_premium,
            ).where(PlexUser.plex_line.isnot(None))
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1], r[2], r[3], r[4]) for r in results]

    # ==================== Wheel Operations ====================

    def add_wheel_spin_record(
        self, tg_id: int, item_name: str, credits_change: float, cost_credits: float
    ) -> bool:
        """记录转盘旋转记录"""
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

    # ==================== Premium Operations ====================

    def get_expired_premium_users(self) -> list:
        """获取所有 Premium 已过期的用户"""
        expired_users = []
        current_time = datetime.now(settings.TZ).isoformat()

        with get_session() as session:
            # 检查 Plex 用户
            plex_stmt = select(
                PlexUser.tg_id,
                PlexUser.plex_username,
                PlexUser.premium_expiry_time,
                PlexUser.plex_line,
            ).where(
                PlexUser.is_premium == 1,
                PlexUser.premium_expiry_time.isnot(None),
                PlexUser.premium_expiry_time < current_time,
            )
            plex_users = session.execute(plex_stmt).fetchall()

            for user in plex_users:
                expired_users.append(
                    {
                        "tg_id": user[0],
                        "username": user[1],
                        "service": "plex",
                        "expiry_time": user[2],
                        "line": user[3],
                    }
                )

            # 检查 Emby 用户
            emby_stmt = select(
                EmbyUser.tg_id,
                EmbyUser.emby_username,
                EmbyUser.premium_expiry_time,
                EmbyUser.emby_line,
            ).where(
                EmbyUser.is_premium == 1,
                EmbyUser.premium_expiry_time.isnot(None),
                EmbyUser.premium_expiry_time < current_time,
            )
            emby_users = session.execute(emby_stmt).fetchall()

            for user in emby_users:
                expired_users.append(
                    {
                        "tg_id": user[0],
                        "username": user[1],
                        "service": "emby",
                        "expiry_time": user[2],
                        "line": user[3],
                    }
                )

        return expired_users

    def update_expired_premium_status(self) -> int:
        """批量更新已过期的 Premium 用户状态"""
        current_time = datetime.now(settings.TZ).isoformat()
        current_timestamp = int(datetime.now(settings.TZ).timestamp())

        with get_session() as session:
            # 更新 Plex 用户
            plex_result = session.execute(
                update(PlexUser)
                .where(
                    PlexUser.is_premium == 1,
                    PlexUser.premium_expiry_time.isnot(None),
                    PlexUser.premium_expiry_time < current_time,
                )
                .values(
                    is_premium=0,
                    premium_expiry_time=None,
                    premium_status_updated_at=current_timestamp,
                )
            )

            # 更新 Emby 用户
            emby_result = session.execute(
                update(EmbyUser)
                .where(
                    EmbyUser.is_premium == 1,
                    EmbyUser.premium_expiry_time.isnot(None),
                    EmbyUser.premium_expiry_time < current_time,
                )
                .values(
                    is_premium=0,
                    premium_expiry_time=None,
                    premium_status_updated_at=current_timestamp,
                )
            )
            total_updated = plex_result.rowcount + emby_result.rowcount
            return total_updated

    def get_premium_users_expiring_soon(self, days: int = 3) -> list:
        """获取即将过期的 Premium 用户（默认3天内）"""
        current_time = datetime.now(settings.TZ)
        warning_time = (current_time + timedelta(days=days)).isoformat()
        current_time_str = current_time.isoformat()

        expiring_users = []

        with get_session() as session:
            # 检查 Plex 用户
            plex_stmt = select(
                PlexUser.tg_id, PlexUser.plex_username, PlexUser.premium_expiry_time
            ).where(
                PlexUser.is_premium == 1,
                PlexUser.premium_expiry_time.isnot(None),
                PlexUser.premium_expiry_time > current_time_str,
                PlexUser.premium_expiry_time <= warning_time,
            )
            plex_users = session.execute(plex_stmt).fetchall()

            for user in plex_users:
                expiry_dt = datetime.fromisoformat(user[2]).astimezone(settings.TZ)
                days_remaining = (expiry_dt - current_time).days
                expiring_users.append(
                    {
                        "tg_id": user[0],
                        "username": user[1],
                        "service": "plex",
                        "expiry_time": user[2],
                        "days_remaining": days_remaining,
                    }
                )

            # 检查 Emby 用户
            emby_stmt = select(
                EmbyUser.tg_id, EmbyUser.emby_username, EmbyUser.premium_expiry_time
            ).where(
                EmbyUser.is_premium == 1,
                EmbyUser.premium_expiry_time.isnot(None),
                EmbyUser.premium_expiry_time > current_time_str,
                EmbyUser.premium_expiry_time <= warning_time,
            )
            emby_users = session.execute(emby_stmt).fetchall()

            for user in emby_users:
                expiry_dt = datetime.fromisoformat(user[2]).astimezone(settings.TZ)
                days_remaining = (expiry_dt - current_time).days
                expiring_users.append(
                    {
                        "tg_id": user[0],
                        "username": user[1],
                        "service": "emby",
                        "expiry_time": user[2],
                        "days_remaining": days_remaining,
                    }
                )

        return expiring_users

    def get_premium_statistics(self) -> dict:
        """获取 Premium 用户统计信息"""
        try:
            current_time = datetime.now(settings.TZ).isoformat()

            with get_session() as session:
                # 总 Premium 用户数（去重）
                total_premium_users = session.execute(
                    select(func.count()).select_from(
                        select(PlexUser.tg_id)
                        .where(PlexUser.is_premium == 1, PlexUser.tg_id.isnot(None))
                        .union(
                            select(EmbyUser.tg_id).where(
                                EmbyUser.is_premium == 1, EmbyUser.tg_id.isnot(None)
                            )
                        )
                        .subquery()
                    )
                ).scalar()

                # 活跃 Premium 用户数（未过期的，去重）
                active_premium_users = session.execute(
                    select(func.count()).select_from(
                        select(PlexUser.tg_id)
                        .where(
                            PlexUser.is_premium == 1,
                            PlexUser.tg_id.isnot(None),
                            (PlexUser.premium_expiry_time.is_(None))
                            | (PlexUser.premium_expiry_time > current_time),
                        )
                        .union(
                            select(EmbyUser.tg_id).where(
                                EmbyUser.is_premium == 1,
                                EmbyUser.tg_id.isnot(None),
                                (EmbyUser.premium_expiry_time.is_(None))
                                | (EmbyUser.premium_expiry_time > current_time),
                            )
                        )
                        .subquery()
                    )
                ).scalar()

                # Premium Plex 用户数（未过期的）
                premium_plex_users = session.execute(
                    select(func.count(PlexUser.id)).where(
                        PlexUser.is_premium == 1,
                        (PlexUser.premium_expiry_time.is_(None))
                        | (PlexUser.premium_expiry_time > current_time),
                    )
                ).scalar()

                # Premium Emby 用户数（未过期的）
                premium_emby_users = session.execute(
                    select(func.count(EmbyUser.emby_username)).where(
                        EmbyUser.is_premium == 1,
                        (EmbyUser.premium_expiry_time.is_(None))
                        | (EmbyUser.premium_expiry_time > current_time),
                    )
                ).scalar()

                return {
                    "total_premium_users": total_premium_users,
                    "active_premium_users": active_premium_users,
                    "premium_plex_users": premium_plex_users,
                    "premium_emby_users": premium_emby_users,
                }

        except Exception as e:
            logger.error(f"Error getting premium statistics: {e}")
            return {
                "total_premium_users": 0,
                "active_premium_users": 0,
                "premium_plex_users": 0,
                "premium_emby_users": 0,
            }

    def get_all_active_premium_users(self) -> list:
        """获取所有活跃的 Premium 用户及其到期时间"""
        premium_users = []
        current_time = datetime.now(settings.TZ).isoformat()

        try:
            with get_session() as session:
                # 获取 Plex Premium 用户
                plex_stmt = select(
                    PlexUser.tg_id,
                    PlexUser.plex_username,
                    PlexUser.premium_expiry_time,
                    PlexUser.plex_line,
                ).where(
                    PlexUser.is_premium == 1,
                    (PlexUser.premium_expiry_time.is_(None))
                    | (PlexUser.premium_expiry_time > current_time),
                )
                plex_users = session.execute(plex_stmt).fetchall()

                for user in plex_users:
                    premium_users.append(
                        {
                            "tg_id": user[0],
                            "username": user[1],
                            "service": "Plex",
                            "expiry_time": user[2],
                            "line": user[3],
                        }
                    )

                # 获取 Emby Premium 用户
                emby_stmt = select(
                    EmbyUser.tg_id,
                    EmbyUser.emby_username,
                    EmbyUser.premium_expiry_time,
                    EmbyUser.emby_line,
                ).where(
                    EmbyUser.is_premium == 1,
                    (EmbyUser.premium_expiry_time.is_(None))
                    | (EmbyUser.premium_expiry_time > current_time),
                )
                emby_users = session.execute(emby_stmt).fetchall()

                for user in emby_users:
                    premium_users.append(
                        {
                            "tg_id": user[0],
                            "username": user[1],
                            "service": "Emby",
                            "expiry_time": user[2],
                            "line": user[3],
                        }
                    )

            # 按服务类型和到期时间排序
            premium_users.sort(
                key=lambda x: (
                    x["service"],
                    x["expiry_time"] if x["expiry_time"] else "9999-12-31",
                )
            )

            return premium_users

        except Exception as e:
            logger.error(f"Error getting all active premium users: {e}")
            return []

    def get_all_premium_traffic_debt_users(self) -> list:
        """获取所有有 Premium 流量欠额或预计结算后欠额的用户"""
        debt_users = []
        now = datetime.now(settings.TZ)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        premium_lines = settings.PREMIUM_STREAM_BACKEND

        if not premium_lines:
            return debt_users

        try:
            with get_session() as session:
                plex_traffic_rows = session.execute(
                    select(
                        LineTrafficStats.user_id,
                        func.coalesce(func.sum(LineTrafficStats.send_bytes), 0),
                    )
                    .where(
                        LineTrafficStats.service == "plex",
                        LineTrafficStats.user_id.isnot(None),
                        LineTrafficStats.line.in_(premium_lines),
                        LineTrafficStats.timestamp >= today_start.isoformat(),
                        LineTrafficStats.timestamp <= today_end.isoformat(),
                    )
                    .group_by(LineTrafficStats.user_id)
                ).fetchall()
                plex_today_traffic = {
                    str(user_id): int(traffic or 0)
                    for user_id, traffic in plex_traffic_rows
                    if user_id
                }
                plex_today_user_ids = [
                    int(user_id)
                    for user_id in plex_today_traffic
                    if str(user_id).isdigit()
                ]

                emby_traffic_rows = session.execute(
                    select(
                        LineTrafficStats.username,
                        func.coalesce(func.sum(LineTrafficStats.send_bytes), 0),
                    )
                    .where(
                        LineTrafficStats.service == "emby",
                        LineTrafficStats.line.in_(premium_lines),
                        LineTrafficStats.timestamp >= today_start.isoformat(),
                        LineTrafficStats.timestamp <= today_end.isoformat(),
                    )
                    .group_by(LineTrafficStats.username)
                ).fetchall()
                emby_today_traffic = {
                    username.lower(): int(traffic or 0)
                    for username, traffic in emby_traffic_rows
                    if username
                }

                plex_stmt = select(
                    PlexUser.plex_id,
                    PlexUser.tg_id,
                    PlexUser.plex_username,
                    PlexUser.plex_line,
                    PlexUser.is_premium,
                    PlexUser.premium_traffic_debt_bytes,
                ).where(
                    (PlexUser.premium_traffic_debt_bytes > 0)
                    | (PlexUser.plex_id.in_(plex_today_user_ids))
                )
                plex_users = session.execute(plex_stmt).fetchall()

                emby_stmt = select(
                    EmbyUser.emby_username,
                    EmbyUser.tg_id,
                    EmbyUser.emby_line,
                    EmbyUser.is_premium,
                    EmbyUser.premium_traffic_debt_bytes,
                ).where(
                    (EmbyUser.premium_traffic_debt_bytes > 0)
                    | (
                        func.lower(EmbyUser.emby_username).in_(
                            list(emby_today_traffic.keys())
                        )
                    )
                )
                emby_users = session.execute(emby_stmt).fetchall()

            for user in plex_users:
                plex_id = user[0]
                today_premium_traffic = plex_today_traffic.get(str(plex_id), 0)
                quota_status = self.get_plex_premium_quota_status(plex_id)
                daily_limit = quota_status["daily_limit"]
                current_debt = quota_status["current_debt"]
                projected_debt = min(
                    max(current_debt + today_premium_traffic - daily_limit, 0),
                    daily_limit * 2,
                )
                today_exceed_traffic = max(
                    today_premium_traffic - quota_status["remaining_free"], 0
                )

                if current_debt > 0 or projected_debt > 0:
                    debt_users.append(
                        {
                            "service": "Plex",
                            "username": user[2],
                            "tg_id": user[1],
                            "is_premium": bool(user[4]),
                            "current_debt": current_debt,
                            "today_exceed_traffic": today_exceed_traffic,
                            "projected_debt": projected_debt,
                        }
                    )

            for user in emby_users:
                username = user[0]
                today_premium_traffic = emby_today_traffic.get(username.lower(), 0)
                quota_status = self.get_emby_premium_quota_status(username)
                daily_limit = quota_status["daily_limit"]
                current_debt = quota_status["current_debt"]
                projected_debt = min(
                    max(current_debt + today_premium_traffic - daily_limit, 0),
                    daily_limit * 2,
                )
                today_exceed_traffic = max(
                    today_premium_traffic - quota_status["remaining_free"], 0
                )

                if current_debt > 0 or projected_debt > 0:
                    debt_users.append(
                        {
                            "service": "Emby",
                            "username": username,
                            "tg_id": user[1],
                            "is_premium": bool(user[3]),
                            "current_debt": current_debt,
                            "today_exceed_traffic": today_exceed_traffic,
                            "projected_debt": projected_debt,
                        }
                    )

            debt_users.sort(
                key=lambda item: (
                    item["service"],
                    -item["projected_debt"],
                    -item["current_debt"],
                    item["username"] or "",
                )
            )
            return debt_users
        except Exception as e:
            logger.error(f"Error getting premium traffic debt users: {e}")
            return []

    # ==================== Auction Operations ====================

    def create_auction(
        self,
        title: str,
        description: str,
        starting_price: float,
        end_time: int,
        created_by: int,
    ) -> Optional[int]:
        """创建竞拍"""
        try:
            with get_session() as session:
                created_at = int(time.time())
                auction = Auctions(
                    title=title,
                    description=description,
                    starting_price=starting_price,
                    current_price=starting_price,
                    end_time=end_time,
                    created_by=created_by,
                    created_at=created_at,
                )
                session.add(auction)
                # flush, 拿到 id
                session.flush()
                return auction.id
        except Exception as e:
            logger.error(f"Error creating auction: {e}")
            return None

    def get_auction_by_id(self, auction_id: int) -> Optional[dict]:
        """根据ID获取竞拍信息"""
        try:
            with get_session() as session:
                stmt = select(Auctions).where(Auctions.id == auction_id)
                auction = session.execute(stmt).scalar_one_or_none()

                if auction:
                    return {
                        "id": auction.id,
                        "title": auction.title or f"竞拍活动 #{auction.id}",
                        "description": auction.description or "无描述",
                        "starting_price": auction.starting_price or 0,
                        "current_price": auction.current_price
                        or auction.starting_price
                        or 0,
                        "end_time": auction.end_time,
                        "created_by": auction.created_by,
                        "created_at": auction.created_at,
                        "is_active": auction.is_active,
                        "winner_id": auction.winner_id,
                        "bid_count": auction.bid_count,
                    }
                return None
        except Exception as e:
            logger.error(f"Error getting auction by id: {e}")
            return None

    def get_active_auctions(self, limit: int = 50) -> List[dict]:
        """获取活跃竞拍列表"""
        try:
            with get_session() as session:
                current_time = int(time.time())
                stmt = (
                    select(Auctions)
                    .where(Auctions.is_active == 1, Auctions.end_time > current_time)
                    .order_by(Auctions.created_at.desc())
                    .limit(limit)
                )
                results = session.execute(stmt).scalars().all()

                auctions = []
                for auction in results:
                    auctions.append(
                        {
                            "id": auction.id,
                            "title": auction.title or f"竞拍活动 #{auction.id}",
                            "description": auction.description or "无描述",
                            "starting_price": auction.starting_price or 0,
                            "current_price": auction.current_price
                            or auction.starting_price
                            or 0,
                            "end_time": auction.end_time,
                            "created_by": auction.created_by,
                            "created_at": auction.created_at,
                            "is_active": auction.is_active,
                            "winner_id": auction.winner_id,
                            "bid_count": auction.bid_count,
                        }
                    )
                return auctions
        except Exception as e:
            logger.error(f"Error getting active auctions: {e}")
            return []

    def place_bid(self, auction_id: int, bidder_id: int, bid_amount: float) -> bool:
        """出价"""
        try:
            with get_session() as session:
                bid_time = int(time.time())

                # 检查竞拍是否存在且活跃
                auction = session.execute(
                    select(Auctions).where(Auctions.id == auction_id)
                ).scalar_one_or_none()

                if not auction or not auction.is_active or auction.end_time <= bid_time:
                    return False

                # 检查出价是否高于当前价格
                if bid_amount <= auction.current_price:
                    return False

                # 插入出价记录
                bid = AuctionBids(
                    auction_id=auction_id,
                    bidder_id=bidder_id,
                    bid_amount=bid_amount,
                    bid_time=bid_time,
                )
                session.add(bid)

                # 更新竞拍当前价格和出价次数
                session.execute(
                    update(Auctions)
                    .where(Auctions.id == auction_id)
                    .values(current_price=bid_amount, bid_count=Auctions.bid_count + 1)
                )
                return True
        except Exception as e:
            logger.error(f"Error placing bid: {e}")
            return False

    def get_auction_bids(self, auction_id: int, limit: int = 50) -> List[dict]:
        """获取竞拍出价记录"""
        try:
            with get_session() as session:
                stmt = (
                    select(AuctionBids)
                    .where(AuctionBids.auction_id == auction_id)
                    .order_by(AuctionBids.bid_time.desc())
                    .limit(limit)
                )
                results = session.execute(stmt).scalars().all()

                bids = []
                for bid in results:
                    bids.append(
                        {
                            "id": bid.id,
                            "auction_id": bid.auction_id,
                            "bidder_id": bid.bidder_id,
                            "bid_amount": bid.bid_amount,
                            "bid_time": bid.bid_time,
                        }
                    )
                return bids
        except Exception as e:
            logger.error(f"Error getting auction bids: {e}")
            return []

    def get_user_highest_bid(self, auction_id: int, user_id: int) -> Optional[float]:
        """获取用户在特定竞拍中的最高出价"""
        try:
            with get_session() as session:
                stmt = select(func.max(AuctionBids.bid_amount)).where(
                    AuctionBids.auction_id == auction_id,
                    AuctionBids.bidder_id == user_id,
                )
                result = session.execute(stmt).scalar()
                return result
        except Exception as e:
            logger.error(f"Error getting user highest bid: {e}")
            return None

    def get_auction_participants(
        self, auction_id: int, exclude_user_id: Optional[int] = None
    ) -> List[int]:
        """获取拍卖的所有参与者（出价者）ID列表，可排除指定用户"""
        try:
            with get_session() as session:
                if exclude_user_id:
                    stmt = select(func.distinct(AuctionBids.bidder_id)).where(
                        AuctionBids.auction_id == auction_id,
                        AuctionBids.bidder_id != exclude_user_id,
                    )
                else:
                    stmt = select(func.distinct(AuctionBids.bidder_id)).where(
                        AuctionBids.auction_id == auction_id
                    )
                results = session.execute(stmt).scalars().all()
                return list(results)
        except Exception as e:
            logger.error(f"Error getting auction participants: {e}")
            return []

    def finish_expired_auctions(self) -> List[dict]:
        """结束过期的竞拍"""
        try:
            with get_session() as session:
                current_time = int(time.time())

                # 查找过期的活跃竞拍
                stmt = select(Auctions).where(
                    Auctions.is_active == 1, Auctions.end_time <= current_time
                )
                expired_auctions = session.execute(stmt).scalars().all()

                finished_auctions = []
                for auction in expired_auctions:
                    auction_id = auction.id

                    # 获取最高出价者
                    highest_bid_stmt = (
                        select(AuctionBids.bidder_id, func.max(AuctionBids.bid_amount))
                        .where(AuctionBids.auction_id == auction_id)
                        .group_by(AuctionBids.auction_id)
                    )
                    highest_bid = session.execute(highest_bid_stmt).fetchone()

                    winner_id = highest_bid[0] if highest_bid else None
                    final_price = auction.current_price
                    credits_reduced = False

                    # 如果有获胜者，扣除其积分
                    if winner_id and highest_bid:
                        final_price = highest_bid[1]

                        # 获取用户当前积分
                        stats = session.execute(
                            select(Statistics).where(Statistics.tg_id == winner_id)
                        ).scalar_one_or_none()

                        if stats and stats.credits >= final_price:
                            session.execute(
                                update(Statistics)
                                .where(Statistics.tg_id == winner_id)
                                .values(credits=Statistics.credits - final_price)
                            )
                            credits_reduced = True
                            logger.info(
                                f"Auction {auction_id} finished: deducted {final_price} credits from winner {winner_id}"
                            )
                        else:
                            logger.warning(
                                f"Winner {winner_id} has insufficient credits for auction {auction_id} (price: {final_price})"
                            )

                    # 更新竞拍状态
                    session.execute(
                        update(Auctions)
                        .where(Auctions.id == auction_id)
                        .values(
                            is_active=0, winner_id=winner_id, current_price=final_price
                        )
                    )

                    finished_auctions.append(
                        {
                            "id": auction_id,
                            "title": auction.title or f"竞拍活动 #{auction_id}",
                            "winner_id": winner_id,
                            "final_price": final_price,
                            "credits_reduced": credits_reduced,
                        }
                    )
                return finished_auctions
        except Exception as e:
            logger.error(f"Error finishing expired auctions: {e}")
            logger.error(traceback.format_exc())
            return []

    def get_auction_stats(self) -> dict:
        """获取竞拍统计数据"""
        try:
            with get_session() as session:
                current_time = int(time.time())

                # 总竞拍数
                total_auctions = session.execute(
                    select(func.count(Auctions.id))
                ).scalar()

                # 活跃竞拍数
                active_auctions = session.execute(
                    select(func.count(Auctions.id)).where(
                        Auctions.is_active == 1, Auctions.end_time > current_time
                    )
                ).scalar()

                # 总出价数
                total_bids = session.execute(
                    select(func.count(AuctionBids.id))
                ).scalar()

                # 总成交价值
                total_value = (
                    session.execute(
                        select(func.sum(Auctions.current_price)).where(
                            Auctions.winner_id.isnot(None)
                        )
                    ).scalar()
                    or 0.0
                )

                return {
                    "total_auctions": total_auctions,
                    "active_auctions": active_auctions,
                    "total_bids": total_bids,
                    "total_value": float(total_value),
                }
        except Exception as e:
            logger.error(f"Error getting auction stats: {e}")
            return {
                "total_auctions": 0,
                "active_auctions": 0,
                "total_bids": 0,
                "total_value": 0.0,
            }

    def get_all_auctions(
        self, status: Optional[str] = None, limit: int = 50, offset: int = 0
    ) -> List[dict]:
        """获取所有竞拍活动（管理员用）"""
        try:
            with get_session() as session:
                current_time = int(time.time())

                if status == "active":
                    stmt = (
                        select(Auctions)
                        .where(
                            Auctions.is_active == 1, Auctions.end_time > current_time
                        )
                        .order_by(Auctions.created_at.desc())
                        .limit(limit)
                        .offset(offset)
                    )
                elif status == "ended":
                    stmt = (
                        select(Auctions)
                        .where(
                            (Auctions.is_active == 0)
                            | (Auctions.end_time <= current_time)
                        )
                        .order_by(Auctions.created_at.desc())
                        .limit(limit)
                        .offset(offset)
                    )
                else:
                    stmt = (
                        select(Auctions)
                        .order_by(Auctions.created_at.desc())
                        .limit(limit)
                        .offset(offset)
                    )

                results = session.execute(stmt).scalars().all()

                auctions = []
                for auction in results:
                    # 获取出价数量
                    bid_count = session.execute(
                        select(func.count(AuctionBids.id)).where(
                            AuctionBids.auction_id == auction.id
                        )
                    ).scalar()

                    # 判断状态
                    if not auction.is_active:
                        auction_status = "ended"
                    elif auction.end_time <= current_time:
                        auction_status = "ended"
                    else:
                        auction_status = "active"

                    auctions.append(
                        {
                            "id": auction.id,
                            "title": auction.title or f"竞拍活动 #{auction.id}",
                            "description": auction.description or "无描述",
                            "starting_price": auction.starting_price or 0,
                            "current_price": auction.current_price
                            or auction.starting_price
                            or 0,
                            "end_time": auction.end_time,
                            "created_by": auction.created_by,
                            "created_at": auction.created_at,
                            "is_active": bool(auction.is_active),
                            "winner_id": auction.winner_id,
                            "bid_count": bid_count,
                            "status": auction_status,
                        }
                    )

                return auctions
        except Exception as e:
            logger.error(f"Error getting all auctions: {e}")
            return []

    def update_auction(self, auction_id: int, update_data: dict) -> bool:
        """更新竞拍活动"""
        try:
            with get_session() as session:
                values_to_update = {}

                if "title" in update_data:
                    values_to_update["title"] = update_data["title"]
                if "description" in update_data:
                    values_to_update["description"] = update_data["description"]
                if "starting_price" in update_data:
                    values_to_update["starting_price"] = update_data["starting_price"]
                if "end_time" in update_data:
                    values_to_update["end_time"] = update_data["end_time"]

                if not values_to_update:
                    return False

                result = session.execute(
                    update(Auctions)
                    .where(Auctions.id == auction_id)
                    .values(**values_to_update)
                )
                return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating auction: {e}")
            return False

    def delete_auction(self, auction_id: int) -> bool:
        """删除竞拍活动"""
        try:
            with get_session() as session:
                # 先删除相关的出价记录
                session.execute(
                    delete(AuctionBids).where(AuctionBids.auction_id == auction_id)
                )

                # 再删除竞拍活动
                result = session.execute(
                    delete(Auctions).where(Auctions.id == auction_id)
                )
                return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting auction: {e}")
            return False

    def finish_auction_by_id(self, auction_id: int) -> tuple:
        """手动结束指定竞拍活动"""
        try:
            with get_session() as session:
                # 获取竞拍信息
                auction = session.execute(
                    select(Auctions).where(Auctions.id == auction_id)
                ).scalar_one_or_none()

                if not auction:
                    return False, f"竞拍 id {auction_id} 不存在"

                # 获取最高出价
                highest_bid_stmt = (
                    select(AuctionBids.bidder_id, AuctionBids.bid_amount)
                    .where(AuctionBids.auction_id == auction_id)
                    .order_by(AuctionBids.bid_amount.desc())
                    .limit(1)
                )
                highest_bid = session.execute(highest_bid_stmt).fetchone()

                winner_id = None
                final_price = auction.starting_price
                credits_reduced = False

                if highest_bid:
                    winner_id = highest_bid[0]
                    final_price = highest_bid[1]

                    # 扣除获胜者的积分
                    stats = session.execute(
                        select(Statistics).where(Statistics.tg_id == winner_id)
                    ).scalar_one_or_none()

                    if stats and stats.credits >= final_price:
                        session.execute(
                            update(Statistics)
                            .where(Statistics.tg_id == winner_id)
                            .values(credits=Statistics.credits - final_price)
                        )
                        credits_reduced = True

                # 更新竞拍状态
                session.execute(
                    update(Auctions)
                    .where(Auctions.id == auction_id)
                    .values(is_active=0, winner_id=winner_id, current_price=final_price)
                )
                return True, {
                    "id": auction_id,
                    "title": auction.title,
                    "winner_id": winner_id,
                    "final_price": final_price,
                    "credits_reduced": credits_reduced,
                }

        except Exception as e:
            logger.error(f"Error finishing auction {auction_id}: {e}")
            logger.error(traceback.format_exc())
            return False, str(e)

    def get_user_auction_history(self, user_id: int, limit: int = 20) -> List[dict]:
        """获取用户参与的竞拍历史"""
        try:
            with get_session() as session:
                # 获取用户参与的竞拍
                stmt = (
                    select(Auctions)
                    .join(AuctionBids, Auctions.id == AuctionBids.auction_id)
                    .where(AuctionBids.bidder_id == user_id)
                    .order_by(Auctions.created_at.desc())
                    .limit(limit)
                    .distinct()
                )
                results = session.execute(stmt).scalars().all()

                auctions = []
                for auction in results:
                    # 获取用户最高出价
                    highest_bid = session.execute(
                        select(func.max(AuctionBids.bid_amount)).where(
                            AuctionBids.auction_id == auction.id,
                            AuctionBids.bidder_id == user_id,
                        )
                    ).scalar()

                    auctions.append(
                        {
                            "id": auction.id,
                            "title": auction.title or f"竞拍活动 #{auction.id}",
                            "description": auction.description or "无描述",
                            "starting_price": auction.starting_price or 0,
                            "current_price": auction.current_price
                            or auction.starting_price
                            or 0,
                            "end_time": auction.end_time,
                            "created_by": auction.created_by,
                            "created_at": auction.created_at,
                            "is_active": bool(auction.is_active),
                            "winner_id": auction.winner_id,
                            "user_highest_bid": highest_bid,
                            "is_winner": auction.winner_id == user_id,
                        }
                    )

                return auctions
        except Exception as e:
            logger.error(f"Error getting user auction history: {e}")
            return []

    def get_detailed_auction_stats(
        self, start_date: Optional[int] = None, end_date: Optional[int] = None
    ) -> dict:
        """获取详细的竞拍统计数据"""
        try:
            with get_session() as session:
                # 设置默认时间范围（如果未提供）
                if not start_date:
                    start_date = 0
                if not end_date:
                    end_date = int(time.time())

                # 基本统计
                stats = self.get_auction_stats()

                # 时间段内的统计
                period_auctions = session.execute(
                    select(func.count(Auctions.id)).where(
                        Auctions.created_at.between(start_date, end_date)
                    )
                ).scalar()

                # 时间段内的出价数
                period_bids = session.execute(
                    select(func.count(AuctionBids.id))
                    .join(Auctions, AuctionBids.auction_id == Auctions.id)
                    .where(Auctions.created_at.between(start_date, end_date))
                ).scalar()

                # 平均出价数
                avg_bids = (
                    session.execute(
                        select(func.avg(func.count(AuctionBids.id))).group_by(
                            AuctionBids.auction_id
                        )
                    ).scalar()
                    or 0.0
                )

                # 最高成交价
                highest_price = (
                    session.execute(
                        select(func.max(Auctions.current_price)).where(
                            Auctions.winner_id.isnot(None)
                        )
                    ).scalar()
                    or 0.0
                )

                stats.update(
                    {
                        "period_auctions": period_auctions,
                        "period_bids": period_bids,
                        "avg_bids_per_auction": float(avg_bids),
                        "highest_transaction": float(highest_price),
                        "start_date": start_date,
                        "end_date": end_date,
                    }
                )

                return stats
        except Exception as e:
            logger.error(f"Error getting detailed auction stats: {e}")
            return self.get_auction_stats()

    # ==================== Traffic Statistics Operations ====================

    def create_line_traffic_entry(
        self,
        line: str,
        send_bytes: int,
        service: str,
        username: str,
        user_id: str,
        timestamp: str,
        event_hash: str,
        request_uri: Optional[str] = None,
        upstream: Optional[str] = None,
        upstream_response_time: Optional[str] = None,
    ) -> tuple[bool, bool]:
        """创建流量统计记录"""
        try:
            with get_session() as session:
                existing_stmt = select(LineTrafficStats.id).where(
                    LineTrafficStats.event_hash == event_hash
                )
                existing_id = session.execute(existing_stmt).scalar_one_or_none()
                if existing_id is not None:
                    logger.info(
                        f"Skip duplicated line traffic entry, event_hash={event_hash}"
                    )
                    return False, True

                traffic_entry = LineTrafficStats(
                    line=line,
                    send_bytes=send_bytes,
                    service=service,
                    username=username,
                    user_id=user_id,
                    timestamp=timestamp,
                    event_hash=event_hash,
                    request_uri=request_uri,
                    upstream=upstream,
                    upstream_response_time=upstream_response_time,
                )
                session.add(traffic_entry)
                return True, False
        except Exception as e:
            # 并发场景下仍可能在显式查询后发生唯一键冲突，保留兜底判断
            if "uq_line_traffic_event_hash" in str(
                e
            ) or "UNIQUE constraint failed: line_traffic_stats.event_hash" in str(e):
                logger.info(
                    f"Skip duplicated line traffic entry, event_hash={event_hash}"
                )
                return False, True
            logger.error(f"Error creating line traffic entry: {e}")
            return False, False

    def bulk_create_line_traffic_entries(
        self,
        rows: list[dict],
        *,
        query_chunk: int = 500,
        insert_chunk: int = 500,
    ) -> dict[str, str]:
        """批量创建流量统计记录

        Args:
            rows: 每项为含 event_hash 及 LineTrafficStats 字段的 dict

        Returns:
            {event_hash: 'inserted' | 'duplicate' | 'failed'}
            默认 'failed'（未确定，调用方应重试）；查重命中为 'duplicate'；
            成功落库为 'inserted'。批内重复 event_hash 在此防御性收敛，
            每个 event_hash 只插入一次。
        """
        if not rows:
            return {}

        # 防御性去重：同一 event_hash 只保留首条
        unique: dict[str, dict] = {}
        for row in rows:
            unique.setdefault(row["event_hash"], row)

        # 默认 failed：任何未走到确定结论的 event_hash 都交给上游重试
        result: dict[str, str] = {event_hash: "failed" for event_hash in unique}

        try:
            with get_session() as session:
                # 分块预查重，避免 SQLite IN 参数上限（999）
                hashes = list(unique.keys())
                existing: set[str] = set()
                for i in range(0, len(hashes), query_chunk):
                    chunk = hashes[i : i + query_chunk]
                    stmt = select(LineTrafficStats.event_hash).where(
                        LineTrafficStats.event_hash.in_(chunk)
                    )
                    existing.update(session.execute(stmt).scalars().all())

                for event_hash in existing:
                    result[event_hash] = "duplicate"

                pending = [unique[h] for h in hashes if h not in existing]

                # 按 service 分组后再分块插入：plex 的 user_id 是整数、emby 的是 hex
                # 字符串，而 user_id 列为 text。批量插入用多行 VALUES，Postgres 会按列
                # 统一推断类型，同一批混入整数与字符串会把该列推断为 integer，导致
                # 字符串报 "invalid input syntax for type integer"。按 service 分批可
                # 保证每批 user_id 类型同构，无需改写入值。单块失败仅影响该块。
                pending_by_service: dict[str, list[dict]] = {}
                for row in pending:
                    pending_by_service.setdefault(row["service"], []).append(row)

                for service_rows in pending_by_service.values():
                    for i in range(0, len(service_rows), insert_chunk):
                        chunk_rows = service_rows[i : i + insert_chunk]
                        try:
                            session.add_all(
                                [LineTrafficStats(**row) for row in chunk_rows]
                            )
                            session.flush()
                            session.commit()
                            for row in chunk_rows:
                                result[row["event_hash"]] = "inserted"
                        except Exception as e:
                            session.rollback()
                            logger.error(
                                f"批量插入流量日志失败，本块 {len(chunk_rows)} 条将重试: {e}"
                            )
        except Exception as e:
            logger.error(f"批量创建流量日志记录时发生错误: {e}")

        return result

    def get_premium_line_traffic_statistics(self) -> list:
        """获取Premium线路流量统计信息"""
        try:
            now = datetime.now(settings.TZ)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = today_start - timedelta(days=now.weekday())
            month_start = today_start.replace(day=1)

            # 获取Premium线路列表
            premium_lines = settings.PREMIUM_STREAM_BACKEND

            line_stats = []

            with get_session() as session:
                for line in premium_lines:
                    # 计算今日流量
                    today_traffic = session.execute(
                        select(
                            func.coalesce(func.sum(LineTrafficStats.send_bytes), 0)
                        ).where(
                            LineTrafficStats.line == line,
                            LineTrafficStats.timestamp >= today_start.isoformat(),
                        )
                    ).scalar()

                    # 计算本周流量
                    week_traffic = session.execute(
                        select(
                            func.coalesce(func.sum(LineTrafficStats.send_bytes), 0)
                        ).where(
                            LineTrafficStats.line == line,
                            LineTrafficStats.timestamp >= week_start.isoformat(),
                        )
                    ).scalar()

                    # 计算本月流量
                    month_traffic = session.execute(
                        select(
                            func.coalesce(func.sum(LineTrafficStats.send_bytes), 0)
                        ).where(
                            LineTrafficStats.line == line,
                            LineTrafficStats.timestamp >= month_start.isoformat(),
                        )
                    ).scalar()

                    # 获取当前线路流量排名前五的用户（基于今日数据）
                    top_users_result = session.execute(
                        select(
                            LineTrafficStats.username,
                            func.sum(LineTrafficStats.send_bytes).label(
                                "total_traffic"
                            ),
                        )
                        .where(
                            LineTrafficStats.line == line,
                            LineTrafficStats.timestamp >= today_start.isoformat(),
                        )
                        .group_by(LineTrafficStats.username)
                        .order_by(func.sum(LineTrafficStats.send_bytes).desc())
                        .limit(5)
                    ).fetchall()

                    top_users = []
                    for username, traffic in top_users_result:
                        top_users.append({"username": username, "traffic": traffic})

                    line_stats.append(
                        {
                            "line": line,
                            "today_traffic": today_traffic,
                            "week_traffic": week_traffic,
                            "month_traffic": month_traffic,
                            "top_users": top_users,
                        }
                    )

            return line_stats

        except Exception as e:
            logger.error(f"Error getting premium line traffic statistics: {e}")
            return []

    def get_user_daily_traffic(
        self,
        username: Optional[str] = None,
        user_id: Optional[str] = None,
        service: str = None,
        date: datetime = None,
        premium_only: bool = False,
    ) -> int:
        """获取用户指定日期的流量消耗，默认为今日"""
        if not username and not user_id:
            logger.error(
                "Username or user_id must be provided to get user daily traffic"
            )
            return 0
        try:
            # 如果未指定日期，使用今日
            if date is None:
                date = datetime.now(settings.TZ)

            # 确保日期对象包含时区信息
            if date.tzinfo is None:
                date = date.replace(tzinfo=settings.TZ)
            else:
                date = date.astimezone(settings.TZ)

            # 计算指定日期的开始和结束时间
            day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = date.replace(hour=23, minute=59, second=59, microsecond=999999)

            with get_session() as session:
                # 原始流量表按天精确查询，月初结算昨日数据也依赖这里
                if user_id:
                    conditions = [
                        LineTrafficStats.user_id == user_id,
                        LineTrafficStats.service == service,
                        LineTrafficStats.timestamp >= day_start.isoformat(),
                        LineTrafficStats.timestamp <= day_end.isoformat(),
                    ]
                else:
                    conditions = [
                        func.lower(LineTrafficStats.username) == username.lower(),
                        LineTrafficStats.service == service,
                        LineTrafficStats.timestamp >= day_start.isoformat(),
                        LineTrafficStats.timestamp <= day_end.isoformat(),
                    ]

                if premium_only:
                    premium_lines = settings.PREMIUM_STREAM_BACKEND
                    if premium_lines:
                        conditions.append(LineTrafficStats.line.in_(premium_lines))
                    else:
                        return 0

                result = session.execute(
                    select(
                        func.coalesce(func.sum(LineTrafficStats.send_bytes), 0)
                    ).where(*conditions)
                ).scalar()

                return result if result else 0

        except Exception as e:
            logger.error(
                f"Error getting user daily traffic for {username or user_id}: {e}"
            )
            return 0

    def get_traffic_statistics(self) -> dict:
        """获取全面的流量统计信息，包括今日/本周/本月，按服务类型和线路分类"""
        try:
            now = datetime.now(settings.TZ)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = today_start - timedelta(days=now.weekday())
            month_start = today_start.replace(day=1)

            periods = [
                ("today", today_start.isoformat()),
                ("week", week_start.isoformat()),
                ("month", month_start.isoformat()),
            ]

            result = {}

            with get_session() as session:
                # 获取所有已批准的自定义线路域名
                approved_custom_lines = (
                    session.execute(
                        select(CustomLine.domain).where(CustomLine.status == "approved")
                    )
                    .scalars()
                    .all()
                )

                for period_name, start_time in periods:
                    # 查询按服务类型分组的流量统计
                    service_results = session.execute(
                        select(
                            LineTrafficStats.service,
                            func.coalesce(
                                func.sum(LineTrafficStats.send_bytes), 0
                            ).label("total_traffic"),
                        )
                        .where(LineTrafficStats.timestamp >= start_time)
                        .group_by(LineTrafficStats.service)
                    ).fetchall()

                    # 查询按线路分组的流量统计
                    line_results = session.execute(
                        select(
                            LineTrafficStats.line,
                            func.coalesce(
                                func.sum(LineTrafficStats.send_bytes), 0
                            ).label("total_traffic"),
                        )
                        .where(LineTrafficStats.timestamp >= start_time)
                        .group_by(LineTrafficStats.line)
                        .order_by(func.sum(LineTrafficStats.send_bytes).desc())
                    ).fetchall()

                    # 计算总流量
                    total_traffic = session.execute(
                        select(
                            func.coalesce(func.sum(LineTrafficStats.send_bytes), 0)
                        ).where(LineTrafficStats.timestamp >= start_time)
                    ).scalar()

                    # 构建期间数据
                    period_data = {
                        "total": total_traffic,
                        "emby": 0,
                        "plex": 0,
                        "lines": [],
                        "custom_lines": [],  # 新增：自定义线路统计
                    }

                    for service, traffic in service_results:
                        if service.lower() == "emby":
                            period_data["emby"] = traffic
                        elif service.lower() == "plex":
                            period_data["plex"] = traffic

                    # 添加线路数据
                    for line, traffic in line_results:
                        is_known_line = False
                        # 检查是否是已知线路
                        for _line in (
                            settings.STREAM_BACKEND + settings.PREMIUM_STREAM_BACKEND
                        ):
                            if line.lower() in _line.lower():
                                period_data["lines"].append(
                                    {"line": line, "traffic": traffic}
                                )
                                is_known_line = True
                                break

                        # 如果不是已知线路，检查是否是已批准的自定义线路
                        if not is_known_line and line in approved_custom_lines:
                            period_data["custom_lines"].append(
                                {"line": line, "traffic": traffic, "is_custom": True}
                            )

                    result[period_name] = period_data

            return result

        except Exception as e:
            logger.error(f"Error getting comprehensive traffic statistics: {e}")
            return {
                "today": {
                    "total": 0,
                    "emby": 0,
                    "plex": 0,
                    "lines": [],
                    "custom_lines": [],
                },
                "week": {
                    "total": 0,
                    "emby": 0,
                    "plex": 0,
                    "lines": [],
                    "custom_lines": [],
                },
                "month": {
                    "total": 0,
                    "emby": 0,
                    "plex": 0,
                    "lines": [],
                    "custom_lines": [],
                },
            }

    def get_plex_traffic_rank(self, start_date=None, end_date=None) -> list:
        """获取 Plex 流量排行榜"""
        try:
            # 使用北京时间
            now_beijing = datetime.now(settings.TZ)

            if start_date is None:
                # 默认为今日开始
                start_date = now_beijing.replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
            else:
                # 确保是当月的日期
                current_month_start = now_beijing.replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                )
                if start_date < current_month_start:
                    start_date = current_month_start

            if end_date is None:
                # 默认为今日结束
                end_date = now_beijing.replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
            else:
                # 确保不超过今日
                today_end = now_beijing.replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
                if end_date > today_end:
                    end_date = today_end

            # 仅当月数据，从 line_traffic_stats 表查询
            with get_session() as session:
                stmt = (
                    select(
                        PlexUser.plex_username,
                        LineTrafficStats.user_id,
                        func.sum(LineTrafficStats.send_bytes).label("total_traffic"),
                        func.coalesce(PlexUser.is_premium, 0).label("is_premium"),
                        PlexUser.tg_id,
                    )
                    .select_from(LineTrafficStats)
                    .outerjoin(
                        PlexUser,
                        func.lower(LineTrafficStats.username)
                        == func.lower(PlexUser.plex_username),
                    )
                    .where(
                        LineTrafficStats.service == "plex",
                        LineTrafficStats.timestamp >= start_date.isoformat(),
                        LineTrafficStats.timestamp <= end_date.isoformat(),
                        LineTrafficStats.username.isnot(None),
                        LineTrafficStats.username != "",
                    )
                    .group_by(
                        func.lower(LineTrafficStats.username),
                        LineTrafficStats.user_id,
                        PlexUser.is_premium,
                        PlexUser.tg_id,
                        PlexUser.plex_username,
                    )
                    .order_by(func.sum(LineTrafficStats.send_bytes).desc())
                    .limit(50)
                )

                results = session.execute(stmt).fetchall()
                return [(r[0], r[1], r[2], r[3], r[4]) for r in results]

        except Exception as e:
            logger.error(f"Error getting Plex traffic rank: {e}")
            return []

    def get_emby_traffic_rank(self, start_date=None, end_date=None) -> list:
        """获取 Emby 流量排行榜"""
        try:
            # 使用北京时间
            now_beijing = datetime.now(settings.TZ)

            if start_date is None:
                # 默认为今日开始
                start_date = now_beijing.replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
            else:
                # 确保是当月的日期
                current_month_start = now_beijing.replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                )
                if start_date < current_month_start:
                    start_date = current_month_start

            if end_date is None:
                # 默认为今日结束
                end_date = now_beijing.replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
            else:
                # 确保不超过今日
                today_end = now_beijing.replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
                if end_date > today_end:
                    end_date = today_end

            with get_session() as session:
                stmt = (
                    select(
                        EmbyUser.emby_username,
                        LineTrafficStats.user_id,
                        func.sum(LineTrafficStats.send_bytes).label("total_traffic"),
                        func.coalesce(EmbyUser.is_premium, 0).label("is_premium"),
                        EmbyUser.tg_id,
                    )
                    .select_from(LineTrafficStats)
                    .outerjoin(
                        EmbyUser,
                        func.lower(LineTrafficStats.username)
                        == func.lower(EmbyUser.emby_username),
                    )
                    .where(
                        LineTrafficStats.service == "emby",
                        LineTrafficStats.timestamp >= start_date.isoformat(),
                        LineTrafficStats.timestamp <= end_date.isoformat(),
                        LineTrafficStats.username.isnot(None),
                        LineTrafficStats.username != "",
                    )
                    .group_by(
                        func.lower(LineTrafficStats.username),
                        LineTrafficStats.user_id,
                        EmbyUser.is_premium,
                        EmbyUser.tg_id,
                        EmbyUser.emby_username,
                    )
                    .order_by(func.sum(LineTrafficStats.send_bytes).desc())
                    .limit(50)
                )

                results = session.execute(stmt).fetchall()
                return [(r[0], r[1], r[2], r[3], r[4]) for r in results]

        except Exception as e:
            logger.error(f"Error getting Emby traffic rank: {e}")
            return []

    def aggregate_monthly_traffic_data(self, target_month: str = None) -> tuple:
        """聚合指定月份的流量数据到月度统计表"""
        try:
            if target_month is None:
                # 默认处理上个月的数据
                now = datetime.now(settings.TZ)
                if now.day == 1:
                    # 如果是每月1号，处理上个月数据
                    last_month = now.replace(day=1) - timedelta(days=1)
                    target_month = last_month.strftime("%Y-%m")
                else:
                    return False, "只能在每月1号自动处理上个月数据"

            logger.info(f"开始聚合 {target_month} 的流量数据")

            # 验证月份格式
            try:
                datetime.strptime(target_month, "%Y-%m")
            except ValueError:
                return False, f"月份格式错误: {target_month}，应为 YYYY-MM 格式"

            with get_session() as session:
                # 检查是否已经聚合过该月份的数据（已改为警告而非阻止）
                existing_check = session.execute(
                    select(func.count(LineTrafficMonthlyStats.id)).where(
                        LineTrafficMonthlyStats.year_month == target_month
                    )
                ).scalar()

                if existing_check > 0:
                    logger.warning(
                        f"月份 {target_month} 已存在 {existing_check} 条聚合数据，将跳过重复记录"
                    )

                # 计算目标月份的开始和结束时间
                month_start = datetime.strptime(
                    f"{target_month}-01", "%Y-%m-%d"
                ).replace(tzinfo=settings.TZ)
                if month_start.month == 12:
                    next_month_start = month_start.replace(
                        year=month_start.year + 1, month=1
                    )
                else:
                    next_month_start = month_start.replace(month=month_start.month + 1)

                month_start_str = month_start.isoformat()
                next_month_start_str = next_month_start.isoformat()

                # 聚合查询：按 line, service, username, user_id 分组求和
                aggregation_stmt = (
                    select(
                        LineTrafficStats.line,
                        LineTrafficStats.service,
                        LineTrafficStats.username,
                        LineTrafficStats.user_id,
                        func.sum(LineTrafficStats.send_bytes).label("total_bytes"),
                        func.count(LineTrafficStats.id).label("record_count"),
                    )
                    .where(
                        LineTrafficStats.timestamp >= month_start_str,
                        LineTrafficStats.timestamp < next_month_start_str,
                    )
                    .group_by(
                        LineTrafficStats.line,
                        LineTrafficStats.service,
                        LineTrafficStats.username,
                        LineTrafficStats.user_id,
                    )
                    .having(func.sum(LineTrafficStats.send_bytes) > 0)
                    .order_by(func.sum(LineTrafficStats.send_bytes).desc())
                )

                aggregated_data = session.execute(aggregation_stmt).fetchall()

                if not aggregated_data:
                    return False, f"月份 {target_month} 没有找到需要聚合的数据"

                # 插入聚合数据到月度统计表
                current_time = datetime.now(settings.TZ).isoformat()
                insert_count = 0
                skip_count = 0
                update_count = 0

                # 使用 SAVEPOINT 来处理每条记录，避免整个事务回滚
                from sqlalchemy import exc as sa_exc

                for record in aggregated_data:
                    line, service, username, user_id, total_bytes, record_count = record

                    # 为每条记录创建一个保存点
                    savepoint = session.begin_nested()

                    try:
                        # 先检查记录是否已存在
                        existing_record = session.execute(
                            select(LineTrafficMonthlyStats).where(
                                LineTrafficMonthlyStats.line == line,
                                LineTrafficMonthlyStats.service == service,
                                LineTrafficMonthlyStats.username == username,
                                LineTrafficMonthlyStats.year_month == target_month,
                            )
                        ).scalar_one_or_none()

                        if existing_record:
                            # 记录已存在，检查是否需要更新
                            if existing_record.total_bytes != total_bytes:
                                existing_record.total_bytes = total_bytes
                                existing_record.created_at = current_time
                                update_count += 1
                                logger.debug(
                                    f"更新月度流量记录: {line}, {service}, {username}, {target_month}"
                                )
                            else:
                                skip_count += 1
                        else:
                            # 记录不存在，插入新记录
                            monthly_stat = LineTrafficMonthlyStats(
                                line=line,
                                service=service,
                                username=username,
                                user_id=user_id,
                                year_month=target_month,
                                total_bytes=total_bytes,
                                created_at=current_time,
                            )
                            session.add(monthly_stat)
                            insert_count += 1

                        # 提交这条记录的保存点
                        savepoint.commit()

                    except sa_exc.IntegrityError:
                        # 唯一约束冲突，回滚到保存点
                        savepoint.rollback()
                        skip_count += 1
                        logger.debug(
                            f"跳过重复记录（唯一约束冲突）: {line}, {service}, {username}, {target_month}"
                        )
                    except Exception as e:
                        # 其他错误，回滚到保存点
                        savepoint.rollback()
                        skip_count += 1
                        logger.warning(
                            f"处理月度聚合数据失败: {e}, 数据: line={line}, service={service}, "
                            f"username={username}, month={target_month}"
                        )

                logger.info(
                    f"成功聚合 {target_month} 月份数据: {len(aggregated_data)} 个用户组合，"
                    f"插入 {insert_count} 条新记录，更新 {update_count} 条记录，跳过 {skip_count} 条重复记录"
                )
                return (
                    True,
                    f"成功聚合 {target_month} 月份数据: 插入了 {insert_count} 条新记录，"
                    f"更新了 {update_count} 条记录，跳过了 {skip_count} 条重复记录",
                )

        except Exception as e:
            logger.error(f"聚合月度流量数据失败: {e}")
            return False, f"聚合月度流量数据失败: {str(e)}"

    def cleanup_monthly_traffic_data(self, target_month: str) -> tuple:
        """清理已聚合月份的原始流量数据"""
        try:
            # 验证月份格式
            try:
                datetime.strptime(target_month, "%Y-%m")
            except ValueError:
                return False, f"月份格式错误: {target_month}，应为 YYYY-MM 格式"

            with get_session() as session:
                # 检查月度聚合数据是否存在
                monthly_check = session.execute(
                    select(func.count(LineTrafficMonthlyStats.id)).where(
                        LineTrafficMonthlyStats.year_month == target_month
                    )
                ).scalar()

                if monthly_check == 0:
                    return (
                        False,
                        f"月份 {target_month} 的聚合数据不存在，不能清理原始数据",
                    )

                # 计算目标月份的时间范围
                month_start = datetime.strptime(
                    f"{target_month}-01", "%Y-%m-%d"
                ).replace(tzinfo=settings.TZ)
                if month_start.month == 12:
                    next_month_start = month_start.replace(
                        year=month_start.year + 1, month=1
                    )
                else:
                    next_month_start = month_start.replace(month=month_start.month + 1)

                month_start_str = month_start.isoformat()
                next_month_start_str = next_month_start.isoformat()

                # 统计要删除的记录数
                delete_count = session.execute(
                    select(func.count(LineTrafficStats.id)).where(
                        LineTrafficStats.timestamp >= month_start_str,
                        LineTrafficStats.timestamp < next_month_start_str,
                    )
                ).scalar()

                if delete_count == 0:
                    return True, f"月份 {target_month} 没有需要清理的原始数据"

                # 删除原始数据
                session.execute(
                    delete(LineTrafficStats).where(
                        LineTrafficStats.timestamp >= month_start_str,
                        LineTrafficStats.timestamp < next_month_start_str,
                    )
                )

                logger.info(
                    f"已清理 {target_month} 月份的 {delete_count} 条原始流量数据"
                )
                return (
                    True,
                    f"成功清理 {target_month} 月份的 {delete_count} 条原始流量数据",
                )

        except Exception as e:
            logger.error(f"清理月度流量数据失败: {e}")
            return False, f"清理月度流量数据失败: {str(e)}"

    def update_traffic_username(self, old_username: str, new_username: str) -> bool:
        """更新流量统计中的用户名"""
        if not old_username or not new_username:
            logger.warning(
                f"跳过流量统计用户名更新，用户名为空: {old_username} -> {new_username}"
            )
            return False

        try:
            with get_session() as session:
                # 更新 line_traffic_stats 表
                raw_result = session.execute(
                    update(LineTrafficStats)
                    .where(
                        func.lower(LineTrafficStats.username) == old_username.lower()
                    )
                    .values(username=new_username)
                )

                # 月度表存在唯一约束 (line, service, username, year_month)，
                # 用户名变更时如果目标用户名记录已存在，需要合并流量后删除旧记录。
                monthly_records = session.execute(
                    select(LineTrafficMonthlyStats).where(
                        func.lower(LineTrafficMonthlyStats.username)
                        == old_username.lower(),
                        LineTrafficMonthlyStats.username != new_username,
                    )
                ).scalars()

                monthly_updated_count = 0
                monthly_merged_count = 0
                for monthly_record in monthly_records:
                    existing_record = session.execute(
                        select(LineTrafficMonthlyStats).where(
                            LineTrafficMonthlyStats.line == monthly_record.line,
                            LineTrafficMonthlyStats.service == monthly_record.service,
                            LineTrafficMonthlyStats.username == new_username,
                            LineTrafficMonthlyStats.year_month
                            == monthly_record.year_month,
                            LineTrafficMonthlyStats.id != monthly_record.id,
                        )
                    ).scalar_one_or_none()

                    if existing_record:
                        existing_record.total_bytes += monthly_record.total_bytes
                        if not existing_record.user_id and monthly_record.user_id:
                            existing_record.user_id = monthly_record.user_id
                        session.delete(monthly_record)
                        monthly_merged_count += 1
                    else:
                        monthly_record.username = new_username
                        monthly_updated_count += 1

                logger.info(
                    f"更新流量统计用户名成功: {old_username} -> {new_username}, "
                    f"原始记录 {raw_result.rowcount} 条, 月度更新 {monthly_updated_count} 条, "
                    f"月度合并 {monthly_merged_count} 条"
                )
                return True
        except Exception as e:
            logger.error(f"更新流量统计用户名失败: {e}")
            return False

    # ==================== Donation Management Operations ====================

    def create_donation_registration(
        self,
        user_id: int,
        payment_method: str,
        amount: float,
        note: str = None,
        is_donation_registration: bool = False,
    ) -> bool:
        """创建捐赠登记记录"""
        try:
            with get_session() as session:
                created_at = datetime.now(settings.TZ).isoformat()

                # 确保统计信息存在以通过外键校验
                stats_exists = session.execute(
                    select(Statistics.tg_id).where(Statistics.tg_id == user_id)
                ).scalar_one_or_none()
                if not stats_exists:
                    session.add(Statistics(tg_id=user_id, credits=0, donation=0))
                    session.flush()

                donation = DonationRegistrations(
                    user_id=user_id,
                    payment_method=payment_method,
                    amount=amount,
                    note=note,
                    created_at=created_at,
                    is_donation_registration=int(is_donation_registration),
                )
                session.add(donation)
                return True
        except Exception as e:
            logger.error(f"创建捐赠登记失败: {e}")
            return False

    def get_donation_registration_by_id(self, registration_id: int) -> Optional[dict]:
        """根据ID获取捐赠登记信息"""
        try:
            from app.utils.utils import get_user_name_from_tg_id

            with get_session() as session:
                stmt = select(DonationRegistrations).where(
                    DonationRegistrations.id == registration_id
                )
                result = session.execute(stmt).scalar_one_or_none()

                if result:
                    user_id = result.user_id
                    processed_by = result.processed_by

                    return {
                        "id": result.id,
                        "user_id": user_id,
                        "payment_method": result.payment_method,
                        "amount": result.amount,
                        "note": result.note,
                        "status": result.status,
                        "admin_note": result.admin_note,
                        "created_at": result.created_at,
                        "processed_at": result.processed_at,
                        "processed_by": processed_by,
                        "is_donation_registration": bool(
                            result.is_donation_registration
                        ),
                        "username": get_user_name_from_tg_id(user_id),
                        "processed_by_username": get_user_name_from_tg_id(processed_by)
                        if processed_by
                        else None,
                    }
                return None
        except Exception as e:
            logger.error(f"获取捐赠登记信息失败: {e}")
            return None

    def get_donation_registrations_by_user(
        self, user_id: int, limit: int = 20
    ) -> List[dict]:
        """获取用户的捐赠登记历史"""
        try:
            from app.utils.utils import get_user_name_from_tg_id

            with get_session() as session:
                stmt = (
                    select(DonationRegistrations)
                    .where(DonationRegistrations.user_id == user_id)
                    .order_by(DonationRegistrations.created_at.desc())
                    .limit(limit)
                )
                results = session.execute(stmt).scalars().all()

                registrations = []
                for result in results:
                    user_id_result = result.user_id
                    processed_by = result.processed_by

                    registrations.append(
                        {
                            "id": result.id,
                            "user_id": user_id_result,
                            "payment_method": result.payment_method,
                            "amount": result.amount,
                            "note": result.note,
                            "status": result.status,
                            "admin_note": result.admin_note,
                            "created_at": result.created_at,
                            "processed_at": result.processed_at,
                            "processed_by": processed_by,
                            "is_donation_registration": bool(
                                result.is_donation_registration
                            ),
                            "username": get_user_name_from_tg_id(user_id_result),
                            "processed_by_username": get_user_name_from_tg_id(
                                processed_by
                            )
                            if processed_by
                            else None,
                        }
                    )
                return registrations
        except Exception as e:
            logger.error(f"获取用户捐赠登记历史失败: {e}")
            return []

    def get_pending_donation_registrations(self, limit: int = 50) -> List[dict]:
        """获取待处理的捐赠登记列表"""
        try:
            from app.utils.utils import get_user_name_from_tg_id

            with get_session() as session:
                stmt = (
                    select(DonationRegistrations)
                    .where(DonationRegistrations.status == "pending")
                    .order_by(DonationRegistrations.created_at.asc())
                    .limit(limit)
                )
                results = session.execute(stmt).scalars().all()

                registrations = []
                for result in results:
                    user_id = result.user_id
                    processed_by = result.processed_by

                    registrations.append(
                        {
                            "id": result.id,
                            "user_id": user_id,
                            "payment_method": result.payment_method,
                            "amount": result.amount,
                            "note": result.note,
                            "status": result.status,
                            "admin_note": result.admin_note,
                            "created_at": result.created_at,
                            "processed_at": result.processed_at,
                            "processed_by": processed_by,
                            "is_donation_registration": bool(
                                result.is_donation_registration
                            ),
                            "username": get_user_name_from_tg_id(user_id),
                            "processed_by_username": get_user_name_from_tg_id(
                                processed_by
                            )
                            if processed_by
                            else None,
                        }
                    )
                return registrations
        except Exception as e:
            logger.error(f"获取待处理捐赠登记失败: {e}")
            return []

    def confirm_donation_registration(
        self,
        registration_id: int,
        approved: bool,
        admin_note: str = None,
        processed_by: int = None,
    ) -> bool:
        """确认捐赠登记状态"""
        try:
            with get_session() as session:
                processed_at = datetime.now(settings.TZ).isoformat()
                status = "approved" if approved else "rejected"

                session.execute(
                    update(DonationRegistrations)
                    .where(DonationRegistrations.id == registration_id)
                    .values(
                        status=status,
                        admin_note=admin_note,
                        processed_at=processed_at,
                        processed_by=processed_by,
                    )
                )
                return True
        except Exception as e:
            logger.error(f"确认捐赠登记失败: {e}")
            return False

    def delete_donation_registration(self, registration_id: int) -> bool:
        """删除捐赠登记记录"""
        try:
            with get_session() as session:
                session.execute(
                    delete(DonationRegistrations).where(
                        DonationRegistrations.id == registration_id
                    )
                )
                return True
        except Exception as e:
            logger.error(f"删除捐赠登记失败: {e}")
            return False

    def get_donation_statistics(self) -> dict:
        """获取捐赠统计信息"""
        try:
            with get_session() as session:
                # 总登记数
                total_registrations = session.execute(
                    select(func.count(DonationRegistrations.id))
                ).scalar()

                # 待处理数
                pending_registrations = session.execute(
                    select(func.count(DonationRegistrations.id)).where(
                        DonationRegistrations.status == "pending"
                    )
                ).scalar()

                # 已批准数
                approved_registrations = session.execute(
                    select(func.count(DonationRegistrations.id)).where(
                        DonationRegistrations.status == "approved"
                    )
                ).scalar()

                # 已拒绝数
                rejected_registrations = session.execute(
                    select(func.count(DonationRegistrations.id)).where(
                        DonationRegistrations.status == "rejected"
                    )
                ).scalar()

                # 总捐赠金额（已批准的）
                total_amount = session.execute(
                    select(func.sum(DonationRegistrations.amount)).where(
                        DonationRegistrations.status == "approved"
                    )
                ).scalar()
                total_amount = float(total_amount) if total_amount else 0.0

                return {
                    "total_registrations": total_registrations,
                    "pending_registrations": pending_registrations,
                    "approved_registrations": approved_registrations,
                    "rejected_registrations": rejected_registrations,
                    "total_approved_amount": total_amount,
                }
        except Exception as e:
            logger.error(f"获取捐赠统计信息失败: {e}")
            return {
                "total_registrations": 0,
                "pending_registrations": 0,
                "approved_registrations": 0,
                "rejected_registrations": 0,
                "total_approved_amount": 0.0,
            }

    # ==================== Crypto Donation Orders Operations ====================

    def create_crypto_donation_order(
        self,
        user_id: int,
        order_id: str,
        crypto_type: str,
        amount: float,
        note: str = None,
    ) -> bool:
        """创建 crypto 捐赠订单"""
        try:
            # 验证加密货币类型是否支持
            if crypto_type not in settings.UPAY_CRYPTO_TYPES:
                logger.error(f"不支持的加密货币类型: {crypto_type}")
                return False

            with get_session() as session:
                created_at = datetime.now(settings.TZ).isoformat()

                order = CryptoDonationOrders(
                    user_id=user_id,
                    order_id=order_id,
                    crypto_type=crypto_type,
                    amount=amount,
                    created_at=created_at,
                    note=note,
                )
                session.add(order)
                return True
        except Exception as e:
            logger.error(f"创建 crypto 捐赠订单失败: {e}")
            return False

    def update_crypto_donation_order_upay_info(
        self,
        order_id: str,
        trade_id: str,
        actual_amount: float,
        payment_address: str,
        payment_url: str,
        expiration_time: int,
    ) -> bool:
        """更新 crypto 捐赠订单的 UPAY 信息"""
        try:
            with get_session() as session:
                updated_at = datetime.now(settings.TZ).isoformat()

                session.execute(
                    update(CryptoDonationOrders)
                    .where(CryptoDonationOrders.order_id == order_id)
                    .values(
                        trade_id=trade_id,
                        actual_amount=actual_amount,
                        payment_address=payment_address,
                        payment_url=payment_url,
                        expiration_time=expiration_time,
                        updated_at=updated_at,
                    )
                )
                return True
        except Exception as e:
            logger.error(f"更新 crypto 捐赠订单 UPAY 信息失败: {e}")
            return False

    def complete_crypto_donation_order(
        self,
        trade_id: str,
        block_transaction_id: str,
        actual_amount: float,
    ) -> bool:
        """完成 crypto 捐赠订单支付"""
        try:
            with get_session() as session:
                paid_at = datetime.now(settings.TZ).isoformat()
                updated_at = paid_at

                session.execute(
                    update(CryptoDonationOrders)
                    .where(CryptoDonationOrders.trade_id == trade_id)
                    .values(
                        status=2,
                        block_transaction_id=block_transaction_id,
                        actual_amount=actual_amount,
                        paid_at=paid_at,
                        updated_at=updated_at,
                    )
                )
                return True
        except Exception as e:
            logger.error(f"完成 crypto 捐赠订单支付失败: {e}")
            return False

    def get_crypto_donation_order_by_order_id(self, order_id: str) -> Optional[dict]:
        """根据订单ID获取 crypto 捐赠订单"""
        try:
            with get_session() as session:
                stmt = select(CryptoDonationOrders).where(
                    CryptoDonationOrders.order_id == order_id
                )
                result = session.execute(stmt).scalar_one_or_none()

                if result:
                    return {
                        "id": result.id,
                        "user_id": result.user_id,
                        "order_id": result.order_id,
                        "trade_id": result.trade_id,
                        "crypto_type": result.crypto_type,
                        "amount": result.amount,
                        "actual_amount": result.actual_amount,
                        "payment_address": result.payment_address,
                        "block_transaction_id": result.block_transaction_id,
                        "status": result.status,
                        "payment_url": result.payment_url,
                        "expiration_time": result.expiration_time,
                        "created_at": result.created_at,
                        "updated_at": result.updated_at,
                        "paid_at": result.paid_at,
                        "note": result.note,
                    }
                return None
        except Exception as e:
            logger.error(f"获取 crypto 捐赠订单失败: {e}")
            return None

    def get_crypto_donation_order_by_trade_id(self, trade_id: str) -> Optional[dict]:
        """根据交易ID获取 crypto 捐赠订单"""
        try:
            with get_session() as session:
                stmt = select(CryptoDonationOrders).where(
                    CryptoDonationOrders.trade_id == trade_id
                )
                result = session.execute(stmt).scalar_one_or_none()

                if result:
                    return {
                        "id": result.id,
                        "user_id": result.user_id,
                        "order_id": result.order_id,
                        "trade_id": result.trade_id,
                        "crypto_type": result.crypto_type,
                        "amount": result.amount,
                        "actual_amount": result.actual_amount,
                        "payment_address": result.payment_address,
                        "block_transaction_id": result.block_transaction_id,
                        "status": result.status,
                        "payment_url": result.payment_url,
                        "expiration_time": result.expiration_time,
                        "created_at": result.created_at,
                        "updated_at": result.updated_at,
                        "paid_at": result.paid_at,
                        "note": result.note,
                    }
                return None
        except Exception as e:
            logger.error(f"获取 crypto 捐赠订单失败: {e}")
            return None

    def get_crypto_donation_orders_by_user(
        self, user_id: int, limit: int = 20
    ) -> List[dict]:
        """获取用户的 crypto 捐赠订单历史"""
        try:
            with get_session() as session:
                stmt = (
                    select(CryptoDonationOrders)
                    .where(CryptoDonationOrders.user_id == user_id)
                    .order_by(CryptoDonationOrders.created_at.desc())
                    .limit(limit)
                )
                results = session.execute(stmt).scalars().all()

                orders = []
                for result in results:
                    orders.append(
                        {
                            "id": result.id,
                            "user_id": result.user_id,
                            "order_id": result.order_id,
                            "trade_id": result.trade_id,
                            "crypto_type": result.crypto_type,
                            "amount": result.amount,
                            "actual_amount": result.actual_amount,
                            "payment_address": result.payment_address,
                            "block_transaction_id": result.block_transaction_id,
                            "status": result.status,
                            "payment_url": result.payment_url,
                            "expiration_time": result.expiration_time,
                            "created_at": result.created_at,
                            "updated_at": result.updated_at,
                            "paid_at": result.paid_at,
                            "note": result.note,
                        }
                    )
                return orders
        except Exception as e:
            logger.error(f"获取用户 crypto 捐赠订单历史失败: {e}")
            return []

    def get_all_crypto_donation_orders(
        self, limit: int = 100, offset: int = 0, status_filter: str = None
    ) -> List[dict]:
        """获取所有 crypto 捐赠订单历史（管理员用）"""
        try:
            with get_session() as session:
                # 构建查询
                stmt = select(CryptoDonationOrders)

                # 添加状态过滤
                if status_filter and status_filter in ["0", "1", "2", "3"]:
                    stmt = stmt.where(CryptoDonationOrders.status == int(status_filter))

                # 排序和分页
                stmt = (
                    stmt.order_by(CryptoDonationOrders.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )

                results = session.execute(stmt).scalars().all()

                orders = []
                for result in results:
                    orders.append(
                        {
                            "id": result.id,
                            "user_id": result.user_id,
                            "order_id": result.order_id,
                            "trade_id": result.trade_id,
                            "crypto_type": result.crypto_type,
                            "amount": result.amount,
                            "actual_amount": result.actual_amount,
                            "payment_address": result.payment_address,
                            "block_transaction_id": result.block_transaction_id,
                            "status": result.status,
                            "payment_url": result.payment_url,
                            "expiration_time": result.expiration_time,
                            "created_at": result.created_at,
                            "updated_at": result.updated_at,
                            "paid_at": result.paid_at,
                            "note": result.note,
                        }
                    )
                return orders
        except Exception as e:
            logger.error(f"获取所有 crypto 捐赠订单历史失败: {e}")
            return []

    def get_crypto_donation_orders_count(self, status_filter: str = None) -> int:
        """获取 crypto 捐赠订单总数（管理员用）"""
        try:
            with get_session() as session:
                # 构建查询
                stmt = select(func.count(CryptoDonationOrders.id))

                # 添加状态过滤
                if status_filter and status_filter in ["0", "1", "2", "3"]:
                    stmt = stmt.where(CryptoDonationOrders.status == int(status_filter))

                result = session.execute(stmt).scalar()
                return result if result else 0
        except Exception as e:
            logger.error(f"获取 crypto 捐赠订单总数失败: {e}")
            return 0

    def get_expired_crypto_donation_orders(self) -> List[dict]:
        """获取所有已过期但状态仍为等待支付的 crypto 捐赠订单"""
        try:
            with get_session() as session:
                current_time = int(time.time() * 1000)  # 当前时间的毫秒时间戳

                stmt = (
                    select(CryptoDonationOrders)
                    .where(
                        CryptoDonationOrders.status == 1,
                        CryptoDonationOrders.expiration_time.isnot(None),
                        CryptoDonationOrders.expiration_time <= current_time,
                    )
                    .order_by(CryptoDonationOrders.created_at.asc())
                )
                results = session.execute(stmt).scalars().all()

                expired_orders = []
                for result in results:
                    expired_orders.append(
                        {
                            "id": result.id,
                            "user_id": result.user_id,
                            "order_id": result.order_id,
                            "trade_id": result.trade_id,
                            "crypto_type": result.crypto_type,
                            "amount": result.amount,
                            "actual_amount": result.actual_amount,
                            "payment_address": result.payment_address,
                            "block_transaction_id": result.block_transaction_id,
                            "status": result.status,
                            "payment_url": result.payment_url,
                            "expiration_time": result.expiration_time,
                            "created_at": result.created_at,
                            "updated_at": result.updated_at,
                            "paid_at": result.paid_at,
                            "note": result.note,
                        }
                    )
                return expired_orders
        except Exception as e:
            logger.error(f"获取过期 crypto 捐赠订单失败: {e}")
            return []

    def update_expired_crypto_donation_orders(self) -> int:
        """批量更新已过期的 crypto 捐赠订单状态为已过期(3)"""
        try:
            with get_session() as session:
                current_time = int(time.time() * 1000)  # 当前时间的毫秒时间戳
                updated_at = datetime.now(settings.TZ).isoformat()

                # 更新所有过期的订单状态
                result = session.execute(
                    update(CryptoDonationOrders)
                    .where(
                        CryptoDonationOrders.status == 1,
                        CryptoDonationOrders.expiration_time.isnot(None),
                        CryptoDonationOrders.expiration_time <= current_time,
                    )
                    .values(status=3, updated_at=updated_at)
                )
                updated_count = result.rowcount

                if updated_count > 0:
                    logger.info(
                        f"成功更新 {updated_count} 个过期的 crypto 捐赠订单状态"
                    )

                return updated_count
        except Exception as e:
            logger.error(f"更新过期 crypto 捐赠订单状态失败: {e}")
            return 0

    # ============================================================
    # SystemConfig 配置管理相关方法
    # ============================================================

    def get_system_config(self, config_type: str, config_key: str) -> Optional[str]:
        """
        获取系统配置

        Args:
            config_type: 配置类型 (free_premium_line, line_tag, lucky_wheel)
            config_key: 配置键

        Returns:
            配置值，如果不存在返回 None
        """
        try:
            with get_session() as session:
                stmt = select(SystemConfig.config_value).where(
                    SystemConfig.config_type == config_type,
                    SystemConfig.config_key == config_key,
                )
                result = session.execute(stmt).scalar_one_or_none()
                return result
        except Exception as e:
            logger.error(
                f"获取系统配置失败 (type={config_type}, key={config_key}): {str(e)}"
            )
            return None

    def set_system_config(
        self, config_type: str, config_key: str, config_value: str
    ) -> bool:
        """
        设置系统配置（更新或插入）

        Args:
            config_type: 配置类型
            config_key: 配置键
            config_value: 配置值

        Returns:
            是否成功
        """
        try:
            current_time = int(time.time())
            with get_session() as session:
                # 尝试查找现有配置
                stmt = select(SystemConfig).where(
                    SystemConfig.config_type == config_type,
                    SystemConfig.config_key == config_key,
                )
                existing_config = session.execute(stmt).scalar_one_or_none()

                if existing_config:
                    # 更新现有配置
                    existing_config.config_value = config_value
                    existing_config.updated_at = current_time
                else:
                    # 插入新配置
                    new_config = SystemConfig(
                        config_type=config_type,
                        config_key=config_key,
                        config_value=config_value,
                        created_at=current_time,
                        updated_at=current_time,
                    )
                    session.add(new_config)

                logger.info(f"设置系统配置成功 (type={config_type}, key={config_key})")
                return True
        except Exception as e:
            logger.error(
                f"设置系统配置失败 (type={config_type}, key={config_key}): {str(e)}"
            )
            return False

    def delete_system_config(self, config_type: str, config_key: str) -> bool:
        """
        删除系统配置

        Args:
            config_type: 配置类型
            config_key: 配置键

        Returns:
            是否成功
        """
        try:
            with get_session() as session:
                stmt = select(SystemConfig).where(
                    SystemConfig.config_type == config_type,
                    SystemConfig.config_key == config_key,
                )
                config = session.execute(stmt).scalar_one_or_none()

                if config:
                    session.delete(config)
                    logger.info(
                        f"删除系统配置成功 (type={config_type}, key={config_key})"
                    )
                    return True
                else:
                    logger.info(
                        f"系统配置不存在 (type={config_type}, key={config_key})"
                    )
                    return True
        except Exception as e:
            logger.error(
                f"删除系统配置失败 (type={config_type}, key={config_key}): {str(e)}"
            )
            return False

    def get_all_configs_by_type(self, config_type: str) -> dict:
        """
        获取指定类型的所有配置

        Args:
            config_type: 配置类型

        Returns:
            配置字典 {config_key: config_value}
        """
        try:
            with get_session() as session:
                stmt = select(SystemConfig.config_key, SystemConfig.config_value).where(
                    SystemConfig.config_type == config_type
                )
                results = session.execute(stmt).all()
                return {row[0]: row[1] for row in results}
        except Exception as e:
            logger.error(f"获取所有配置失败 (type={config_type}): {str(e)}")
            return {}

    # ============================================================
    # 免费高级线路相关方法
    # ============================================================

    def get_free_premium_lines(self) -> list[str]:
        """获取所有免费高级线路列表"""
        configs = self.get_all_configs_by_type("free_premium_line")
        return [key for key, value in configs.items() if value == "1"]

    def set_free_premium_lines(self, lines: list[str]) -> bool:
        """
        设置免费高级线路列表

        Args:
            lines: 线路名称列表

        Returns:
            是否成功
        """
        try:
            # 获取现有的免费线路
            existing_lines = set(self.get_free_premium_lines())
            new_lines = set(lines)

            # 删除不再免费的线路
            for line in existing_lines - new_lines:
                self.delete_system_config("free_premium_line", line)

            # 添加新的免费线路
            for line in new_lines:
                self.set_system_config("free_premium_line", line, "1")

            logger.info(f"设置免费高级线路成功，共 {len(lines)} 条线路")
            return True
        except Exception as e:
            logger.error(f"设置免费高级线路失败: {str(e)}")
            return False

    def is_free_premium_line(self, line_name: str) -> bool:
        """检查线路是否为免费高级线路"""
        value = self.get_system_config("free_premium_line", line_name)
        return value == "1"

    # ============================================================
    # 线路标签相关方法
    # ============================================================

    def get_line_tags(self, line_name: str) -> list[str]:
        """
        获取线路的标签列表

        Args:
            line_name: 线路名称

        Returns:
            标签列表
        """
        tags_str = self.get_system_config("line_tag", line_name)
        if tags_str:
            tags = tags_str.split(",")
            return [tag.strip() for tag in tags if tag.strip()]
        return []

    def set_line_tags(self, line_name: str, tags: list[str]) -> bool:
        """
        设置线路标签

        Args:
            line_name: 线路名称
            tags: 标签列表

        Returns:
            是否成功
        """
        if not tags:
            # 如果标签为空，删除该配置
            return self.delete_system_config("line_tag", line_name)

        # 去重并转换为逗号分隔的字符串
        tags_str = ",".join(set(tags))
        return self.set_system_config("line_tag", line_name, tags_str)

    def delete_line_tags(self, line_name: str) -> bool:
        """删除线路的所有标签"""
        return self.delete_system_config("line_tag", line_name)

    def get_all_line_tags(self) -> dict:
        """
        获取所有线路的标签

        Returns:
            字典 {line_name: [tags]}
        """
        configs = self.get_all_configs_by_type("line_tag")
        result = {}
        for line_name, tags_str in configs.items():
            tags = tags_str.split(",")
            result[line_name] = [tag.strip() for tag in tags if tag.strip()]
        return result

    # ============================================================
    # 幸运大转盘配置相关方法
    # ============================================================

    def get_lucky_wheel_config(self, config_key: str = "config") -> Optional[str]:
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

    # ============================================================
    # 21 点配置相关方法
    # ============================================================

    def get_blackjack_config(self, config_key: str = "config") -> Optional[str]:
        """
        获取 21 点配置

        Args:
            config_key: 配置键 (config)

        Returns:
            配置的 JSON 字符串
        """
        return self.get_system_config("blackjack", config_key)

    def set_blackjack_config(self, config_key: str, config_json: str) -> bool:
        """
        设置 21 点配置

        Args:
            config_key: 配置键 (config)
            config_json: 配置的 JSON 字符串

        Returns:
            是否成功
        """
        return self.set_system_config("blackjack", config_key, config_json)

    def get_blackjack_config_dict(self) -> dict:
        """
        获取 21 点配置字典，缺失项以默认值补全；首次读取时把默认配置落库。

        每手牌在发牌时会把其中的关键参数快照到手牌行上，结算读快照而非读本方法，
        故管理员改配置不影响进行中的手牌。
        """
        raw = self.get_blackjack_config("config")
        config = dict(DEFAULT_BLACKJACK_CONFIG)
        if raw:
            try:
                stored = json.loads(raw)
                if isinstance(stored, dict):
                    config.update(stored)
            except Exception as e:
                logger.error(f"解析 21 点配置失败，回退默认配置: {e}")
        else:
            # 首次读取时落库，便于管理员在面板上看到完整的初始配置
            self.set_blackjack_config("config", json.dumps(config, ensure_ascii=False))
        return config

    # ============================================================
    # 线路调度功能相关方法
    # ============================================================

    def check_line_schedule_unlock(self, tg_id: int, service: str) -> dict:
        """
        检查用户是否解锁了指定服务的线路调度功能

        Args:
            tg_id: 用户的 Telegram ID
            service: 服务类型 (plex/emby)

        Returns:
            dict: {
                'is_unlocked': bool,  # 是否已解锁（包括 premium 自动解锁）
                'is_premium': bool,   # 是否为 premium 用户
                'unlock_time': int,   # 解锁时间戳
            }
        """
        from app.utils.utils import get_user_name_from_tg_id

        try:
            with get_session() as session:
                is_premium = False
                unlock_time = None

                if service == "plex":
                    # 检查 Plex 用户状态
                    stmt = select(
                        PlexUser.is_premium,
                        PlexUser.premium_expiry_time,
                        PlexUser.line_schedule_unlocked,
                        PlexUser.line_schedule_unlock_time,
                    ).where(PlexUser.tg_id == tg_id)
                    result = session.execute(stmt).fetchone()

                    if result:
                        # 检查 premium 状态
                        if result[0] == 1:
                            # premium_expiry_time 为空表示永久 premium
                            if not result[1]:
                                is_premium = True
                            else:
                                # 有过期时间，检查是否过期
                                expiry = datetime.fromisoformat(result[1])
                                if expiry > datetime.now(settings.TZ):
                                    is_premium = True

                        # 检查解锁状态
                        if result[2] == 1:
                            unlock_time = result[3]

                elif service == "emby":
                    # 检查 Emby 用户状态
                    stmt = select(
                        EmbyUser.is_premium,
                        EmbyUser.premium_expiry_time,
                        EmbyUser.line_schedule_unlocked,
                        EmbyUser.line_schedule_unlock_time,
                    ).where(EmbyUser.tg_id == tg_id)
                    result = session.execute(stmt).fetchone()

                    if result:
                        # 检查 premium 状态
                        if result[0] == 1:
                            # premium_expiry_time 为空表示永久 premium
                            if not result[1]:
                                is_premium = True
                            else:
                                # 有过期时间，检查是否过期
                                expiry = datetime.fromisoformat(result[1])
                                if expiry > datetime.now(settings.TZ):
                                    is_premium = True

                        # 检查解锁状态
                        if result[2] == 1:
                            unlock_time = result[3]

                # Premium 用户或已解锁用户都算已解锁
                is_unlocked = is_premium or (unlock_time is not None)

                return {
                    "is_unlocked": is_unlocked,
                    "is_premium": is_premium,
                    "unlock_time": unlock_time,
                }

        except Exception as e:
            logger.error(
                f"检查用户 {get_user_name_from_tg_id(tg_id)} 的 {service} 线路调度解锁状态失败: {e}"
            )
            return {"is_unlocked": False, "is_premium": False, "unlock_time": None}

    def unlock_line_schedule(self, tg_id: int, service: str) -> bool:
        """
        解锁用户的线路调度功能

        Args:
            tg_id: 用户的 Telegram ID
            service: 服务类型 (plex/emby)

        Returns:
            是否成功
        """
        from app.utils.utils import get_user_name_from_tg_id

        try:
            with get_session() as session:
                unlock_time = int(time.time())

                if service == "plex":
                    stmt = (
                        update(PlexUser)
                        .where(PlexUser.tg_id == tg_id)
                        .values(
                            line_schedule_unlocked=1,
                            line_schedule_unlock_time=unlock_time,
                        )
                    )
                elif service == "emby":
                    stmt = (
                        update(EmbyUser)
                        .where(EmbyUser.tg_id == tg_id)
                        .values(
                            line_schedule_unlocked=1,
                            line_schedule_unlock_time=unlock_time,
                        )
                    )
                else:
                    logger.error(f"未知的服务类型: {service}")
                    return False

                session.execute(stmt)
                logger.info(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 解锁 {service} 线路调度功能"
                )
                return True

        except Exception as e:
            logger.error(f"解锁 {service} 线路调度功能失败: {e}")
            return False

    def create_line_schedule(
        self,
        tg_id: int,
        service: str,
        line: str,
        days_of_week: List[int],
        start_time: str,
        end_time: str,
        priority: int = 0,
    ) -> Optional[int]:
        """
        创建线路调度

        Args:
            tg_id: 用户的 Telegram ID
            service: 服务类型 (plex/emby)
            line: 线路名称
            days_of_week: 星期几列表 [0-6]
            start_time: 开始时间 HH:MM
            end_time: 结束时间 HH:MM
            priority: 优先级

        Returns:
            创建的调度 ID，失败返回 None
        """
        from app.utils.utils import get_user_name_from_tg_id

        try:
            with get_session() as session:
                schedule = LineSchedule(
                    tg_id=tg_id,
                    service=service,
                    line=line,
                    days_of_week=",".join(map(str, sorted(days_of_week)))
                    if days_of_week
                    else "",
                    start_time=start_time,
                    end_time=end_time,
                    priority=priority,
                    is_enabled=1,
                    created_at=int(time.time()),
                    updated_at=int(time.time()),
                )
                session.add(schedule)
                session.flush()  # 获取 schedule.id

                logger.info(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 创建 {service} 线路调度: {line} "
                    f"({days_of_week}, {start_time}-{end_time})"
                )
                return schedule.id

        except Exception as e:
            logger.error(f"创建线路调度失败: {e}")
            return None

    def get_user_line_schedules(
        self,
        tg_id: int,
        service: Optional[str] = None,
        enabled_only: bool = False,
    ) -> List[dict]:
        """
        获取用户的线路调度列表

        Args:
            tg_id: 用户的 Telegram ID
            service: 服务类型，None 表示获取所有
            enabled_only: 是否只获取启用的调度

        Returns:
            调度列表
        """
        try:
            with get_session() as session:
                stmt = select(LineSchedule).where(LineSchedule.tg_id == tg_id)

                if service:
                    stmt = stmt.where(LineSchedule.service == service)

                if enabled_only:
                    stmt = stmt.where(LineSchedule.is_enabled == 1)

                stmt = stmt.order_by(LineSchedule.priority, LineSchedule.created_at)

                schedules = session.execute(stmt).scalars().all()

                return [
                    {
                        "id": s.id,
                        "service": s.service,
                        "line": s.line,
                        "days_of_week": [int(d) for d in s.days_of_week.split(",")]
                        if s.days_of_week
                        else [],
                        "start_time": s.start_time,
                        "end_time": s.end_time,
                        "priority": s.priority,
                        "is_enabled": s.is_enabled == 1,
                        "created_at": s.created_at,
                        "updated_at": s.updated_at,
                    }
                    for s in schedules
                ]

        except Exception as e:
            logger.error(f"获取用户 {tg_id} 的线路调度列表失败: {e}")
            return []

    def update_line_schedule(self, schedule_id: int, tg_id: int, **kwargs) -> bool:
        """
        更新线路调度

        Args:
            schedule_id: 调度 ID
            tg_id: 用户的 Telegram ID (用于验证权限)
            **kwargs: 要更新的字段

        Returns:
            是否成功
        """
        from app.utils.utils import get_user_name_from_tg_id

        try:
            with get_session() as session:
                schedule = session.execute(
                    select(LineSchedule).where(
                        LineSchedule.id == schedule_id, LineSchedule.tg_id == tg_id
                    )
                ).scalar_one_or_none()

                if not schedule:
                    logger.warning(f"线路调度 {schedule_id} 不存在或无权限")
                    return False

                # 更新字段
                if "line" in kwargs:
                    schedule.line = kwargs["line"]
                if "days_of_week" in kwargs:
                    schedule.days_of_week = ",".join(
                        map(str, sorted(kwargs["days_of_week"]))
                    )
                if "start_time" in kwargs:
                    schedule.start_time = kwargs["start_time"]
                if "end_time" in kwargs:
                    schedule.end_time = kwargs["end_time"]
                if "priority" in kwargs:
                    schedule.priority = kwargs["priority"]
                if "is_enabled" in kwargs:
                    schedule.is_enabled = 1 if kwargs["is_enabled"] else 0

                schedule.updated_at = int(time.time())
                logger.info(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 更新线路调度 {schedule_id}"
                )
                return True

        except Exception as e:
            logger.error(f"更新线路调度 {schedule_id} 失败: {e}")
            return False

    def delete_line_schedule(self, schedule_id: int, tg_id: int) -> bool:
        """
        删除线路调度

        Args:
            schedule_id: 调度 ID
            tg_id: 用户的 Telegram ID (用于验证权限)

        Returns:
            是否成功
        """
        from app.utils.utils import get_user_name_from_tg_id

        try:
            with get_session() as session:
                # 先查询以获取调度信息
                schedule = session.execute(
                    select(LineSchedule).where(
                        LineSchedule.id == schedule_id, LineSchedule.tg_id == tg_id
                    )
                ).scalar_one_or_none()

                if not schedule:
                    logger.warning(f"线路调度 {schedule_id} 不存在或无权限")
                    return False

                # 删除调度
                session.delete(schedule)
                logger.info(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 删除线路调度 {schedule_id}"
                )
                return True

        except Exception as e:
            logger.error(f"删除线路调度 {schedule_id} 失败: {e}")
            return False

    def check_schedule_conflict(
        self,
        tg_id: int,
        service: str,
        days_of_week: List[int],
        start_time: str,
        end_time: str,
        exclude_id: Optional[int] = None,
    ) -> bool:
        """
        检查时间段是否冲突

        Args:
            tg_id: 用户的 Telegram ID
            service: 服务类型
            days_of_week: 星期几列表
            start_time: 开始时间 HH:MM
            end_time: 结束时间 HH:MM
            exclude_id: 要排除的调度 ID（用于更新时）

        Returns:
            是否存在冲突
        """
        try:
            schedules = self.get_user_line_schedules(tg_id, service, enabled_only=True)

            # 转换时间为分钟数便于比较
            def time_to_minutes(t: str) -> int:
                h, m = map(int, t.split(":"))
                return h * 60 + m

            new_start = time_to_minutes(start_time)
            new_end = time_to_minutes(end_time)

            # 处理跨天的情况
            if new_end <= new_start:
                new_end += 24 * 60

            new_days_set = set(days_of_week)

            for schedule in schedules:
                # 排除指定的调度
                if exclude_id and schedule["id"] == exclude_id:
                    continue

                # 检查星期几是否有交集
                schedule_days_set = set(schedule["days_of_week"])
                if not new_days_set & schedule_days_set:
                    continue

                # 检查时间段是否重叠
                sched_start = time_to_minutes(schedule["start_time"])
                sched_end = time_to_minutes(schedule["end_time"])

                # 处理跨天
                if sched_end <= sched_start:
                    sched_end += 24 * 60

                # 检查是否重叠
                if not (new_end <= sched_start or new_start >= sched_end):
                    logger.info(
                        f"发现时间冲突: 新调度 {start_time}-{end_time} 与 "
                        f"调度 {schedule['id']} {schedule['start_time']}-{schedule['end_time']} 冲突"
                    )
                    return True

            return False

        except Exception as e:
            logger.error(f"检查时间冲突失败: {e}")
            return True  # 出错时保守处理，返回冲突

    def get_current_active_schedule(self, tg_id: int, service: str) -> Optional[dict]:
        """
        获取当前生效的线路调度

        Args:
            tg_id: 用户的 Telegram ID
            service: 服务类型

        Returns:
            当前生效的调度，没有返回 None
        """
        try:
            now = datetime.now(settings.TZ)
            current_day = now.weekday()  # 0=Monday, 6=Sunday
            current_time = now.strftime("%H:%M")

            def time_to_minutes(t: str) -> int:
                h, m = map(int, t.split(":"))
                return h * 60 + m

            current_minutes = time_to_minutes(current_time)

            schedules = self.get_user_line_schedules(tg_id, service, enabled_only=True)

            # 按优先级排序
            schedules.sort(key=lambda x: x["priority"])

            for schedule in schedules:
                # 检查星期几
                if current_day not in schedule["days_of_week"]:
                    continue

                # 检查时间段
                start_minutes = time_to_minutes(schedule["start_time"])
                end_minutes = time_to_minutes(schedule["end_time"])

                # 处理跨天情况
                if end_minutes <= start_minutes:
                    # 跨天时间段
                    if (
                        current_minutes >= start_minutes
                        or current_minutes < end_minutes
                    ):
                        return schedule
                else:
                    # 同一天时间段
                    if start_minutes <= current_minutes < end_minutes:
                        return schedule

            return None

        except Exception as e:
            logger.error(f"获取当前生效的调度失败: {e}")
            return None

    def disable_schedules_by_line(
        self, line_name: str, only_non_premium: bool = False
    ) -> tuple[bool, int, List[dict]]:
        """
        禁用指定线路的所有调度，并返回受影响的用户信息

        Args:
            line_name: 线路名称
            only_non_premium: 是否只禁用非 premium 用户的调度

        Returns:
            (是否成功, 禁用的调度数量, 受影响的用户列表)
            用户列表格式: [{"tg_id": int, "service": str, "schedule_count": int}, ...]
        """
        try:
            with get_session() as session:
                # 查找所有使用该线路且已启用的调度
                stmt = select(LineSchedule).where(
                    LineSchedule.line == line_name, LineSchedule.is_enabled == 1
                )
                schedules = session.execute(stmt).scalars().all()

                if not schedules:
                    logger.info(f"没有找到使用线路 {line_name} 的已启用调度")
                    return True, 0, []

                # 如果需要过滤 premium 用户，先查询用户的 premium 状态
                premium_users = set()
                if only_non_premium:
                    # 获取所有相关用户的 tg_id
                    tg_ids = list(set(schedule.tg_id for schedule in schedules))

                    # 查询 Plex 用户的 premium 状态
                    plex_stmt = select(PlexUser.tg_id).where(
                        PlexUser.tg_id.in_(tg_ids), PlexUser.is_premium == 1
                    )
                    plex_premium = session.execute(plex_stmt).scalars().all()
                    premium_users.update(plex_premium)

                    # 查询 Emby 用户的 premium 状态
                    emby_stmt = select(EmbyUser.tg_id).where(
                        EmbyUser.tg_id.in_(tg_ids), EmbyUser.is_premium == 1
                    )
                    emby_premium = session.execute(emby_stmt).scalars().all()
                    premium_users.update(emby_premium)

                # 统计受影响的用户（在禁用前）
                user_service_map = {}
                schedules_to_disable = []
                for schedule in schedules:
                    # 如果只禁用非 premium 用户，跳过 premium 用户
                    if only_non_premium and schedule.tg_id in premium_users:
                        continue

                    schedules_to_disable.append(schedule)
                    key = (schedule.tg_id, schedule.service)
                    if key not in user_service_map:
                        user_service_map[key] = {
                            "tg_id": schedule.tg_id,
                            "service": schedule.service,
                            "schedule_count": 0,
                        }
                    user_service_map[key]["schedule_count"] += 1

                if not schedules_to_disable:
                    logger.info(f"没有需要禁用的调度（线路: {line_name}）")
                    return True, 0, []

                # 禁用所有调度
                count = 0
                current_time = int(time.time())
                for schedule in schedules_to_disable:
                    schedule.is_enabled = 0
                    schedule.updated_at = current_time
                    count += 1

                affected_users = list(user_service_map.values())
                logger.info(
                    f"已禁用 {count} 个使用线路 {line_name} 的调度，"
                    f"影响 {len(affected_users)} 位用户"
                    + (" (仅非 premium 用户)" if only_non_premium else "")
                )
                return True, count, affected_users

        except Exception as e:
            logger.error(f"禁用线路 {line_name} 的调度失败: {e}")
            return False, 0, []

    def get_users_with_line_schedule(self, line_name: str) -> List[dict]:
        """
        获取所有使用指定线路调度的用户信息

        Args:
            line_name: 线路名称

        Returns:
            用户信息列表 [{"tg_id": int, "service": str, "schedule_count": int}, ...]
        """
        try:
            with get_session() as session:
                # 查找所有使用该线路且已启用的调度
                stmt = select(LineSchedule).where(
                    LineSchedule.line == line_name, LineSchedule.is_enabled == 1
                )
                schedules = session.execute(stmt).scalars().all()

                # 按用户和服务分组统计
                user_service_map = {}
                for schedule in schedules:
                    key = (schedule.tg_id, schedule.service)
                    if key not in user_service_map:
                        user_service_map[key] = {
                            "tg_id": schedule.tg_id,
                            "service": schedule.service,
                            "schedule_count": 0,
                        }
                    user_service_map[key]["schedule_count"] += 1

                return list(user_service_map.values())

        except Exception as e:
            logger.error(f"获取使用线路 {line_name} 的用户失败: {e}")
            return []

    # ==================== Badge Management ====================

    @staticmethod
    def _badge_to_dict(badge: Badge) -> dict:
        """将 Badge ORM 对象转换为字典"""
        return {
            "id": badge.id,
            "badge_type": badge.badge_type,
            "name": badge.name,
            "description": badge.description,
            "icon_url": badge.icon_url,
            "credits_cost": badge.credits_cost,
            "bonus_percentage": badge.bonus_percentage,
            "valid_days": badge.valid_days,
            "is_enabled": badge.is_enabled,
            "created_at": badge.created_at,
            "updated_at": badge.updated_at,
        }

    @staticmethod
    def _user_badge_to_dict(user_badge: UserBadge, include_badge: bool = True) -> dict:
        """将 UserBadge ORM 对象转换为字典"""
        current_time = int(time.time())
        bonus_active = user_badge.expires_at > current_time

        result = {
            "id": user_badge.id,
            "tg_id": user_badge.tg_id,
            "badge_id": user_badge.badge_id,
            "credits_cost": user_badge.credits_cost,
            "redeemed_at": user_badge.redeemed_at,
            "expires_at": user_badge.expires_at,
            "is_active": user_badge.is_active,
            "bonus_active": bonus_active,  # 积分加成是否有效
            "badge": None,
        }

        if include_badge and user_badge.badge:
            result["badge"] = DatabaseORM._badge_to_dict(user_badge.badge)

        return result

    def get_badge_center_config(self) -> Tuple[bool, Optional[str]]:
        """
        获取勋章中心配置

        Returns:
            (是否启用, 提示信息)
        """
        enabled_str = self.get_system_config("badge_center", "enabled")
        enabled = enabled_str == "1" if enabled_str else False
        message = self.get_system_config("badge_center", "message")
        return enabled, message

    def set_badge_center_config(
        self, enabled: bool, message: Optional[str] = None
    ) -> bool:
        """
        设置勋章中心配置

        Args:
            enabled: 是否启用
            message: 提示信息

        Returns:
            是否成功
        """
        try:
            self.set_system_config("badge_center", "enabled", "1" if enabled else "0")
            if message is not None:
                self.set_system_config("badge_center", "message", message)
            return True
        except Exception as e:
            logger.error(f"设置勋章中心配置失败: {e}")
            return False

    def create_badge(
        self,
        badge_type: str,
        name: str,
        description: str,
        icon_url: str,
        credits_cost: float,
        bonus_percentage: float,
        valid_days: int = 365,
        is_enabled: int = 1,
    ) -> Optional[dict]:
        """
        创建勋章

        Returns:
            Badge字典或None
        """
        try:
            with get_session() as session:
                current_time = int(time.time())
                badge = Badge(
                    badge_type=badge_type,
                    name=name,
                    description=description,
                    icon_url=icon_url,
                    credits_cost=credits_cost,
                    bonus_percentage=bonus_percentage,
                    valid_days=valid_days,
                    is_enabled=is_enabled,
                    created_at=current_time,
                    updated_at=current_time,
                )
                session.add(badge)
                session.flush()  # 刷新以获取 badge 的 ID
                logger.info(f"创建勋章成功: {badge_type}")

                # 转换为字典返回
                return self._badge_to_dict(badge)
        except Exception as e:
            logger.error(f"创建勋章失败: {e}")
            return None

    def get_badge_by_id(self, badge_id: int) -> Optional[dict]:
        """根据ID获取勋章"""
        try:
            with get_session() as session:
                stmt = select(Badge).where(Badge.id == badge_id)
                badge = session.execute(stmt).scalar_one_or_none()

                if not badge:
                    return None

                return self._badge_to_dict(badge)
        except Exception as e:
            logger.error(f"获取勋章失败: {e}")
            return None

    def get_badge_by_type(self, badge_type: str) -> Optional[dict]:
        """根据类型获取勋章"""
        try:
            with get_session() as session:
                stmt = select(Badge).where(Badge.badge_type == badge_type)
                badge = session.execute(stmt).scalar_one_or_none()

                if not badge:
                    return None

                return self._badge_to_dict(badge)
        except Exception as e:
            logger.error(f"获取勋章失败: {e}")
            return None

    def get_all_badges(self, only_enabled: bool = False) -> List[dict]:
        """
        获取所有勋章

        Args:
            only_enabled: 是否只获取启用的勋章

        Returns:
            勋章字典列表
        """
        try:
            with get_session() as session:
                stmt = select(Badge)
                if only_enabled:
                    stmt = stmt.where(Badge.is_enabled == 1)
                stmt = stmt.order_by(Badge.created_at.desc())
                badges = session.execute(stmt).scalars().all()

                return [self._badge_to_dict(badge) for badge in badges]
        except Exception as e:
            logger.error(f"获取勋章列表失败: {e}")
            return []

    def update_badge(
        self,
        badge_id: int,
        **kwargs,
    ) -> bool:
        """
        更新勋章信息

        Args:
            badge_id: 勋章ID
            **kwargs: 要更新的字段

        Returns:
            是否成功
        """
        try:
            with get_session() as session:
                stmt = select(Badge).where(Badge.id == badge_id)
                badge = session.execute(stmt).scalar_one_or_none()
                if not badge:
                    logger.error(f"勋章不存在: {badge_id}")
                    return False

                for key, value in kwargs.items():
                    if hasattr(badge, key) and value is not None:
                        setattr(badge, key, value)

                badge.updated_at = int(time.time())
                logger.info(f"更新勋章成功: {badge_id}")
                return True
        except Exception as e:
            logger.error(f"更新勋章失败: {e}")
            return False

    def delete_badge(self, badge_id: int) -> bool:
        """
        删除勋章

        Args:
            badge_id: 勋章ID

        Returns:
            是否成功
        """
        try:
            with get_session() as session:
                stmt = delete(Badge).where(Badge.id == badge_id)
                result = session.execute(stmt)
                row_count = result.rowcount
                logger.info(f"删除勋章成功: {badge_id}, 影响行数: {row_count}")

            return row_count > 0
        except Exception as e:
            logger.error(f"删除勋章失败: {e}")
            return False

    def redeem_badge(
        self, tg_id: int, badge_id: int
    ) -> Tuple[bool, str, Optional[dict]]:
        """
        兑换勋章

        Args:
            tg_id: 用户TG ID
            badge_id: 勋章ID

        Returns:
            (是否成功, 消息, UserBadge字典或None)
        """
        try:
            with get_session() as session:
                # 1. 检查勋章是否存在且已启用
                badge = session.execute(
                    select(Badge).where(Badge.id == badge_id)
                ).scalar_one_or_none()
                if not badge:
                    return False, "勋章不存在", None
                if badge.is_enabled != 1:
                    return False, "该勋章暂不可兑换", None

                # 2. 检查用户是否已经拥有该勋章
                existing = session.execute(
                    select(UserBadge).where(
                        UserBadge.tg_id == tg_id, UserBadge.badge_id == badge_id
                    )
                ).scalar_one_or_none()
                if existing:
                    return False, "您已经拥有该勋章", None

                # 3. 检查用户积分是否足够
                stats = session.execute(
                    select(Statistics).where(Statistics.tg_id == tg_id)
                ).scalar_one_or_none()

                if not stats:
                    return False, "用户不存在", None

                if stats.credits < badge.credits_cost:
                    return False, f"积分不足，需要 {badge.credits_cost} 积分", None

                # 4. 扣除积分（在同一个事务中）
                new_credits = stats.credits - badge.credits_cost
                session.execute(
                    update(Statistics)
                    .where(Statistics.tg_id == tg_id)
                    .values(credits=new_credits)
                )

                # 5. 创建用户勋章记录
                current_time = int(time.time())
                expires_at = current_time + (badge.valid_days * 24 * 3600)
                user_badge = UserBadge(
                    tg_id=tg_id,
                    badge_id=badge_id,
                    credits_cost=badge.credits_cost,
                    redeemed_at=current_time,
                    expires_at=expires_at,
                    is_active=1,
                )
                session.add(user_badge)
                session.flush()  # 刷新以获取 user_badge 的 ID，但不提交

                # 手动设置 badge 关联以便转换
                user_badge.badge = badge

                # 转换为字典返回
                badge_info = self._user_badge_to_dict(user_badge, include_badge=True)

                logger.info(
                    f"用户 {tg_id} 兑换勋章 {badge.name} 成功，"
                    f"消耗积分 {badge.credits_cost}"
                )

            return True, "兑换成功", badge_info

        except Exception as e:
            logger.error(f"兑换勋章失败: {e}")
            logger.error(traceback.format_exc())
            return False, "兑换失败，请稍后重试", None

    def get_user_badges(self, tg_id: int, only_active: bool = True) -> List[dict]:
        """
        获取用户拥有的勋章

        Args:
            tg_id: 用户TG ID
            only_active: 是否只获取有效的勋章

        Returns:
            用户勋章字典列表
        """
        try:
            with get_session() as session:
                stmt = (
                    select(UserBadge)
                    .options(joinedload(UserBadge.badge))  # 急加载关联的勋章数据
                    .where(UserBadge.tg_id == tg_id)
                    .order_by(UserBadge.redeemed_at.desc())
                )
                if only_active:
                    stmt = stmt.where(UserBadge.is_active == 1)

                user_badges = session.execute(stmt).scalars().unique().all()

                return [self._user_badge_to_dict(ub) for ub in user_badges]
        except Exception as e:
            logger.error(f"获取用户勋章失败: {e}")
            return []

    def get_user_active_badges_with_bonus(self, tg_id: int) -> List[dict]:
        """
        获取用户当前有效的勋章及其加成信息

        Args:
            tg_id: 用户TG ID

        Returns:
            勋章信息列表 [{"badge": dict, "bonus_percentage": float, "expires_at": int}, ...]
        """
        try:
            current_time = int(time.time())
            with get_session() as session:
                stmt = (
                    select(UserBadge)
                    .where(
                        UserBadge.tg_id == tg_id,
                        UserBadge.is_active == 1,
                        UserBadge.expires_at > current_time,
                    )
                    .order_by(UserBadge.redeemed_at.desc())
                )
                user_badges = session.execute(stmt).scalars().all()

                result = []
                for ub in user_badges:
                    badge = session.execute(
                        select(Badge).where(Badge.id == ub.badge_id)
                    ).scalar_one_or_none()
                    if badge:
                        result.append(
                            {
                                "badge": self._badge_to_dict(badge),
                                "bonus_percentage": badge.bonus_percentage,
                                "expires_at": ub.expires_at,
                            }
                        )
                return result
        except Exception as e:
            logger.error(f"获取用户有效勋章失败: {e}")
            return []

    # ============================================================
    # 下载/同步权限解锁功能相关方法
    # ============================================================

    def check_download_unlock(self, tg_id: int, service: str) -> dict:
        """
        检查用户是否解锁了指定服务的下载/同步功能

        Args:
            tg_id: 用户的 Telegram ID
            service: 服务类型 (plex/emby)

        Returns:
            dict: {
                'is_unlocked': bool,  # 是否已解锁（包括 premium 自动解锁）
                'is_premium': bool,   # 是否为 premium 用户
                'unlock_time': int,   # 解锁时间戳
            }
        """
        from app.utils.utils import get_user_name_from_tg_id

        try:
            with get_session() as session:
                is_premium = False
                unlock_time = None

                if service == "plex":
                    # 检查 Plex 用户状态
                    stmt = select(
                        PlexUser.is_premium,
                        PlexUser.premium_expiry_time,
                        PlexUser.sync_unlocked,
                        PlexUser.sync_unlock_time,
                    ).where(PlexUser.tg_id == tg_id)
                    result = session.execute(stmt).fetchone()

                    if result:
                        # 检查 premium 状态
                        if result[0] == 1:
                            # premium_expiry_time 为空表示永久 premium
                            if not result[1]:
                                is_premium = True
                            else:
                                # 有过期时间，检查是否过期
                                expiry = datetime.fromisoformat(result[1])
                                if expiry > datetime.now(settings.TZ):
                                    is_premium = True

                        # 检查解锁状态
                        if result[2] == 1:
                            unlock_time = result[3]

                elif service == "emby":
                    # 检查 Emby 用户状态
                    stmt = select(
                        EmbyUser.is_premium,
                        EmbyUser.premium_expiry_time,
                        EmbyUser.download_unlocked,
                        EmbyUser.download_unlock_time,
                    ).where(EmbyUser.tg_id == tg_id)
                    result = session.execute(stmt).fetchone()

                    if result:
                        # 检查 premium 状态
                        if result[0] == 1:
                            # premium_expiry_time 为空表示永久 premium
                            if not result[1]:
                                is_premium = True
                            else:
                                # 有过期时间，检查是否过期
                                expiry = datetime.fromisoformat(result[1])
                                if expiry > datetime.now(settings.TZ):
                                    is_premium = True

                        # 检查解锁状态
                        if result[2] == 1:
                            unlock_time = result[3]

                # Premium 用户或已解锁用户都算已解锁
                is_unlocked = is_premium or (unlock_time is not None)

                return {
                    "is_unlocked": is_unlocked,
                    "is_premium": is_premium,
                    "unlock_time": unlock_time,
                }

        except Exception as e:
            logger.error(
                f"检查用户 {get_user_name_from_tg_id(tg_id)} 的 {service} 下载权限解锁状态失败: {e}"
            )
            return {"is_unlocked": False, "is_premium": False, "unlock_time": None}

    def set_download_unlocked(self, tg_id: int, service: str) -> bool:
        """
        设置用户下载权限为已解锁（仅更新数据库）

        Args:
            tg_id: 用户的 Telegram ID
            service: 服务类型 (plex/emby)

        Returns:
            是否成功
        """
        try:
            with get_session() as session:
                unlock_time = int(time.time())

                if service == "plex":
                    stmt = (
                        update(PlexUser)
                        .where(PlexUser.tg_id == tg_id)
                        .values(
                            sync_unlocked=1,
                            sync_unlock_time=unlock_time,
                        )
                    )
                elif service == "emby":
                    stmt = (
                        update(EmbyUser)
                        .where(EmbyUser.tg_id == tg_id)
                        .values(
                            download_unlocked=1,
                            download_unlock_time=unlock_time,
                        )
                    )
                else:
                    logger.error(f"未知的服务类型: {service}")
                    return False

                session.execute(stmt)
                logger.info(f"用户 {tg_id} 的 {service} 下载权限已解锁")
                return True

        except Exception as e:
            logger.error(f"设置 {service} 下载权限解锁失败: {e}")
            return False

    def deduct_credits_for_download_unlock(self, tg_id: int) -> tuple[bool, str, float]:
        """
        扣除解锁下载权限所需积分

        Args:
            tg_id: 用户的 Telegram ID

        Returns:
            (是否成功, 消息, 剩余积分)
        """
        try:
            with get_session() as session:
                stmt = select(Statistics.credits).where(Statistics.tg_id == tg_id)
                credits = session.execute(stmt).scalar()

                if credits is None:
                    return False, "用户不存在", 0

                required_credits = settings.DOWNLOAD_UNLOCK_CREDITS
                if credits < required_credits:
                    return (
                        False,
                        f"积分不足，需要 {required_credits} 积分，当前积分 {credits:.2f}",
                        credits,
                    )

                # 扣除积分
                new_credits = credits - required_credits
                stmt = (
                    update(Statistics)
                    .where(Statistics.tg_id == tg_id)
                    .values(credits=new_credits)
                )
                session.execute(stmt)

                logger.info(
                    f"用户 {tg_id} 扣除 {required_credits} 积分用于解锁下载权限"
                )
                return True, f"消耗 {required_credits} 积分", new_credits

        except Exception as e:
            logger.error(f"扣除积分失败: {e}")
            return False, f"扣除积分失败: {str(e)}", 0

    def get_download_unlocked_users_num(self) -> int:
        """
        获取已解锁下载权限的用户数量（不包括 Premium 用户）

        Returns:
            解锁用户数量
        """
        try:
            with get_session() as session:
                # Plex 用户
                plex_count = session.execute(
                    select(func.count()).where(PlexUser.sync_unlocked == 1)
                ).scalar()

                # Emby 用户
                emby_count = session.execute(
                    select(func.count()).where(EmbyUser.download_unlocked == 1)
                ).scalar()

                return (plex_count or 0) + (emby_count or 0)
        except Exception as e:
            logger.error(f"获取下载权限解锁用户数量失败: {e}")
            return 0

    # ------------------------------------------------------------------
    # Tautulli 幽灵会话清理
    # ------------------------------------------------------------------

    def get_logged_ghost_row_ids(self, row_ids: List[int]) -> set:
        """查询这批 row_id 中已经留档过的部分，用于跳过重复处理"""
        if not row_ids:
            return set()
        try:
            with get_session() as session:
                stmt = select(GhostSessionLog.row_id).where(
                    GhostSessionLog.row_id.in_(row_ids)
                )
                return set(session.execute(stmt).scalars().all())
        except Exception as e:
            logger.error(f"查询已留档的幽灵会话失败: {e}")
            # 查询失败时返回全集，宁可跳过也不要重复删除/补偿
            return set(row_ids)

    def add_ghost_session_log(self, record: dict) -> bool:
        """留档一条被判定为幽灵会话的记录

        必须在调用 Tautulli 的 delete_history 之前写入：记录一旦删除就无法回溯，
        补偿时长只能依赖这张表。

        record 中的 compensated 决定这条记录是否参与后续补偿：对于已经按脏数据
        结算过的历史记录，应直接置 1（只删除、不补偿），否则会二次计入时长。
        """
        try:
            with get_session() as session:
                session.add(
                    GhostSessionLog(
                        row_id=record["row_id"],
                        user_id=str(record["user_id"]),
                        friendly_name=record.get("friendly_name"),
                        title=record.get("title"),
                        rating_key=(
                            str(record["rating_key"])
                            if record.get("rating_key") is not None
                            else None
                        ),
                        started=record.get("started") or 0,
                        stopped=record.get("stopped") or 0,
                        play_date=record["play_date"],
                        raw_seconds=record["raw_seconds"],
                        media_seconds=record.get("media_seconds"),
                        percent_complete=record.get("percent_complete") or 0,
                        compensated_seconds=record["compensated_seconds"],
                        deleted=0,
                        compensated=int(record.get("compensated") or 0),
                        created_at=int(time.time()),
                    )
                )
                return True
        except Exception as e:
            logger.error(f"留档幽灵会话 row_id={record.get('row_id')} 失败: {e}")
            return False

    def get_undeleted_ghost_row_ids(self) -> List[int]:
        """取出已留档但尚未确认从 Tautulli 删除的 row_id

        用于自愈：留档成功但删除或标记环节失败时，这些记录会停在 deleted=0，
        既不会被补偿也不会被重新扫描到（Tautulli 那边可能已经删了），
        下一轮清理开始时重试一次即可归位。
        """
        try:
            with get_session() as session:
                stmt = select(GhostSessionLog.row_id).where(
                    GhostSessionLog.deleted == 0
                )
                return list(session.execute(stmt).scalars().all())
        except Exception as e:
            logger.error(f"查询未删除的幽灵会话失败: {e}")
            return []

    def mark_ghost_sessions_deleted(self, row_ids: List[int]) -> bool:
        """标记这批记录已从 Tautulli 删除"""
        if not row_ids:
            return True
        try:
            with get_session() as session:
                stmt = (
                    update(GhostSessionLog)
                    .where(GhostSessionLog.row_id.in_(row_ids))
                    .values(deleted=1)
                )
                session.execute(stmt)
                return True
        except Exception as e:
            logger.error(f"标记幽灵会话已删除失败: {e}")
            return False

    def get_pending_ghost_compensation(self) -> Dict[str, float]:
        """取出尚未计入结算的补偿时长，返回 {plex_user_id: 小时数}

        只统计已确认从 Tautulli 删除的记录——没删掉的记录仍会出现在
        get_home_stats 的聚合里，再补偿一次就重复了。
        """
        try:
            with get_session() as session:
                stmt = (
                    select(
                        GhostSessionLog.user_id,
                        func.sum(GhostSessionLog.compensated_seconds),
                    )
                    .where(
                        GhostSessionLog.compensated == 0,
                        GhostSessionLog.deleted == 1,
                    )
                    .group_by(GhostSessionLog.user_id)
                )
                return {
                    str(user_id): float(total or 0) / 3600
                    for user_id, total in session.execute(stmt).all()
                }
        except Exception as e:
            logger.error(f"获取待补偿的幽灵会话时长失败: {e}")
            return {}

    def mark_ghost_compensation_settled(self) -> bool:
        """把当前待补偿的记录标记为已计入结算

        与 get_pending_ghost_compensation 配对使用，确保每条记录只补偿一次。
        """
        try:
            with get_session() as session:
                stmt = (
                    update(GhostSessionLog)
                    .where(
                        GhostSessionLog.compensated == 0,
                        GhostSessionLog.deleted == 1,
                    )
                    .values(compensated=1)
                )
                session.execute(stmt)
                return True
        except Exception as e:
            logger.error(f"标记幽灵会话补偿已结算失败: {e}")
            return False

    # ==================== Gift Pack Operations ====================

    @staticmethod
    def _gift_pack_reward_label(reward: Dict) -> str:
        """把一个奖励项渲染成人类可读的短语，如「100 积分」「7 天 Premium」"""
        reward_type = reward.get("type")
        if reward_type == "credits":
            amount = float(reward.get("amount") or 0)
            text = str(int(amount)) if amount.is_integer() else f"{amount:g}"
            return f"{text} 积分"
        if reward_type == "premium_days":
            return f"{int(reward.get('days') or 0)} 天 Premium"
        return str(reward_type)

    @staticmethod
    def _gift_pack_local_date(timestamp: int) -> str:
        """按 settings.TZ 把时间戳折算成 YYYY-MM-DD

        提醒节流的「今天」以运营时区为准，而非用户浏览器时区，
        否则跨时区用户的提醒节奏会与运营预期错位。
        """
        return datetime.fromtimestamp(int(timestamp), settings.TZ).strftime("%Y-%m-%d")

    @staticmethod
    def _is_premium_active(is_premium, expiry_time) -> bool:
        """判断某个服务的 Premium 是否当前有效（永久会员视为有效）"""
        if not is_premium:
            return False
        if not expiry_time:
            # 有 is_premium 标记但无到期时间 = 永久会员
            return True
        try:
            return datetime.fromisoformat(str(expiry_time)).astimezone(
                settings.TZ
            ) > datetime.now(settings.TZ)
        except (ValueError, TypeError):
            # 到期时间无法解析时退回标记位，避免因脏数据误判为不可领取
            return bool(is_premium)

    def _load_gift_pack_user_context(self, session, tg_id: int) -> Dict:
        """一次性载入资格判定所需的用户状态

        列表页要对 N 个礼包逐个判资格，集中载入避免 N 次重复查询。
        资格永远基于此处的实时查询结果，不使用任何缓存。
        """
        credits = session.execute(
            select(Statistics.credits).where(Statistics.tg_id == tg_id)
        ).scalar_one_or_none()
        plex = session.execute(
            select(PlexUser.is_premium, PlexUser.premium_expiry_time).where(
                PlexUser.tg_id == tg_id
            )
        ).one_or_none()
        emby = session.execute(
            select(EmbyUser.is_premium, EmbyUser.premium_expiry_time).where(
                EmbyUser.tg_id == tg_id
            )
        ).one_or_none()

        bound_services = []
        if plex is not None:
            bound_services.append("plex")
        if emby is not None:
            bound_services.append("emby")

        premium_services = []
        if plex is not None and self._is_premium_active(plex[0], plex[1]):
            premium_services.append("plex")
        if emby is not None and self._is_premium_active(emby[0], emby[1]):
            premium_services.append("emby")

        return {
            "has_stats": credits is not None,
            "credits": float(credits or 0),
            "bound_services": bound_services,
            "premium_services": premium_services,
        }

    @staticmethod
    def _evaluate_gift_pack_eligibility(
        eligibility: Optional[Dict], context: Dict
    ) -> Tuple[bool, List[str]]:
        """判定用户是否满足礼包的领取资格

        :return: (是否满足, 未满足的具体原因列表)
        """
        if not eligibility:
            return True, []

        reasons: List[str] = []

        min_credits = eligibility.get("min_credits")
        if min_credits is not None and context["credits"] < float(min_credits):
            gap = float(min_credits) - context["credits"]
            reasons.append(
                f"积分不足，还差 {gap:.2f} 积分（需要 {float(min_credits):.2f}）"
            )

        if eligibility.get("require_premium") and not context["premium_services"]:
            reasons.append("需要 Premium 会员身份")

        require_binding = eligibility.get("require_binding")
        if require_binding == "any":
            if not context["bound_services"]:
                reasons.append("需先绑定 Plex 或 Emby 账号")
        elif require_binding in ("plex", "emby"):
            if require_binding not in context["bound_services"]:
                reasons.append(f"需先绑定 {require_binding.capitalize()} 账号")

        return (not reasons), reasons

    def _grant_gift_pack_rewards(
        self, session, tg_id: int, rewards: List[Dict], context: Dict
    ) -> Tuple[List[Dict], List[str]]:
        """在调用方的事务内发放全部奖励项

        任一项失败即抛出异常，由调用方回滚整个事务。

        :return: (发放快照, 待事务提交后同步媒体服务器权限的服务列表)
        """
        # 延迟导入：app.premium 依赖本模块，模块级导入会形成循环
        from app.premium import update_premium_status

        snapshot: List[Dict] = []
        pending_permission_sync: List[str] = []

        for reward in rewards:
            reward_type = reward.get("type")
            label = self._gift_pack_reward_label(reward)

            if reward_type == "credits":
                amount = float(reward.get("amount") or 0)
                stats = (
                    session.execute(
                        select(Statistics)
                        .where(Statistics.tg_id == tg_id)
                        .with_for_update()
                    )
                    .scalars()
                    .one_or_none()
                )
                if not stats:
                    raise ValueError("用户积分信息不存在")
                stats.credits = round(float(stats.credits) + amount, 2)
                snapshot.append(
                    {
                        "type": "credits",
                        "label": label,
                        "success": True,
                        "amount": amount,
                        "balance_after": stats.credits,
                    }
                )

            elif reward_type == "premium_days":
                days = int(reward.get("days") or 0)
                services = context["bound_services"]
                if not services:
                    # 正常情况下已被 require_binding 资格拦住，这里是最后一道防线
                    raise ValueError("请先绑定媒体账号后再领取")
                for service in services:
                    # 传入 session 复用外层事务，使 Premium 写入与领取记录同生共死
                    new_expiry = update_premium_status(
                        self, tg_id, service, days, session=session
                    )
                    if new_expiry is None:
                        # 永久会员：跳过延长，但不阻断领取
                        snapshot.append(
                            {
                                "type": "premium_days",
                                "label": label,
                                "success": True,
                                "days": days,
                                "service": service,
                                "skipped": "lifetime",
                                "message": f"{service.capitalize()} 为永久会员，Premium 天数未生效",
                            }
                        )
                    else:
                        snapshot.append(
                            {
                                "type": "premium_days",
                                "label": label,
                                "success": True,
                                "days": days,
                                "service": service,
                                "new_expiry": new_expiry.isoformat(),
                            }
                        )
                        pending_permission_sync.append(service)

            else:
                raise ValueError(f"不支持的奖励类型: {reward_type}")

        return snapshot, pending_permission_sync

    @staticmethod
    def _gift_pack_lifecycle(pack: GiftPack, now: int) -> str:
        """礼包相对当前时间的生命周期状态"""
        if now < int(pack.start_at):
            return "upcoming"
        if now > int(pack.end_at):
            return "ended"
        return "active"

    @staticmethod
    def _gift_pack_remaining(pack: GiftPack) -> Optional[int]:
        """剩余份数；不限量时返回 None"""
        if pack.total_quantity is None:
            return None
        return max(0, int(pack.total_quantity) - int(pack.claimed_count))

    def create_gift_pack(
        self,
        title: str,
        rewards: List[Dict],
        start_at: int,
        end_at: int,
        description: Optional[str] = None,
        eligibility: Optional[Dict] = None,
        total_quantity: Optional[int] = None,
        max_prompt_count: int = 3,
        is_enabled: bool = True,
        created_by: Optional[int] = None,
    ) -> int:
        """创建礼包，返回礼包 ID

        含 Premium 天数奖励时自动补「至少绑定一个媒体账号」的资格：
        把它做成显式资格而非发放时的隐式校验，用户在列表里就能看到
        可行动的提示，且天然不会进入提醒候选。
        """
        if not rewards:
            raise ValueError("礼包至少需要一项奖励")
        if end_at <= start_at:
            raise ValueError("结束时间必须晚于开始时间")
        if total_quantity is not None and total_quantity <= 0:
            raise ValueError("限量份数必须大于 0")

        eligibility = dict(eligibility) if eligibility else {}
        if any(r.get("type") == "premium_days" for r in rewards):
            if not eligibility.get("require_binding"):
                eligibility["require_binding"] = "any"

        now = int(time.time())
        with get_session() as session:
            pack = GiftPack(
                title=title,
                description=description,
                rewards=json.dumps(rewards, ensure_ascii=False),
                eligibility=json.dumps(eligibility, ensure_ascii=False)
                if eligibility
                else None,
                total_quantity=total_quantity,
                claimed_count=0,
                start_at=int(start_at),
                end_at=int(end_at),
                max_prompt_count=int(max_prompt_count),
                is_enabled=1 if is_enabled else 0,
                expiry_notified=0,
                created_by=created_by,
                created_at=now,
                updated_at=now,
            )
            session.add(pack)
            session.flush()
            return int(pack.id)

    def update_gift_pack(self, pack_id: int, **fields) -> bool:
        """编辑礼包；仅更新传入的字段"""
        allowed = {
            "title",
            "description",
            "rewards",
            "eligibility",
            "total_quantity",
            "start_at",
            "end_at",
            "max_prompt_count",
            "is_enabled",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return True

        with get_session() as session:
            pack = (
                session.execute(select(GiftPack).where(GiftPack.id == pack_id))
                .scalars()
                .one_or_none()
            )
            if not pack:
                raise ValueError("礼包不存在")

            start_at = int(updates.get("start_at", pack.start_at))
            end_at = int(updates.get("end_at", pack.end_at))
            if end_at <= start_at:
                raise ValueError("结束时间必须晚于开始时间")

            rewards = updates.get("rewards")
            if rewards is not None:
                if not rewards:
                    raise ValueError("礼包至少需要一项奖励")
                # 奖励项变更后重新套用绑定资格：含 Premium 则必须绑定
                eligibility = updates.get("eligibility")
                if eligibility is None:
                    eligibility = (
                        json.loads(pack.eligibility) if pack.eligibility else {}
                    )
                eligibility = dict(eligibility)
                if any(r.get("type") == "premium_days" for r in rewards):
                    if not eligibility.get("require_binding"):
                        eligibility["require_binding"] = "any"
                updates["eligibility"] = eligibility
                updates["rewards"] = json.dumps(rewards, ensure_ascii=False)

            if "eligibility" in updates and not isinstance(updates["eligibility"], str):
                value = updates["eligibility"]
                updates["eligibility"] = (
                    json.dumps(value, ensure_ascii=False) if value else None
                )

            if "total_quantity" in updates:
                total_quantity = int(updates["total_quantity"])
                if total_quantity <= 0:
                    raise ValueError("限量份数必须大于 0")
                if total_quantity < int(pack.claimed_count):
                    raise ValueError(
                        f"限量份数不能小于已领取份数（已领 {int(pack.claimed_count)} 份）"
                    )

            if "is_enabled" in updates:
                updates["is_enabled"] = 1 if updates["is_enabled"] else 0

            for key, value in updates.items():
                setattr(pack, key, value)
            pack.updated_at = int(time.time())
            return True

    def set_gift_pack_enabled(self, pack_id: int, is_enabled: bool) -> bool:
        """启用 / 停用礼包"""
        try:
            with get_session() as session:
                result = session.execute(
                    update(GiftPack)
                    .where(GiftPack.id == pack_id)
                    .values(
                        is_enabled=1 if is_enabled else 0, updated_at=int(time.time())
                    )
                )
                return result.rowcount > 0
        except Exception as e:
            logger.error(f"更新礼包启用状态失败 (pack_id={pack_id}): {e}")
            return False

    def delete_gift_pack(self, pack_id: int) -> bool:
        """删除礼包；已有领取记录时拒绝删除，只能停用"""
        with get_session() as session:
            pack = (
                session.execute(select(GiftPack).where(GiftPack.id == pack_id))
                .scalars()
                .one_or_none()
            )
            if not pack:
                raise ValueError("礼包不存在")

            claimed = session.execute(
                select(func.count(GiftPackUserState.id)).where(
                    GiftPackUserState.pack_id == pack_id,
                    GiftPackUserState.claimed_at.isnot(None),
                )
            ).scalar_one()
            if int(claimed) > 0 or int(pack.claimed_count) > 0:
                raise ValueError("该礼包已有用户领取，只能停用不能删除")

            # 仅被提醒过、从未领取的状态行随礼包一并清理
            session.execute(
                delete(GiftPackUserState).where(GiftPackUserState.pack_id == pack_id)
            )
            session.delete(pack)
            return True

    def get_gift_pack_by_id(self, pack_id: int) -> Optional[Dict]:
        """获取单个礼包的原始定义"""
        try:
            with get_session() as session:
                pack = (
                    session.execute(select(GiftPack).where(GiftPack.id == pack_id))
                    .scalars()
                    .one_or_none()
                )
                if not pack:
                    return None
                now = int(time.time())
                return {
                    "id": int(pack.id),
                    "title": pack.title,
                    "description": pack.description,
                    "rewards": json.loads(pack.rewards),
                    "eligibility": json.loads(pack.eligibility)
                    if pack.eligibility
                    else None,
                    "total_quantity": pack.total_quantity,
                    "claimed_count": int(pack.claimed_count),
                    "remaining": self._gift_pack_remaining(pack),
                    "start_at": int(pack.start_at),
                    "end_at": int(pack.end_at),
                    "max_prompt_count": int(pack.max_prompt_count),
                    "is_enabled": bool(pack.is_enabled),
                    "lifecycle": self._gift_pack_lifecycle(pack, now),
                    "created_by": pack.created_by,
                    "created_at": int(pack.created_at),
                    "updated_at": int(pack.updated_at),
                }
        except Exception as e:
            logger.error(f"获取礼包失败 (pack_id={pack_id}): {e}")
            return None

    def get_gift_packs_for_user(self, tg_id: int) -> List[Dict]:
        """礼包中心列表：返回与该用户相关的礼包及其对该用户的状态

        「相关」= 所有已启用的礼包，加上该用户已领取过的礼包
        （后者即使事后被停用，用户仍应能查到自己的领取凭据）。
        """
        try:
            with get_session() as session:
                now = int(time.time())
                claimed_pack_ids = [
                    pid
                    for (pid,) in session.execute(
                        select(GiftPackUserState.pack_id).where(
                            GiftPackUserState.tg_id == tg_id,
                            GiftPackUserState.claimed_at.isnot(None),
                        )
                    ).all()
                ]
                condition = GiftPack.is_enabled == 1
                if claimed_pack_ids:
                    condition = condition | GiftPack.id.in_(claimed_pack_ids)
                packs = (
                    session.execute(select(GiftPack).where(condition)).scalars().all()
                )
                if not packs:
                    return []

                states = {
                    state.pack_id: state
                    for state in session.execute(
                        select(GiftPackUserState).where(
                            GiftPackUserState.tg_id == tg_id,
                            GiftPackUserState.pack_id.in_([p.id for p in packs]),
                        )
                    )
                    .scalars()
                    .all()
                }
                context = self._load_gift_pack_user_context(session, tg_id)

                items: List[Dict] = []
                for pack in packs:
                    rewards = json.loads(pack.rewards)
                    eligibility = (
                        json.loads(pack.eligibility) if pack.eligibility else None
                    )
                    lifecycle = self._gift_pack_lifecycle(pack, now)
                    remaining = self._gift_pack_remaining(pack)
                    state = states.get(pack.id)

                    reasons: List[str] = []
                    if state is not None and state.claimed_at:
                        status = "claimed"
                    elif not pack.is_enabled:
                        status = "disabled"
                    elif lifecycle == "upcoming":
                        status = "upcoming"
                    elif lifecycle == "ended":
                        status = "ended"
                    elif remaining is not None and remaining <= 0:
                        status = "sold_out"
                    else:
                        eligible, reasons = self._evaluate_gift_pack_eligibility(
                            eligibility, context
                        )
                        status = "claimable" if eligible else "ineligible"

                    items.append(
                        {
                            "id": int(pack.id),
                            "title": pack.title,
                            "description": pack.description,
                            "rewards": [
                                {
                                    "type": r.get("type"),
                                    "amount": r.get("amount"),
                                    "days": r.get("days"),
                                    "label": self._gift_pack_reward_label(r),
                                }
                                for r in rewards
                            ],
                            "start_at": int(pack.start_at),
                            "end_at": int(pack.end_at),
                            "total_quantity": pack.total_quantity,
                            "claimed_count": int(pack.claimed_count),
                            "remaining": remaining,
                            "lifecycle": lifecycle,
                            "status": status,
                            "ineligible_reasons": reasons,
                            "claimed_at": int(state.claimed_at)
                            if state is not None and state.claimed_at
                            else None,
                            "reward_snapshot": json.loads(state.reward_snapshot)
                            if state is not None and state.reward_snapshot
                            else None,
                        }
                    )

                # 进行中排最前，其次未开始，最后已结束；同组内按结束时间由近及远
                order = {"active": 0, "upcoming": 1, "ended": 2}
                items.sort(key=lambda x: (order.get(x["lifecycle"], 3), x["end_at"]))
                return items
        except Exception as e:
            logger.error(f"获取用户礼包列表失败 (tg_id={tg_id}): {e}")
            return []

    def claim_gift_pack(self, pack_id: int, tg_id: int) -> Dict:
        """领取礼包

        单事务内完成：锁 pack 行 → 校验启用/窗口/余量/资格/未领取 →
        发放全部奖励 → claimed_count += 1 → upsert user_state。
        任一步失败整体回滚，不扣余量、不记领取、不发奖励。
        UniqueConstraint(pack_id, tg_id) 是并发重复提交的最后一道防线。

        媒体服务器权限同步是不可回滚的外部副作用，放到事务提交之后执行。
        """
        now = int(time.time())
        with get_session() as session:
            pack = (
                session.execute(
                    select(GiftPack).where(GiftPack.id == pack_id).with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not pack:
                raise ValueError("礼包不存在")
            if not pack.is_enabled:
                raise ValueError("礼包已停用")
            if now < int(pack.start_at):
                raise ValueError("礼包尚未开始")
            if now > int(pack.end_at):
                raise ValueError("礼包已结束")

            total_quantity = pack.total_quantity
            if total_quantity is not None and int(pack.claimed_count) >= int(
                total_quantity
            ):
                raise ValueError("礼包已被领完")

            state = (
                session.execute(
                    select(GiftPackUserState)
                    .where(
                        GiftPackUserState.pack_id == pack_id,
                        GiftPackUserState.tg_id == tg_id,
                    )
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if state is not None and state.claimed_at:
                raise ValueError("你已领取过该礼包")

            context = self._load_gift_pack_user_context(session, tg_id)
            if not context["has_stats"]:
                raise ValueError("用户积分信息不存在")

            eligibility = json.loads(pack.eligibility) if pack.eligibility else None
            eligible, reasons = self._evaluate_gift_pack_eligibility(
                eligibility, context
            )
            if not eligible:
                raise ValueError("；".join(reasons) or "不满足领取条件")

            rewards = json.loads(pack.rewards)
            snapshot, pending_permission_sync = self._grant_gift_pack_rewards(
                session, tg_id, rewards, context
            )

            pack.claimed_count = int(pack.claimed_count) + 1
            snapshot_json = json.dumps(snapshot, ensure_ascii=False)
            if state is not None:
                state.claimed_at = now
                state.reward_snapshot = snapshot_json
            else:
                session.add(
                    GiftPackUserState(
                        pack_id=pack_id,
                        tg_id=tg_id,
                        claimed_at=now,
                        reward_snapshot=snapshot_json,
                        prompt_count=0,
                    )
                )

            claimed_count = int(pack.claimed_count)
            remaining = self._gift_pack_remaining(pack)
            pack_title = pack.title

        # 事务已提交：同步媒体服务器权限（best-effort，失败只告警不影响领取结果）
        for service in pending_permission_sync:
            try:
                from app.premium import sync_media_permission

                sync_media_permission(self, tg_id, service)
            except Exception as e:
                logger.warning(
                    f"礼包领取后同步 {service} 权限失败 (pack_id={pack_id}, tg_id={tg_id}): {e}"
                )

        return {
            "pack_id": int(pack_id),
            "title": pack_title,
            "results": snapshot,
            "claimed_count": claimed_count,
            "remaining": remaining,
            "total_quantity": total_quantity,
            "sold_out": total_quantity is not None
            and claimed_count >= int(total_quantity),
        }

    def prompt_check_gift_packs(self, tg_id: int) -> List[Dict]:
        """判定是否该向用户弹出礼包提醒，并在返回的同时记账

        返回非空即表示应弹出一个汇总弹窗。候选条件（D5）：
        进行中 ∧ 已启用 ∧ 未领取 ∧ 满足资格 ∧ 有余量
        ∧ prompt_count < max_prompt_count ∧ 今天尚未提醒过。

        空态短路：系统中不存在进行中且启用的礼包时立即返回，不做任何
        用户维度查询、不写任何行——「当前没有活动」是运营常态。
        """
        try:
            with get_session() as session:
                now = int(time.time())
                packs = (
                    session.execute(
                        select(GiftPack).where(
                            GiftPack.is_enabled == 1,
                            GiftPack.start_at <= now,
                            GiftPack.end_at >= now,
                        )
                    )
                    .scalars()
                    .all()
                )
                # 空态短路：不写库、不查用户
                if not packs:
                    return []

                # 有余量的礼包才值得提醒
                packs = [
                    p
                    for p in packs
                    if p.total_quantity is None
                    or int(p.claimed_count) < int(p.total_quantity)
                ]
                if not packs:
                    return []

                context = self._load_gift_pack_user_context(session, tg_id)
                if not context["has_stats"]:
                    # 无 Statistics 记录的用户无法写入状态行（外键约束），不提醒
                    return []

                states = {
                    state.pack_id: state
                    for state in session.execute(
                        select(GiftPackUserState).where(
                            GiftPackUserState.tg_id == tg_id,
                            GiftPackUserState.pack_id.in_([p.id for p in packs]),
                        )
                    )
                    .scalars()
                    .all()
                }
                today = self._gift_pack_local_date(now)

                candidates: List[Dict] = []
                for pack in packs:
                    state = states.get(pack.id)
                    if state is not None:
                        if state.claimed_at:
                            continue
                        if int(state.prompt_count) >= int(pack.max_prompt_count):
                            continue
                        if state.last_prompted_at and (
                            self._gift_pack_local_date(state.last_prompted_at) == today
                        ):
                            continue

                    eligibility = (
                        json.loads(pack.eligibility) if pack.eligibility else None
                    )
                    eligible, _ = self._evaluate_gift_pack_eligibility(
                        eligibility, context
                    )
                    if not eligible:
                        continue

                    # 判定通过即记账：多记一次的后果（少提醒一次）远优于漏记（反复骚扰）
                    if state is not None:
                        state.prompt_count = int(state.prompt_count) + 1
                        state.last_prompted_at = now
                    else:
                        session.add(
                            GiftPackUserState(
                                pack_id=pack.id,
                                tg_id=tg_id,
                                prompt_count=1,
                                last_prompted_at=now,
                            )
                        )

                    rewards = json.loads(pack.rewards)
                    candidates.append(
                        {
                            "id": int(pack.id),
                            "title": pack.title,
                            "description": pack.description,
                            "rewards": [
                                {
                                    "type": r.get("type"),
                                    "amount": r.get("amount"),
                                    "days": r.get("days"),
                                    "label": self._gift_pack_reward_label(r),
                                }
                                for r in rewards
                            ],
                            "end_at": int(pack.end_at),
                            "total_quantity": pack.total_quantity,
                            "remaining": self._gift_pack_remaining(pack),
                        }
                    )

                return candidates
        except Exception as e:
            logger.error(f"礼包提醒判定失败 (tg_id={tg_id}): {e}")
            return []

    def get_gift_packs_admin(
        self, page: int = 1, page_size: int = 20
    ) -> Tuple[List[Dict], int]:
        """管理端礼包列表（按创建时间倒序分页）"""
        try:
            with get_session() as session:
                now = int(time.time())
                total = session.execute(select(func.count(GiftPack.id))).scalar_one()
                packs = (
                    session.execute(
                        select(GiftPack)
                        .order_by(GiftPack.created_at.desc())
                        .offset(max(0, (page - 1) * page_size))
                        .limit(page_size)
                    )
                    .scalars()
                    .all()
                )
                if not packs:
                    return [], int(total)

                claimed_counts = {
                    pid: count
                    for pid, count in session.execute(
                        select(
                            GiftPackUserState.pack_id,
                            func.count(GiftPackUserState.id),
                        )
                        .where(
                            GiftPackUserState.pack_id.in_([p.id for p in packs]),
                            GiftPackUserState.claimed_at.isnot(None),
                        )
                        .group_by(GiftPackUserState.pack_id)
                    ).all()
                }

                items = [
                    {
                        "id": int(pack.id),
                        "title": pack.title,
                        "description": pack.description,
                        "rewards": json.loads(pack.rewards),
                        "eligibility": json.loads(pack.eligibility)
                        if pack.eligibility
                        else None,
                        "total_quantity": pack.total_quantity,
                        "claimed_count": int(pack.claimed_count),
                        "remaining": self._gift_pack_remaining(pack),
                        "start_at": int(pack.start_at),
                        "end_at": int(pack.end_at),
                        "max_prompt_count": int(pack.max_prompt_count),
                        "is_enabled": bool(pack.is_enabled),
                        "lifecycle": self._gift_pack_lifecycle(pack, now),
                        "can_delete": int(claimed_counts.get(pack.id, 0)) == 0
                        and int(pack.claimed_count) == 0,
                        "created_by": pack.created_by,
                        "created_at": int(pack.created_at),
                        "updated_at": int(pack.updated_at),
                    }
                    for pack in packs
                ]
                return items, int(total)
        except Exception as e:
            logger.error(f"获取礼包管理列表失败: {e}")
            return [], 0

    def get_gift_pack_stats(self, pack_id: int) -> Optional[Dict]:
        """单个礼包的领取统计：领取人数、被提醒人数、各类奖励发放总量"""
        try:
            with get_session() as session:
                pack = (
                    session.execute(select(GiftPack).where(GiftPack.id == pack_id))
                    .scalars()
                    .one_or_none()
                )
                if not pack:
                    return None

                claimed_users = session.execute(
                    select(func.count(GiftPackUserState.id)).where(
                        GiftPackUserState.pack_id == pack_id,
                        GiftPackUserState.claimed_at.isnot(None),
                    )
                ).scalar_one()
                prompted_users = session.execute(
                    select(func.count(GiftPackUserState.id)).where(
                        GiftPackUserState.pack_id == pack_id,
                        GiftPackUserState.prompt_count > 0,
                    )
                ).scalar_one()

                # reward_snapshot 是 JSON 文本，聚合只能在 Python 侧做
                snapshots = [
                    row
                    for (row,) in session.execute(
                        select(GiftPackUserState.reward_snapshot).where(
                            GiftPackUserState.pack_id == pack_id,
                            GiftPackUserState.reward_snapshot.isnot(None),
                        )
                    ).all()
                ]
                credits_total = 0.0
                premium_days_total = 0
                premium_grants = 0
                premium_skipped = 0
                for raw in snapshots:
                    try:
                        for item in json.loads(raw):
                            if item.get("type") == "credits":
                                credits_total += float(item.get("amount") or 0)
                            elif item.get("type") == "premium_days":
                                if item.get("skipped"):
                                    premium_skipped += 1
                                else:
                                    premium_days_total += int(item.get("days") or 0)
                                    premium_grants += 1
                    except (ValueError, TypeError) as e:
                        logger.warning(f"解析礼包发放快照失败 (pack_id={pack_id}): {e}")

                reward_totals = []
                if credits_total:
                    reward_totals.append(
                        {
                            "type": "credits",
                            "label": "积分",
                            "total": round(credits_total, 2),
                        }
                    )
                if premium_grants or premium_skipped:
                    reward_totals.append(
                        {
                            "type": "premium_days",
                            "label": "Premium 天数",
                            "total": premium_days_total,
                            "grants": premium_grants,
                            "skipped_lifetime": premium_skipped,
                        }
                    )

                return {
                    "pack_id": int(pack.id),
                    "title": pack.title,
                    "claimed_users": int(claimed_users),
                    "prompted_users": int(prompted_users),
                    "total_quantity": pack.total_quantity,
                    "remaining": self._gift_pack_remaining(pack),
                    "reward_totals": reward_totals,
                }
        except Exception as e:
            logger.error(f"获取礼包统计失败 (pack_id={pack_id}): {e}")
            return None

    def get_gift_pack_claim_records(
        self, pack_id: int, page: int = 1, page_size: int = 20
    ) -> Tuple[List[Dict], int]:
        """某礼包的领取记录（按领取时间倒序分页）"""
        try:
            with get_session() as session:
                total = session.execute(
                    select(func.count(GiftPackUserState.id)).where(
                        GiftPackUserState.pack_id == pack_id,
                        GiftPackUserState.claimed_at.isnot(None),
                    )
                ).scalar_one()
                rows = (
                    session.execute(
                        select(GiftPackUserState)
                        .where(
                            GiftPackUserState.pack_id == pack_id,
                            GiftPackUserState.claimed_at.isnot(None),
                        )
                        .order_by(GiftPackUserState.claimed_at.desc())
                        .offset(max(0, (page - 1) * page_size))
                        .limit(page_size)
                    )
                    .scalars()
                    .all()
                )
                records = [
                    {
                        "tg_id": int(row.tg_id),
                        "claimed_at": int(row.claimed_at),
                        "reward_snapshot": json.loads(row.reward_snapshot)
                        if row.reward_snapshot
                        else None,
                    }
                    for row in rows
                ]
                return records, int(total)
        except Exception as e:
            logger.error(f"获取礼包领取记录失败 (pack_id={pack_id}): {e}")
            return [], 0

    def get_expired_unnotified_gift_packs(self) -> List[Dict]:
        """扫描已过期且尚未发送汇总通知的礼包

        配合 mark_gift_pack_expiry_notified() 使用。用周期扫描而非 date job：
        end_at 是管理员可编辑的，date job 每次改期都要重排、漏排就永久丢通知。
        """
        try:
            now = int(time.time())
            with get_session() as session:
                packs = (
                    session.execute(
                        select(GiftPack).where(
                            GiftPack.end_at < now,
                            GiftPack.expiry_notified == 0,
                        )
                    )
                    .scalars()
                    .all()
                )
                return [
                    {
                        "id": int(pack.id),
                        "title": pack.title,
                        "total_quantity": pack.total_quantity,
                        "claimed_count": int(pack.claimed_count),
                        "end_at": int(pack.end_at),
                    }
                    for pack in packs
                ]
        except Exception as e:
            logger.error(f"扫描过期礼包失败: {e}")
            return []

    def mark_gift_pack_expiry_notified(self, pack_id: int) -> bool:
        """标记某礼包的过期汇总通知已发送"""
        try:
            with get_session() as session:
                result = session.execute(
                    update(GiftPack)
                    .where(GiftPack.id == pack_id, GiftPack.expiry_notified == 0)
                    .values(expiry_notified=1)
                )
                return result.rowcount > 0
        except Exception as e:
            logger.error(f"标记礼包过期通知失败 (pack_id={pack_id}): {e}")
            return False


# 创建全局实例
db = DatabaseORM()
