"""21 点 repository：争霸赛余额（由 part_N 机械拆分）。"""

from app.core.db import get_session
from app.core.log import logger
from app.domains.identity.models import Statistics


class _BlackjackRepositoryWallet:
    def get_blackjack_tournament_wallet(self, tg_id: int) -> float:
        """该用户的争霸赛余额（仅可支付锦标赛报名费）。"""
        try:
            with get_session() as session:
                stats = session.get(Statistics, int(tg_id))
                if stats is None:
                    return 0.0
                return round(float(stats.tournament_wallet_credits or 0), 2)
        except Exception as e:
            logger.error(f"读取争霸赛余额失败 (tg_id={tg_id}): {e}")
            return 0.0
