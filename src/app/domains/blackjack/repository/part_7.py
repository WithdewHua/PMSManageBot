import json

from sqlalchemy import func, select

from app.core.db import get_session
from app.core.log import logger
from app.domains.blackjack.exceptions import blackjack_error
from app.domains.blackjack.models import (
    BlackjackHand,
    BlackjackTournament,
    BlackjackTournamentEntry,
)
from app.domains.credits import repository as credits_repository
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import Statistics

from . import (
    DEFAULT_BLACKJACK_CONFIG,
)


class _BlackjackRepositoryPart7:
    def _compute_tournament_payouts(
        self, eligible_count: int, structure: list, net_pool: float
    ) -> list:
        from app.domains.blackjack import rules

        return rules.calculate_tournament_payouts(eligible_count, structure, net_pool)

    def settle_blackjack_tournament(self, tournament_id: int) -> dict:
        """完赛结算：排名 → 派奖 → 返回冠军以待授勋。

        **调用方必须先调 `force_settle_tournament_hands()` 清场**：排名要读终局
        筹码，而一手在局的牌意味着押注已从 chips 扣除、赔付尚未计入，其持有者的
        筹码被低估。

        幂等由 `2 → 3` 的 CAS 保证：抢不到的一方一分钱不派、一个勋章不发。

        排名口径：仅取具备派奖资格者（已打完或已淘汰），按筹码降序、报名时点
        升序决胜。**未打满且未被淘汰者不参与派奖，其报名费留在奖池中**——21 点
        接近零期望，不设这道门的话「报名后什么都不做」就是占优策略。

        锁序 tournament → entry → statistics。赛事行先用 `_lock_running_tournament`
        钉住，再在本事务里确认没有未终结手牌，然后才 CAS。tick 的清场与本方法
        之间仍可能有发牌提交；扫到未终结手牌则本轮不派奖，留给下一分钟先清场。

        Returns: {settled(bool), tournament, standings, champion_tg_id, prize_total}
        """
        from app.domains.blackjack import rules as engine

        with get_session() as session:
            tournament = self._lock_running_tournament(session, int(tournament_id))
            if not tournament:
                existing = (
                    session.execute(
                        select(BlackjackTournament).where(
                            BlackjackTournament.id == int(tournament_id)
                        )
                    )
                    .scalars()
                    .one_or_none()
                )
                if not existing:
                    raise blackjack_error("tournament not found")
                return {
                    "settled": False,
                    "tournament": self._tournament_to_dict(existing),
                    "standings": [],
                    "champion_tg_id": None,
                    "prize_total": 0.0,
                }

            pending = session.execute(
                select(func.count())
                .select_from(BlackjackHand)
                .where(
                    BlackjackHand.tournament_id == int(tournament_id),
                    BlackjackHand.status.notin_(engine.TERMINAL_STATUSES),
                )
            ).scalar_one()
            if int(pending) > 0:
                return {
                    "settled": False,
                    "tournament": self._tournament_to_dict(tournament),
                    "standings": [],
                    "champion_tg_id": None,
                    "prize_total": 0.0,
                }

            snapshot = self._tournament_to_dict(tournament)

            # 先抢占：抢不到说明已被他人结算，绝不能继续派奖
            if not self._claim_tournament_transition(
                session,
                int(tournament_id),
                self.TOURNAMENT_RUNNING,
                self.TOURNAMENT_SETTLED,
            ):
                session.expire(tournament)
                return {
                    "settled": False,
                    "tournament": self._tournament_to_dict(tournament),
                    "standings": [],
                    "champion_tg_id": None,
                    "prize_total": 0.0,
                }
            session.expire(tournament)

            entries = (
                session.execute(
                    select(BlackjackTournamentEntry)
                    .where(BlackjackTournamentEntry.tournament_id == int(tournament_id))
                    .with_for_update()
                    .order_by(
                        BlackjackTournamentEntry.chips.desc(),
                        BlackjackTournamentEntry.registered_at_ms.asc(),
                    )
                )
                .scalars()
                .all()
            )

            eligible = [e for e in entries if int(e.status) in self.ENTRY_ELIGIBLE]
            ineligible = [
                e for e in entries if int(e.status) not in self.ENTRY_ELIGIBLE
            ]

            # 奖池按报名数推导（含无资格者的报名费——他们的钱留在池子里）
            net_pool = snapshot["prize_pool_net"]
            payouts = self._compute_tournament_payouts(
                len(eligible), snapshot["payout_structure"], net_pool
            )

            prize_total = 0.0
            for i, entry in enumerate(eligible):
                entry.final_rank = i + 1
                prize = float(payouts[i]) if i < len(payouts) else 0.0
                entry.prize_credits = prize
                if prize > 0:
                    stats = (
                        session.execute(
                            select(Statistics)
                            .where(Statistics.tg_id == int(entry.tg_id))
                            .with_for_update()
                        )
                        .scalars()
                        .one_or_none()
                    )
                    if stats:
                        mutation = credits_repository.add_tx(
                            session, CreditAccount.tg(int(entry.tg_id)), prize
                        )
                        credits_service.register_cache_invalidation(session, mutation)
                    else:
                        session.add(
                            Statistics(
                                tg_id=int(entry.tg_id), donation=0, credits=prize
                            )
                        )
                    prize_total = round(prize_total + prize, 2)

            # 无资格者不排名次、不派奖，但仍写 0 以示「已结算且无派奖」，
            # 与「尚未结算」的 NULL 区分开
            for entry in ineligible:
                entry.prize_credits = 0.0

            session.flush()

            standings = [
                self._tournament_entry_to_dict(e) for e in eligible + ineligible
            ]
            champion = int(eligible[0].tg_id) if eligible else None

            logger.info(
                f"21 点锦标赛 {tournament_id} 已结算：{len(eligible)} 人具备资格"
                f"（{len(ineligible)} 人未完赛），派奖合计 {prize_total} 积分"
            )
            return {
                "settled": True,
                "tournament": self._tournament_to_dict(tournament),
                "standings": standings,
                "champion_tg_id": champion,
                "prize_total": prize_total,
            }

    def get_blackjack_config(self, config_key: str = "config") -> str | None:
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
