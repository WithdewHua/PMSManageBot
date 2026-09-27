"""礼包 repository：用户上下文、条件与受众的取数和求值（由 part_1–part_3 与门面机械拆分）。"""

from typing import ClassVar

from sqlalchemy import select

from app.domains.auction import repository as auction_repository
from app.domains.badges import repository as badges_repository
from app.domains.blackjack import repository as blackjack_repository
from app.domains.gift_pack import rules
from app.domains.gift_pack.exceptions import gift_pack_error
from app.domains.gift_pack.models import GiftPack, GiftPackUserState
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
from app.domains.invitation import repository as invitation_repository
from app.domains.luckywheel import repository as luckywheel_repository
from app.domains.prediction import repository as prediction_repository
from app.domains.treasure import repository as treasure_repository


class _GiftPackRepositoryConditions:
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
        if plex is not None and rules._is_premium_active(plex[0], plex[1]):
            premium_services.append("plex")
        if emby is not None and rules._is_premium_active(emby[0], emby[1]):
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
            "_tg_id": tg_id,
        }

    @staticmethod
    def _count_gift_pack_wheel_spins(
        session, tg_id: int, since: int, until: int, **qualifiers
    ) -> int:
        return luckywheel_repository.count_paid_spins_tx(
            session, tg_id, since, until, paid_only=qualifiers.get("paid_only", True)
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
        return invitation_repository.count_invitees_tx(session, tg_id, since, until)

    @staticmethod
    def _count_gift_pack_watched_hours(
        session, tg_id: int, since: int, until: int, **qualifiers
    ) -> float:
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

    def _gift_pack_metrics(
        self,
        session,
        tg_id: int,
        items: list[dict] | None,
        pack: GiftPack,
        ref: int,
        metrics: dict | None = None,
    ) -> dict:
        """按 rules.required_metrics 预取条件计数（同一窗口只查一次）

        求值本身在 rules 里，纯函数；这里只负责把需要的计数取回来。
        """
        collected = metrics if metrics is not None else {}
        for key in rules.required_metrics(items, pack, ref):
            if key in collected:
                continue
            metric, since, until, qualifiers = key
            method = getattr(self, self._GIFT_PACK_COUNT_METHODS[metric])
            collected[key] = method(session, tg_id, since, until, **dict(qualifiers))
        return collected

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
        if not pack.is_enabled or rules._gift_pack_lifecycle(pack, now) not in (
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
        audience, _ = rules._resolve_gift_pack_conditions(pack)
        ref = rules._gift_pack_phase_ref(pack, now)
        metrics = self._gift_pack_metrics(session, tg_id, audience, pack, ref)
        visible = rules._evaluate_gift_pack_audience(
            audience, ctx, pack, ref, state, metrics=metrics
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
            return (True, [])
        reasons: list[str] = []
        min_credits = eligibility.get("min_credits")
        if min_credits is not None and context["credits"] < float(min_credits):
            gap = float(min_credits) - context["credits"]
            reasons.append(
                f"积分不足，还差 {gap:.2f} 积分（需要 {float(min_credits):.2f}）"
            )
        if eligibility.get("require_premium") and (not context["premium_services"]):
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
        return (not reasons, reasons)

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
