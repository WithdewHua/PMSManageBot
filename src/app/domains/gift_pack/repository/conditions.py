"""礼包 repository：用户上下文、条件与受众的取数和求值（由 part_1–part_3 与门面机械拆分）。"""

import json
from datetime import datetime
from typing import ClassVar

from sqlalchemy import select

from app.core.config import settings
from app.domains.auction import repository as auction_repository
from app.domains.badges import repository as badges_repository
from app.domains.blackjack import repository as blackjack_repository
from app.domains.gift_pack.exceptions import gift_pack_error
from app.domains.gift_pack.models import GiftPack, GiftPackUserState
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
from app.domains.invitation import repository as invitation_repository
from app.domains.luckywheel import repository as luckywheel_repository
from app.domains.prediction import repository as prediction_repository
from app.domains.treasure import repository as treasure_repository

from . import (
    _format_gift_pack_number,
    gift_pack_rewards_require_binding,
)


class _GiftPackRepositoryConditions:
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

        badge_ids = badges_repository.active_badge_ids_tx(session, tg_id)
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
    def _count_gift_pack_wheel_spins(
        session, tg_id: int, since: int, until: int, **qualifiers
    ) -> int:
        return luckywheel_repository.count_paid_spins_tx(
            session,
            tg_id,
            since,
            until,
            paid_only=qualifiers.get("paid_only", True),
        )

    @staticmethod
    def _count_gift_pack_blackjack_hands(
        session, tg_id: int, since: int, until: int, **qualifiers
    ) -> int | tuple[int, float]:
        return blackjack_repository.cash_hand_metrics_tx(
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
        return treasure_repository.count_participated_issues_tx(
            session, tg_id, since, until
        )

    @staticmethod
    def _count_gift_pack_prediction_bets(
        session, tg_id: int, since: int, until: int, **qualifiers
    ) -> int:
        return prediction_repository.count_bets_tx(session, tg_id, since, until)

    @staticmethod
    def _count_gift_pack_auction_participations(
        session, tg_id: int, since: int, until: int, **qualifiers
    ) -> int:
        return auction_repository.count_participated_auctions_tx(
            session, tg_id, since, until
        )

    @staticmethod
    def _count_gift_pack_tournament_entries(
        session, tg_id: int, since: int, until: int, **qualifiers
    ) -> int:
        return blackjack_repository.count_tournament_entries_tx(
            session, tg_id, since, until
        )

    @staticmethod
    def _count_gift_pack_invitees(
        session, tg_id: int, since: int, until: int, **qualifiers
    ) -> int:
        # 邀请码没有事件时间，只按“全部时间”统计
        return invitation_repository.count_invitees_tx(session, tg_id, since, until)

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
            raise gift_pack_error(f"不支持的礼包条件: {kind}")
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
            raise gift_pack_error("用户积分信息不存在")
        return stats

    @staticmethod
    def _gift_pack_conditions_with_binding(
        requirements: list[dict], rewards: list[dict]
    ) -> list[dict]:
        result = list(requirements or [])
        if gift_pack_rewards_require_binding(rewards) and not any(
            item["type"] == "bound" for item in result
        ):
            result.append({"type": "bound", "service": "any"})
        return result

    @staticmethod
    def _gift_pack_audience_size(audience: list[dict]) -> int | None:
        include = [
            set(item["tg_ids"])
            for item in audience
            if item["type"] == "user_list" and item["mode"] == "include"
        ]
        if not include:
            return None
        members = set.intersection(*include)
        for item in audience:
            if item["type"] == "user_list" and item["mode"] == "exclude":
                members.difference_update(item["tg_ids"])
        return len(members)

    @staticmethod
    def _legacy_gift_pack_requirements(legacy: dict) -> list[dict]:
        result = []
        if legacy.get("min_credits") is not None:
            result.append({"type": "credits", "min": legacy["min_credits"]})
        if legacy.get("require_premium"):
            result.append({"type": "premium", "state": "active"})
        if legacy.get("require_binding"):
            result.append({"type": "bound", "service": legacy["require_binding"]})
        return result

    @staticmethod
    def _resolve_gift_pack_conditions(pack: GiftPack) -> tuple[list[dict], list[dict]]:
        """Read new condition JSON, or adapt an unmigrated legacy eligibility row."""
        audience = json.loads(pack.audience) if pack.audience else []
        if pack.requirements:
            requirements = json.loads(pack.requirements)
        else:
            legacy = json.loads(pack.eligibility) if pack.eligibility else {}
            requirements = []
            if legacy.get("min_credits") is not None:
                requirements.append({"type": "credits", "min": legacy["min_credits"]})
            if legacy.get("require_premium"):
                requirements.append({"type": "premium", "state": "active"})
            if legacy.get("require_binding"):
                requirements.append(
                    {"type": "bound", "service": legacy["require_binding"]}
                )
        return audience, requirements

    @staticmethod
    def _gift_pack_condition_label(item: dict) -> str:
        """Keep all user-facing and admin condition wording in one place."""
        kind = item["type"]
        labels = {
            "wheel_spins": "付费转盘" if item.get("paid_only", True) else "转盘",
            "blackjack_hands": "21 点",
            "treasure_issues": "夺宝参与期数",
            "prediction_bets": "大预言家下注",
            "auction_participations": "竞拍参与场数",
            "tournament_entries": "锦标赛参赛",
            "invitees": "邀请人数",
            "watched_hours": "累计观看时长（小时）",
        }
        if kind in labels:
            window = item.get("window") or {"kind": "all"}
            prefix = (
                "礼包开始后"
                if window["kind"] == "pack"
                else f"最近 {window['days']} 天 "
                if window["kind"] == "days"
                else ""
            )
            suffix = ""
            if kind == "blackjack_hands" and item.get("min_bet") is not None:
                suffix = f"（每手 ≥ {_format_gift_pack_number(item['min_bet'])}）"
            return f"{prefix}{labels[kind]}{suffix}"
        if kind == "credits":
            if item.get("max") is not None:
                if item.get("min") is not None:
                    return f"积分（{_format_gift_pack_number(item['min'])}–{_format_gift_pack_number(item['max'])}）"
                return f"积分（不超过 {_format_gift_pack_number(item['max'])}）"
            return "积分"
        if kind == "premium":
            return (
                "需要 Premium 身份" if item["state"] == "active" else "无 Premium 身份"
            )
        if kind == "bound":
            service = item.get("service", "any")
            return (
                f"绑定 {service.capitalize()} 账号"
                if service != "any"
                else "绑定 Plex 或 Emby 账号"
            )
        if kind == "badge":
            return f"持有勋章 #{item['badge_id']}"
        if kind == "claimed_pack":
            return f"已领取礼包 #{item['pack_id']}"
        if kind == "user_list":
            return "包含名单" if item["mode"] == "include" else "排除名单"
        raise gift_pack_error(f"不支持的礼包条件: {kind}")

    @staticmethod
    def _gift_pack_condition_summary(items: list[dict]) -> str:
        def label(item: dict) -> str:
            if item["type"] == "any_of":
                return (
                    "（" + " 或 ".join(label(child) for child in item["items"]) + "）"
                )
            text = _GiftPackRepositoryConditions._gift_pack_condition_label(item)
            target = item.get("min")
            if target is not None:
                number = _format_gift_pack_number(target)
                unit = {
                    "wheel_spins": " 次",
                    "blackjack_hands": " 手",
                    "treasure_issues": " 期",
                    "prediction_bets": " 次",
                    "auction_participations": " 场",
                    "tournament_entries": " 次",
                    "invitees": " 人",
                    "watched_hours": " 小时",
                }.get(item["type"])
                text += f" {number}{unit}" if unit else f" ≥ {number}"
            return text

        return " 且 ".join(label(item) for item in items or [])
