"""21 点 repository：争霸赛余额（由 part_N 机械拆分）。"""

from sqlalchemy import func, select, update

from app.core.db import get_session
from app.core.log import logger
from app.domains.blackjack.exceptions import blackjack_error
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

    def credit_tournament_wallet_tx(self, session, tg_id: int, amount: float) -> float:
        """在调用方事务内给争霸赛余额记一笔，返回记完后的余额。

        争霸赛余额是 blackjack 拥有的列（见 docs/architecture.md 宽表列归属），
        所以跨领域的礼包奖励只通过这里写入：行锁 + SQL 增量 + 两位小数舍入，
        与 credits 的 add_tx 同一种写法，调用方回滚时一并回滚。
        """
        delta = round(float(amount), 2)
        if delta <= 0:
            raise blackjack_error("争霸赛余额数量必须为正")
        stats = (
            session.execute(
                select(Statistics)
                .where(Statistics.tg_id == int(tg_id))
                .with_for_update()
            )
            .scalars()
            .one_or_none()
        )
        if stats is None:
            raise blackjack_error("用户积分信息不存在")
        before = round(float(stats.tournament_wallet_credits or 0), 2)
        after = round(before + delta, 2)
        session.execute(
            update(Statistics)
            .where(Statistics.tg_id == int(tg_id))
            .values(
                tournament_wallet_credits=func.round(
                    Statistics.tournament_wallet_credits + (after - before), 2
                )
            )
        )
        return after
