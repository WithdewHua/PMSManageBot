"""21 点 repository：争霸赛余额（由 part_N 机械拆分）。"""

from sqlalchemy import Numeric, cast, func, select, update

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
                # PostgreSQL 没有 round(double precision, integer)，必须先把
                # 浮点表达式转成 NUMERIC 再取两位，否则整个更新语句会报
                # UndefinedFunction（SQLite 的 round 太宽松，掩盖了这个差异）。
                tournament_wallet_credits=func.round(
                    cast(
                        Statistics.tournament_wallet_credits + (after - before),
                        Numeric,
                    ),
                    2,
                )
            )
        )
        return after

    def _move_tournament_wallet(self, session, old_tg_id: int, new_tg_id: int) -> float:
        """在调用方事务内转移争霸赛余额及计数器，返回转移的余额。

        按 TG ID 升序取行锁（与 credits 锁序一致），对源和目标均采用 SQL 增量更新，
        完整保留源浮点精度（不截断为两位小数），绝不使用源绝对写 0。
        """
        if int(old_tg_id) == int(new_tg_id):
            return 0.0

        ordered_ids = sorted((int(old_tg_id), int(new_tg_id)))
        for tid in ordered_ids:
            session.execute(
                select(Statistics).where(Statistics.tg_id == tid).with_for_update()
            )

        old_stats = session.get(Statistics, int(old_tg_id))
        new_stats = session.get(Statistics, int(new_tg_id))

        if new_stats is None:
            raise blackjack_error("用户积分信息不存在")

        if old_stats is None:
            return 0.0

        amount = float(old_stats.tournament_wallet_credits or 0.0)
        old_streak = int(old_stats.blackjack_lose_streak or 0)
        old_freespin = int(old_stats.blackjack_hands_since_freespin or 0)

        old_values = {}
        if amount != 0.0:
            old_values[Statistics.tournament_wallet_credits] = (
                Statistics.tournament_wallet_credits - amount
            )
        if old_streak != 0:
            old_values[Statistics.blackjack_lose_streak] = (
                Statistics.blackjack_lose_streak - old_streak
            )
        if old_freespin != 0:
            old_values[Statistics.blackjack_hands_since_freespin] = (
                Statistics.blackjack_hands_since_freespin - old_freespin
            )

        if old_values:
            session.execute(
                update(Statistics)
                .where(Statistics.tg_id == int(old_tg_id))
                .values(old_values)
            )

        new_values = {}
        if amount != 0.0:
            new_values[Statistics.tournament_wallet_credits] = (
                Statistics.tournament_wallet_credits + amount
            )
        if old_streak != 0:
            new_values[Statistics.blackjack_lose_streak] = (
                Statistics.blackjack_lose_streak + old_streak
            )
        if old_freespin != 0:
            new_values[Statistics.blackjack_hands_since_freespin] = (
                Statistics.blackjack_hands_since_freespin + old_freespin
            )

        if new_values:
            session.execute(
                update(Statistics)
                .where(Statistics.tg_id == int(new_tg_id))
                .values(new_values)
            )

        return amount

    move_tournament_wallet_tx = _move_tournament_wallet


def _move_tournament_wallet_module(session, old_tg_id: int, new_tg_id: int) -> float:
    return _BlackjackRepositoryWallet()._move_tournament_wallet(
        session, old_tg_id, new_tg_id
    )


move_tournament_wallet_tx = _move_tournament_wallet_module
