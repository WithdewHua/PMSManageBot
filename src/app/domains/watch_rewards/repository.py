"""Persistence boundary for watch reward settlement."""

from __future__ import annotations

import time

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.log import logger
from app.domains.credits import repository as credits_repository
from app.domains.credits.types import CreditAccount
from app.domains.identity import repository as identity_repository
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
from app.domains.identity.types import TgIdReassignIssue
from app.domains.premium import repository as premium_repository
from app.domains.watch_rewards.models import GhostSessionLog, WatchRewardSettlement


def list_plex_accounts() -> list[dict]:
    with get_session() as session:
        rows = session.execute(
            select(PlexUser).where(PlexUser.plex_id.isnot(None))
        ).scalars()
        return [
            {
                "plex_id": row.plex_id,
                "credits": row.credits,
                "watched_time": row.watched_time,
                "tg_id": row.tg_id,
                "username": row.plex_username,
                "is_premium": row.is_premium,
                "premium_status_updated_at": row.premium_status_updated_at,
                "premium_traffic_debt_bytes": row.premium_traffic_debt_bytes,
                "premium_traffic_debt_updated_date": row.premium_traffic_debt_updated_date,
            }
            for row in rows
        ]


def list_emby_accounts() -> list[dict]:
    with get_session() as session:
        rows = session.execute(select(EmbyUser)).scalars()
        return [
            {
                "emby_id": row.emby_id,
                "tg_id": row.tg_id,
                "watched_time": row.emby_watched_time,
                "credits": row.emby_credits,
                "username": row.emby_username,
                "is_premium": row.is_premium,
                "premium_status_updated_at": row.premium_status_updated_at,
                "premium_traffic_debt_bytes": row.premium_traffic_debt_bytes,
                "premium_traffic_debt_updated_date": row.premium_traffic_debt_updated_date,
            }
            for row in rows
        ]


def get_logged_ghost_row_ids(row_ids: list[int]) -> set[int]:
    if not row_ids:
        return set()
    try:
        with get_session() as session:
            return set(
                session.execute(
                    select(GhostSessionLog.row_id).where(
                        GhostSessionLog.row_id.in_(row_ids)
                    )
                ).scalars()
            )
    except Exception as error:
        logger.error(f"查询已留档的幽灵会话失败: {error}")
        return set(row_ids)


