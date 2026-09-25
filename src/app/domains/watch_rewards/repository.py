import time

from sqlalchemy import func, select, update

from app.core.db import get_session
from app.core.log import logger
from app.domains.watch_rewards.models import GhostSessionLog


class WatchRewardsRepository:
    def get_logged_ghost_row_ids(self, row_ids: list[int]) -> set:
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

    def get_undeleted_ghost_row_ids(self) -> list[int]:
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

    def mark_ghost_sessions_deleted(self, row_ids: list[int]) -> bool:
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

    def get_pending_ghost_compensation(self) -> dict[str, float]:
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
