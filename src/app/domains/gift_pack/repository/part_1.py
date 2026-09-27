import time
from datetime import UTC, datetime
from typing import ClassVar
from uuid import uuid4

from sqlalchemy import distinct, func, select

from app.core.config import settings
from app.domains.auction.models import AuctionBids
from app.domains.badges.models import UserBadge
from app.domains.blackjack import service as blackjack_service
from app.domains.credits import repository as credits_repository
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.gift_pack.models import GiftPack, GiftPackUserState
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
from app.domains.invitation.models import Invitation
from app.domains.luckywheel import repository as luckywheel_repository
from app.domains.luckywheel.models import WheelStats
from app.domains.prediction.models import PredictionBet
from app.domains.treasure.models import TreasureParticipation

from . import GIFT_PACK_REWARD_TYPES


class _GiftPackRepositoryPart1:
    @staticmethod
    def _gift_pack_reward_label(reward: dict) -> str:
        """把一个奖励项渲染成人类可读的短语，如「100 积分」「7 天 Premium」"""
        reward_type = reward.get("type")
        meta = GIFT_PACK_REWARD_TYPES.get(reward_type)
        if meta is None:
            return str(reward_type)
        return meta["label"](reward)

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

    def _load_gift_pack_user_context(self, session, tg_id: int) -> dict:
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

        badge_ids = set(
            session.execute(
                select(UserBadge.badge_id).where(
                    UserBadge.tg_id == tg_id, UserBadge.is_active == 1
                )
            ).scalars()
        )
        claimed_pack_ids = set(
            session.execute(
                select(GiftPackUserState.pack_id).where(
                    GiftPackUserState.tg_id == tg_id,
                    GiftPackUserState.claimed_at.is_not(None),
                )
            ).scalars()
        )
        return {
            "has_stats": credits is not None,
            "credits": float(credits or 0),
            "bound_services": bound_services,
            "premium_services": premium_services,
            "badge_ids": badge_ids,
            "claimed_pack_ids": claimed_pack_ids,
            # This cache belongs to this request/transaction, never to DatabaseORM.
            "_session": session,
            "_tg_id": tg_id,
            "_metric_cache": {},
        }

    @staticmethod
    def _gift_pack_phase_ref(pack: GiftPack, now: int) -> int:
        """Freeze timestamped tasks at their deadline (or the pack's end)."""
        return min(int(now), int(pack.task_end_at or pack.end_at))

    @staticmethod
    def _count_gift_pack_wheel_spins(
        session, tg_id: int, since: int, until: int, **qualifiers
    ) -> int:
        stmt = select(func.count(WheelStats.id)).where(
            WheelStats.tg_id == tg_id,
            WheelStats.timestamp >= since,
            WheelStats.timestamp <= until,
        )
        if qualifiers.get("paid_only", True):
            stmt = stmt.where(WheelStats.source == "paid")
        return int(session.execute(stmt).scalar_one())

    @staticmethod
    def _count_gift_pack_blackjack_hands(
        session, tg_id: int, since: int, until: int, **qualifiers
    ) -> int | tuple[int, float]:
        return blackjack_service.count_eligible_cash_hands_tx(
            session,
            tg_id,
            since,
            until,
            min_bet=qualifiers.get("min_bet"),
            min_accuracy=qualifiers.get("min_accuracy"),
        )

    @staticmethod
    def _count_gift_pack_treasure_issues(
        session, tg_id: int, since: int, until: int, **qualifiers
    ) -> int:
        return int(
            session.execute(
                select(func.count(distinct(TreasureParticipation.issue_id))).where(
                    TreasureParticipation.tg_id == tg_id,
                    TreasureParticipation.created_at_ms >= since * 1000,
                    TreasureParticipation.created_at_ms <= until * 1000,
                )
            ).scalar_one()
        )

    @staticmethod
    def _count_gift_pack_prediction_bets(
        session, tg_id: int, since: int, until: int, **qualifiers
    ) -> int:
        return int(
            session.execute(
                select(func.count(PredictionBet.id)).where(
                    PredictionBet.tg_id == tg_id,
                    PredictionBet.created_at >= datetime.fromtimestamp(since, UTC),
                    PredictionBet.created_at <= datetime.fromtimestamp(until, UTC),
                )
            ).scalar_one()
        )

    @staticmethod
    def _count_gift_pack_auction_participations(
        session, tg_id: int, since: int, until: int, **qualifiers
    ) -> int:
        return int(
            session.execute(
                select(func.count(distinct(AuctionBids.auction_id))).where(
                    AuctionBids.bidder_id == tg_id,
                    AuctionBids.bid_time >= since,
                    AuctionBids.bid_time <= until,
                )
            ).scalar_one()
        )

    @staticmethod
    def _count_gift_pack_tournament_entries(
        session, tg_id: int, since: int, until: int, **qualifiers
    ) -> int:
        return blackjack_service.count_tournament_entries_tx(
            session, tg_id, since, until
        )

    @staticmethod
    def _count_gift_pack_invitees(
        session, tg_id: int, since: int, until: int, **qualifiers
    ) -> int:
        # Invitations have no event timestamp; only an all-time window is valid.
        return int(
            session.execute(
                select(func.count(distinct(Invitation.used_by))).where(
                    Invitation.owner == tg_id, Invitation.is_used == 1
                )
            ).scalar_one()
        )

    @staticmethod
    def _count_gift_pack_watched_hours(
        session, tg_id: int, since: int, until: int, **qualifiers
    ) -> float:
        # Aggregate totals have no history: they deliberately keep growing after task_end_at.
        plex = session.execute(
            select(PlexUser.watched_time).where(PlexUser.tg_id == tg_id)
        ).scalar_one_or_none()
        emby = session.execute(
            select(EmbyUser.emby_watched_time).where(EmbyUser.tg_id == tg_id)
        ).scalar_one_or_none()
        return float(plex or 0) + float(emby or 0)

    _GIFT_PACK_COUNT_METHODS: ClassVar[dict[str, str]] = {
        "wheel_spins": "_count_gift_pack_wheel_spins",
        "blackjack_hands": "_count_gift_pack_blackjack_hands",
        "treasure_issues": "_count_gift_pack_treasure_issues",
        "prediction_bets": "_count_gift_pack_prediction_bets",
        "auction_participations": "_count_gift_pack_auction_participations",
        "tournament_entries": "_count_gift_pack_tournament_entries",
        "invitees": "_count_gift_pack_invitees",
        "watched_hours": "_count_gift_pack_watched_hours",
    }

    def _gift_pack_metric_value(
        self, item: dict, ctx: dict, pack: GiftPack, ref: int
    ) -> int | float | tuple[int, float]:
        window = item.get("window") or {"kind": "all"}
        kind = window["kind"]
        if kind == "pack":
            since = int(pack.start_at)
            # A pack's own window has not opened; do not issue a COUNT query.
            if ref < since:
                return (0, 0.0) if item.get("min_accuracy") is not None else 0
        elif kind == "days":
            since = ref - int(window["days"]) * 86400
        else:
            since = 0
        metric = item["type"]
        qualifiers = {
            key: item[key]
            for key in ("paid_only", "min_bet", "min_accuracy")
            if key in item
        }
        cache_key = (metric, since, ref, tuple(sorted(qualifiers.items())))
        cache = ctx.setdefault("_metric_cache", {})
        if cache_key not in cache:
            method = getattr(self, self._GIFT_PACK_COUNT_METHODS[metric])
            cache[cache_key] = method(
                ctx["_session"], ctx["_tg_id"], since, ref, **qualifiers
            )
        return cache[cache_key]

    def _evaluate_conditions(
        self, items: list[dict] | None, ctx: dict, pack: GiftPack, ref: int
    ) -> tuple[bool, list[dict]]:
        """Evaluate each condition once, returning eligibility and structured progress."""
        progress = []
        all_met = True
        for item in items or []:
            if item["type"] == "any_of":
                # A group contains leaves only; evaluate all leaves for their progress.
                children = [
                    self._evaluate_gift_pack_condition(leaf, ctx, pack, ref)
                    for leaf in item["items"]
                ]
                met = any(child["met"] for child in children)
                progress.append(
                    {
                        "type": "any_of",
                        "label": "任选其一",
                        "met": met,
                        "items": children,
                    }
                )
            else:
                leaf = self._evaluate_gift_pack_condition(item, ctx, pack, ref)
                met = leaf["met"]
                progress.append(leaf)
            all_met = all_met and met
        return all_met, progress

    def _evaluate_gift_pack_condition(
        self, item: dict, ctx: dict, pack: GiftPack, ref: int
    ) -> dict:
        kind = item["type"]
        result = {"type": kind, "label": self._gift_pack_condition_label(item)}
        if kind == "premium":
            result["met"] = bool(ctx["premium_services"]) == (item["state"] == "active")
        elif kind == "bound":
            service = item.get("service", "any")
            result["met"] = (
                bool(ctx["bound_services"])
                if service == "any"
                else service in ctx["bound_services"]
            )
        elif kind == "credits":
            current = float(ctx["credits"])
            lower = item.get("min")
            upper = item.get("max")
            result.update(
                met=(lower is None or current >= lower)
                and (upper is None or current <= upper),
                current=current,
                target=lower if lower is not None else upper,
            )
        elif kind == "badge":
            result["met"] = item["badge_id"] in ctx["badge_ids"]
        elif kind == "claimed_pack":
            result["met"] = item["pack_id"] in ctx["claimed_pack_ids"]
        elif kind == "user_list":
            member = ctx["_tg_id"] in item["tg_ids"]
            result["met"] = member if item["mode"] == "include" else not member
        elif kind in self._GIFT_PACK_COUNT_METHODS:
            value = self._gift_pack_metric_value(item, ctx, pack, ref)
            accuracy = None
            if kind == "blackjack_hands" and isinstance(value, tuple):
                value, accuracy = value
            target = item["min"]
            met = value >= target
            if accuracy is not None:
                accuracy_target = float(item["min_accuracy"])
                met = met and accuracy >= accuracy_target
                result["sub"] = [
                    {
                        "label": "准确率",
                        "current": round(accuracy, 2),
                        "target": accuracy_target,
                        "met": accuracy >= accuracy_target,
                    }
                ]
            result.update(met=met, current=value, target=target)
            if kind not in ("invitees", "watched_hours"):
                result["window"] = item.get("window") or {"kind": "all"}
        else:
            raise ValueError(f"不支持的礼包条件: {kind}")
        return result

    def _evaluate_gift_pack_audience(
        self,
        audience: list[dict] | None,
        ctx: dict,
        pack: GiftPack,
        ref: int,
        state: GiftPackUserState | None = None,
    ) -> bool:
        """List membership is live even when non-list criteria were locked earlier."""
        lists = [item for item in audience or [] if item["type"] == "user_list"]
        others = [item for item in audience or [] if item["type"] != "user_list"]
        listed, _ = self._evaluate_conditions(lists, ctx, pack, ref)
        if not listed:
            return False
        if state is not None and state.audience_locked_at is not None:
            return True
        return self._evaluate_conditions(others, ctx, pack, ref)[0]

    def _lock_gift_pack_audience(
        self,
        session,
        pack: GiftPack,
        tg_id: int,
        ctx: dict,
        now: int,
        state: GiftPackUserState | None = None,
    ) -> bool:
        """POST reminder helper: persist non-list audience only during an active phase.

        The read-only list and claim paths must call _evaluate_gift_pack_audience
        instead; they never create a state row or lock audience membership.
        """
        if not pack.is_enabled or self._gift_pack_lifecycle(pack, now) not in (
            "active",
            "claim_only",
        ):
            return False
        if state is None:
            state = session.execute(
                select(GiftPackUserState).where(
                    GiftPackUserState.pack_id == pack.id,
                    GiftPackUserState.tg_id == tg_id,
                )
            ).scalar_one_or_none()
        if state is not None and state.claimed_at is not None:
            return False
        audience, _ = self._resolve_gift_pack_conditions(pack)
        visible = self._evaluate_gift_pack_audience(
            audience, ctx, pack, self._gift_pack_phase_ref(pack, now), state
        )
        if visible and (state is None or state.audience_locked_at is None):
            if state is None:
                state = GiftPackUserState(pack_id=pack.id, tg_id=tg_id)
                session.add(state)
            state.audience_locked_at = now
        return visible

    @staticmethod
    def _evaluate_gift_pack_eligibility(
        eligibility: dict | None, context: dict
    ) -> tuple[bool, list[str]]:
        """判定用户是否满足礼包的领取资格

        :return: (是否满足, 未满足的具体原因列表)
        """
        if not eligibility:
            return True, []

        reasons: list[str] = []

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
        elif (
            require_binding in ("plex", "emby")
            and require_binding not in context["bound_services"]
        ):
            reasons.append(f"需先绑定 {require_binding.capitalize()} 账号")

        return (not reasons), reasons

    def _grant_gift_pack_rewards(
        self, session, tg_id: int, rewards: list[dict], context: dict
    ) -> tuple[list[dict], list[str], list[str], list[str]]:
        """在调用方的事务内发放全部奖励项

        任一项失败即抛出异常，由调用方回滚整个事务。所有分支都复用调用方的
        session；媒体服务器同步提交后执行，特权码配置由领取方在最后一次
        数据库 flush 后、事务提交前写入。

        :return: (发放快照,
                  待事务提交后同步 Premium 媒体服务器权限的服务列表,
                  待事务提交后同步下载权限到媒体服务器的服务列表,
                  待事务提交前写入配置的特权邀请码列表)
        """
        # 延迟导入：app.premium 依赖本模块，模块级导入会形成循环
        from app.domains.premium.service import update_premium_status

        snapshot: list[dict] = []
        pending_permission_sync: list[str] = []
        pending_download_sync: list[str] = []
        pending_privileged_codes: list[str] = []

        for reward in rewards:
            reward_type = reward.get("type")
            label = self._gift_pack_reward_label(reward)

            if reward_type == "credits":
                amount = float(reward.get("amount") or 0)
                self._lock_gift_pack_stats(session, tg_id)
                mutation = credits_repository.add_tx(
                    session, CreditAccount.tg(int(tg_id)), amount
                )
                credits_service.register_cache_invalidation(session, mutation)
                snapshot.append(
                    {
                        "type": "credits",
                        "label": label,
                        "success": True,
                        "amount": amount,
                        "balance_after": mutation.after,
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

            elif reward_type == "wheel_free_spins":
                snapshot.append(
                    self._grant_wheel_free_spins_tx(session, tg_id, reward, label)
                )

            elif reward_type == "tournament_wallet":
                snapshot.append(
                    self._grant_tournament_wallet_tx(session, tg_id, reward, label)
                )

            elif reward_type in ("line_schedule_unlock", "download_unlock"):
                services = context["bound_services"]
                if not services:
                    # 正常情况下已被 require_binding 资格拦住，这里是最后一道防线
                    raise ValueError("请先绑定媒体账号后再领取")
                feature = (
                    "line_schedule"
                    if reward_type == "line_schedule_unlock"
                    else "download"
                )
                for service in services:
                    item = self._grant_feature_unlock_tx(
                        session, tg_id, service, feature
                    )
                    item["type"] = reward_type
                    item["label"] = label
                    snapshot.append(item)
                    if feature == "download" and not item.get("skipped"):
                        pending_download_sync.append(service)

            elif reward_type == "invite_codes":
                snapshot.append(
                    self._grant_invite_codes_tx(
                        session, tg_id, reward, label, pending_privileged_codes
                    )
                )

            else:
                raise ValueError(f"不支持的奖励类型: {reward_type}")

        return (
            snapshot,
            pending_permission_sync,
            pending_download_sync,
            pending_privileged_codes,
        )

    @staticmethod
    def _lock_gift_pack_stats(session, tg_id: int) -> Statistics:
        """锁住用户的 Statistics 行（积分与争霸赛余额分支共用）

        锁顺序与既有积分分支一致：先锁礼包，再锁 statistics。
        """
        stats = (
            session.execute(
                select(Statistics).where(Statistics.tg_id == tg_id).with_for_update()
            )
            .scalars()
            .one_or_none()
        )
        if not stats:
            raise ValueError("用户积分信息不存在")
        return stats

    @staticmethod
    def _grant_wheel_free_spins_tx(
        session, tg_id: int, reward: dict, label: str
    ) -> dict:
        """发放礼包来源的免费大转盘机会（source='gift_pack'）

        与 21 点来源写入同一张表：消耗、概览、到期提醒、角标无需改动；
        周上限、获得通知与对账按 source == 'blackjack' 过滤，不受影响。
        """
        count = int(reward.get("count") or 0)
        expiry_days = int(reward.get("expiry_days") or 0)
        if count <= 0 or expiry_days <= 0:
            raise ValueError("免费机会的次数与有效天数必须为正")
        now_ms = int(time.time() * 1000)
        expires_at_ms = now_ms + expiry_days * 86400 * 1000
        luckywheel_repository.grant_free_spins_tx(
            session,
            tg_id,
            count,
            source="gift_pack",
            granted_at_ms=now_ms,
            expires_at_ms=expires_at_ms,
            cost_credits=0,
            wheel_stats_source="gift_pack_free",
        )
        return {
            "type": "wheel_free_spins",
            "label": label,
            "success": True,
            "count": count,
            "days": expiry_days,
            "expires_at": expires_at_ms // 1000,
        }

    def _grant_tournament_wallet_tx(
        self, session, tg_id: int, reward: dict, label: str
    ) -> dict:
        """把数额计入争霸赛余额（不计入积分），复用积分分支的行锁"""
        amount = float(reward.get("amount") or 0)
        if amount <= 0:
            raise ValueError("争霸赛余额数量必须为正")
        stats = self._lock_gift_pack_stats(session, tg_id)
        stats.tournament_wallet_credits = round(
            float(stats.tournament_wallet_credits or 0) + amount, 2
        )
        return {
            "type": "tournament_wallet",
            "label": label,
            "success": True,
            "amount": amount,
            "balance_after": stats.tournament_wallet_credits,
        }

    # 功能解锁的永久标记列：(模型, 标记列, 解锁时间列)
    _GIFT_PACK_UNLOCK_COLUMNS: ClassVar[dict] = {
        ("line_schedule", "plex"): (
            PlexUser,
            "line_schedule_unlocked",
            "line_schedule_unlock_time",
        ),
        ("line_schedule", "emby"): (
            EmbyUser,
            "line_schedule_unlocked",
            "line_schedule_unlock_time",
        ),
        ("download", "plex"): (PlexUser, "sync_unlocked", "sync_unlock_time"),
        ("download", "emby"): (EmbyUser, "download_unlocked", "download_unlock_time"),
    }

    def _grant_feature_unlock_tx(
        self, session, tg_id: int, service: str, feature: str
    ) -> dict:
        """在调用方事务内为一个服务永久解锁线路调度 / 下载权限（只写数据库）

        「已拥有」直接读永久解锁标记列，而不是调 check_download_unlock：
        后者把 Premium 也算作已解锁，按它判断会让 Premium 用户永远拿不到
        永久解锁。已永久解锁的服务记为 skipped，不阻断领取。
        """
        key = (feature, service)
        if key not in self._GIFT_PACK_UNLOCK_COLUMNS:
            raise ValueError(f"不支持的解锁类型: {feature}/{service}")
        model, flag_col, time_col = self._GIFT_PACK_UNLOCK_COLUMNS[key]
        feature_name = "线路调度" if feature == "line_schedule" else "下载权限"
        service_name = service.capitalize()

        user = (
            session.execute(select(model).where(model.tg_id == tg_id).with_for_update())
            .scalars()
            .one_or_none()
        )
        if user is None:
            raise ValueError(f"未找到绑定的 {service_name} 账号")

        if int(getattr(user, flag_col) or 0) == 1:
            return {
                "success": True,
                "service": service,
                "skipped": "already_unlocked",
                "message": f"{service_name} 已解锁{feature_name}，本次未变更",
            }

        setattr(user, flag_col, 1)
        setattr(user, time_col, int(time.time()))
        return {
            "success": True,
            "service": service,
            "message": f"{service_name} 已永久解锁{feature_name}",
        }

    @staticmethod
    def _grant_invite_codes_tx(
        session,
        tg_id: int,
        reward: dict,
        label: str,
        pending_privileged_codes: list[str],
    ) -> dict:
        """在调用方事务内为用户生成邀请码（Invitation 行）

        与领取同生共死：事务回滚时不会留下可用的邀请码。
        uuid4().hex 与既有码同为 32 位十六进制，不会重复。
        """
        count = int(reward.get("count") or 0)
        if count <= 0:
            raise ValueError("邀请码数量必须为正")
        privileged = bool(reward.get("privileged"))
        codes = [uuid4().hex for _ in range(count)]
        for code in codes:
            session.add(Invitation(code=code, owner=tg_id, is_used=0))
        if privileged:
            pending_privileged_codes.extend(codes)
        session.flush()
        return {
            "type": "invite_codes",
            "label": label,
            "success": True,
            "count": count,
            "privileged": privileged,
            "codes": codes,
        }
