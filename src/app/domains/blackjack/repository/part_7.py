import json
import time

from sqlalchemy import func, select

from app.core.db import get_session
from app.core.kv import SystemConfig
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
        with get_session() as session:
            return self.settle_blackjack_tournament_tx(session, tournament_id)

    def settle_blackjack_tournament_tx(self, session, tournament_id: int) -> dict:
        from app.domains.blackjack import rules as engine

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
        ineligible = [e for e in entries if int(e.status) not in self.ENTRY_ELIGIBLE]

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
                        Statistics(tg_id=int(entry.tg_id), donation=0, credits=prize)
                    )
                prize_total = round(prize_total + prize, 2)

        # 无资格者不排名次、不派奖，但仍写 0 以示「已结算且无派奖」，
        # 与「尚未结算」的 NULL 区分开
        for entry in ineligible:
            entry.prize_credits = 0.0

        session.flush()

        standings = [self._tournament_entry_to_dict(e) for e in eligible + ineligible]
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

    def get_blackjack_config_tx(
        self, session, config_key: str = "config"
    ) -> str | None:
        return session.execute(
            select(SystemConfig.config_value).where(
                SystemConfig.config_type == "blackjack",
                SystemConfig.config_key == config_key,
            )
        ).scalar_one_or_none()

    def set_blackjack_config_tx(
        self, session, config_key: str, config_json: str
    ) -> bool:
        current_time = int(time.time())
        existing = (
            session.execute(
                select(SystemConfig)
                .where(
                    SystemConfig.config_type == "blackjack",
                    SystemConfig.config_key == config_key,
                )
                .with_for_update()
            )
            .scalars()
            .one_or_none()
        )
        if existing is None:
            session.add(
                SystemConfig(
                    config_type="blackjack",
                    config_key=config_key,
                    config_value=config_json,
                    created_at=current_time,
                    updated_at=current_time,
                )
            )
        else:
            existing.config_value = config_json
            existing.updated_at = current_time
        return True

    def get_blackjack_config_dict_tx(self, session) -> dict:
        raw = self.get_blackjack_config_tx(session, "config")
        config = dict(DEFAULT_BLACKJACK_CONFIG)
        if raw:
            try:
                stored = json.loads(raw)
                if isinstance(stored, dict):
                    config.update(stored)
            except Exception as e:
                logger.error(f"解析 21 点配置失败，回退默认配置: {e}")
        else:
            self.set_blackjack_config_tx(
                session, "config", json.dumps(config, ensure_ascii=False)
            )
        return config

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