def add_ghost_session_log(record: dict) -> bool:
    try:
        with get_session() as session:
            session.add(
                GhostSessionLog(
                    row_id=record["row_id"],
                    user_id=str(record["user_id"]),
                    friendly_name=record.get("friendly_name"),
                    title=record.get("title"),
                    rating_key=str(record["rating_key"])
                    if record.get("rating_key") is not None
                    else None,
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
    except Exception as error:
        logger.error(f"留档幽灵会话 row_id={record.get('row_id')} 失败: {error}")
        return False


def get_undeleted_ghost_row_ids() -> list[int]:
    try:
        with get_session() as session:
            return list(
                session.execute(
                    select(GhostSessionLog.row_id).where(GhostSessionLog.deleted == 0)
                ).scalars()
            )
    except Exception as error:
        logger.error(f"查询未删除的幽灵会话失败: {error}")
        return []


def mark_ghost_sessions_deleted(row_ids: list[int]) -> bool:
    if not row_ids:
        return True
    try:
        with get_session() as session:
            session.execute(
                update(GhostSessionLog)
                .where(GhostSessionLog.row_id.in_(row_ids))
                .values(deleted=1)
            )
            return True
    except Exception as error:
        logger.error(f"标记幽灵会话已删除失败: {error}")
        return False


def get_pending_ghost_compensation_rows() -> dict[str, dict]:
    with get_session() as session:
        rows = session.execute(
            select(
                GhostSessionLog.user_id,
                GhostSessionLog.row_id,
                GhostSessionLog.compensated_seconds,
            ).where(GhostSessionLog.compensated == 0, GhostSessionLog.deleted == 1)
        ).all()
        grouped: dict[str, dict] = {}
        for user_id, row_id, seconds in rows:
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
    # sqlite3 legacy transaction control does not BEGIN for SELECT. Without
    # an outer DB transaction, releasing the savepoint commits the claim even
    # when later balance/debt writes roll back.
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        driver = connection.connection.driver_connection
        if not driver.in_transaction:
            connection.exec_driver_sql("BEGIN")
    try:
        with session.begin_nested():
            if session.bind.dialect.name == "sqlite":
                values["id"] = (
                    int(
                        session.execute(
                            select(func.max(WatchRewardSettlement.id))
                        ).scalar_one()
                        or 0
                    )
                    + 1
                )
            session.add(WatchRewardSettlement(**values))
            session.flush()
        return True
    except IntegrityError:
        return False


def settle_user_tx(
    session: Session,
    *,
    service: str,
    account_key: str,
    settlement_date: str,
    account: CreditAccount,
    tg_id: int | None,
    inviter_tg_id: int | None,
    inviter_bonus: float,
    credits_delta: float,
    premium_charge: float,
    watched_value: float,
    debt_bytes: int,
    debt_updated_date: str | None,
    ghost_row_ids: list[int],
    transfer_unbound_balance: bool = False,
) -> dict | None:
    """Settle one account atomically in the caller-owned session."""
    model = PlexUser if service == "plex" else EmbyUser
    key_column = PlexUser.plex_id if service == "plex" else EmbyUser.emby_id
    media_id = int(account_key) if service == "plex" else str(account_key)
    watched_column = (
        PlexUser.watched_time if service == "plex" else EmbyUser.emby_watched_time
    )
    media_row = session.execute(
        select(model).where(key_column == media_id).with_for_update()
    ).scalar_one_or_none()
    if media_row is None:
        raise RuntimeError(f"{service} account {account_key} disappeared")

    effective_inviter = inviter_tg_id if inviter_bonus > 0 else None
    user_stats_exists = (
        tg_id is not None
        and session.execute(
            select(Statistics.tg_id).where(Statistics.tg_id == int(tg_id))
        ).scalar_one_or_none()
        is not None
    )
    inviter_ids = []
    if effective_inviter is not None:
        inviter_exists = session.execute(
            select(Statistics.tg_id).where(Statistics.tg_id == int(effective_inviter))
        ).scalar_one_or_none()
        if inviter_exists is None:
            effective_inviter = None
            inviter_bonus = 0.0
        else:
            inviter_ids.append(int(effective_inviter))

    for stats_id in sorted(
        {int(value) for value in (tg_id, *inviter_ids) if value is not None}
    ):
        if stats_id == tg_id and not user_stats_exists:
            identity_repository.ensure_statistics_tx(session, stats_id)
        else:
            session.execute(
                select(Statistics.tg_id)
                .where(Statistics.tg_id == stats_id)
                .with_for_update()
            ).scalar_one()

    if not insert_watch_reward_settlement_tx(
        session,
        service=service,
        account_key=account_key,
        settlement_date=settlement_date,
        tg_id=tg_id,
        credits_delta=credits_delta,
        premium_charge=premium_charge,
        inviter_tg_id=effective_inviter,
        inviter_bonus=inviter_bonus,
        created_at=int(time.time()),
    ):
        return None

    if transfer_unbound_balance and tg_id is not None and not user_stats_exists:
        credits_repository.move_tx(
            session, CreditAccount.emby(account_key), CreditAccount.tg(int(tg_id))
        )
    credits_repository.add_tx(session, account, credits_delta)
    charge_mutation = credits_repository.charge_premium_traffic_tx(
        session, account, premium_charge
    )

    inviter_balance = None
    if effective_inviter is not None and inviter_bonus > 0:
        inviter_balance = credits_repository.add_tx(
            session, CreditAccount.tg(int(effective_inviter)), inviter_bonus
        ).after

    setattr(media_row, watched_column.key, watched_value)
    debt_account = (
        CreditAccount.plex(int(media_id))
        if service == "plex"
        else CreditAccount.emby(str(media_row.emby_username))
    )
    premium_repository.update_traffic_debt_tx(
        session,
        debt_account,
        debt_bytes=int(debt_bytes),
        updated_date=debt_updated_date,
    )
    session.flush()
    mark_ghost_compensation_rows_tx(session, ghost_row_ids)
    balance = charge_mutation.after
    return {
        "balance": balance,
        "inviter_tg_id": effective_inviter,
        "inviter_balance": inviter_balance,
    }


def settle_user(
    *,
    service: str,
    account_key: str,
    settlement_date: str,
    account: CreditAccount,
    tg_id: int | None,
    inviter_tg_id: int | None,
    inviter_bonus: float,
    credits_delta: float,
    premium_charge: float,
    watched_value: float,
    debt_bytes: int,
    debt_updated_date: str | None,
    ghost_row_ids: list[int],
    transfer_unbound_balance: bool = False,
) -> dict | None:
    with get_session() as session:
        return settle_user_tx(
            session,
            service=service,
            account_key=account_key,
            settlement_date=settlement_date,
            account=account,
            tg_id=tg_id,
            inviter_tg_id=inviter_tg_id,
            inviter_bonus=inviter_bonus,
            credits_delta=credits_delta,
            premium_charge=premium_charge,
            watched_value=watched_value,
            debt_bytes=debt_bytes,
            debt_updated_date=debt_updated_date,
            ghost_row_ids=ghost_row_ids,
            transfer_unbound_balance=transfer_unbound_balance,
        )


def mark_ghost_compensation_rows_tx(session: Session, row_ids: list[int]) -> None:
    if row_ids:
        session.execute(
            update(GhostSessionLog)
            .where(
                GhostSessionLog.row_id.in_(row_ids),
                GhostSessionLog.compensated == 0,
                GhostSessionLog.deleted == 1,
            )
            .values(compensated=1)
        )


class WatchRewardsRepository:
    """Legacy method-shaped adapter retained for compatibility."""

    get_logged_ghost_row_ids = staticmethod(get_logged_ghost_row_ids)
    add_ghost_session_log = staticmethod(add_ghost_session_log)
    get_undeleted_ghost_row_ids = staticmethod(get_undeleted_ghost_row_ids)
    mark_ghost_sessions_deleted = staticmethod(mark_ghost_sessions_deleted)

    def get_pending_ghost_compensation(self) -> dict[str, float]:
        return {
            user_id: value["hours"]
            for user_id, value in get_pending_ghost_compensation_rows().items()
        }


REASSIGNED_TG_ID_COLUMNS: tuple[str, ...] = (
    "watch_reward_settlement.tg_id",
    "watch_reward_settlement.inviter_tg_id",
)


def check_tg_id_reassign_tx(
    session: Session, old_tg_id: int, new_tg_id: int
) -> list[TgIdReassignIssue]:
    return []


def reassign_tg_id_tx(
    session: Session, old_tg_id: int, new_tg_id: int
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for model, column in (
        (WatchRewardSettlement, WatchRewardSettlement.tg_id),
        (WatchRewardSettlement, WatchRewardSettlement.inviter_tg_id),
    ):
        result = session.execute(
            update(model)
            .where(column == int(old_tg_id))
            .values({column: int(new_tg_id)})
        )
        counts[f"{model.__tablename__}.{column.key}"] = max(
            0, int(result.rowcount or 0)
        )
    return counts
