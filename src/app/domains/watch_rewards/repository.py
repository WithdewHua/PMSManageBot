import time

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.log import logger
from app.domains.watch_rewards.models import GhostSessionLog, WatchRewardSettlement


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
        """Return pending compensation hours keyed by Plex account ID."""
        return {
            user_id: value["hours"]
            for user_id, value in get_pending_ghost_compensation_rows().items()
        }


def get_pending_ghost_compensation_rows() -> dict[str, dict]:
    """Return pending hours and exact source row IDs grouped by Plex user."""
    with get_session() as session:
        stmt = select(
            GhostSessionLog.user_id,
            GhostSessionLog.row_id,
            GhostSessionLog.compensated_seconds,
        ).where(
            GhostSessionLog.compensated == 0,
            GhostSessionLog.deleted == 1,
        )
        grouped: dict[str, dict] = {}
        for user_id, row_id, seconds in session.execute(stmt).all():
            entry = grouped.setdefault(str(user_id), {"hours": 0.0, "row_ids": []})
            entry["hours"] += float(seconds or 0) / 3600
            entry["row_ids"].append(int(row_id))
        return grouped


def insert_watch_reward_settlement_tx(
    session: Session,
    *,
    service: str,
    account_key: str,
    settlement_date: str,
    tg_id: int | None,
    credits_delta: float,
    premium_charge: float,
    inviter_tg_id: int | None,
    inviter_bonus: float,
    created_at: int,
) -> bool:
    """Reserve a daily settlement key inside the caller-owned transaction."""
    values = {
        "service": service,
        "account_key": str(account_key),
        "settlement_date": settlement_date,
        "tg_id": tg_id,
        "credits_delta": credits_delta,
        "premium_charge": premium_charge,
        "inviter_tg_id": inviter_tg_id,
        "inviter_bonus": inviter_bonus,
        "created_at": created_at,
    }
    try:
        with session.begin_nested():
            if session.bind.dialect.name == "sqlite":
                current = session.execute(
                    select(func.max(WatchRewardSettlement.id))
                ).scalar_one()
                values["id"] = int(current or 0) + 1
            session.add(WatchRewardSettlement(**values))
            session.flush()
        return True
    except IntegrityError:
        return False


def mark_ghost_compensation_rows_tx(session: Session, row_ids: list[int]) -> None:
    """Mark only this user's snapshotted ghost rows inside their settlement."""
    if not row_ids:
        return
    session.execute(
        update(GhostSessionLog)
        .where(
            GhostSessionLog.row_id.in_(row_ids),
            GhostSessionLog.compensated == 0,
            GhostSessionLog.deleted == 1,
        )
        .values(compensated=1)
    )
