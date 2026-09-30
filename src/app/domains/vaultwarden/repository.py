"""Database queries and transactions for Vaultwarden redemption records."""

from __future__ import annotations

from datetime import datetime
from time import time
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import get_session
from app.domains.vaultwarden.models import VaultwardenRedeemRecords

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def record_redemption_tx(
    session: Session,
    *,
    tg_id: int,
    email: str,
    credits_cost: float,
    redeem_date: str,
    created_at: int,
) -> VaultwardenRedeemRecords:
    """Record a Vaultwarden redemption inside the caller's active database transaction."""
    record = VaultwardenRedeemRecords(
        tg_id=tg_id,
        email=email,
        credits_cost=float(credits_cost),
        redeem_date=redeem_date,
        created_at=int(created_at),
    )
    session.add(record)
    return record


def record_redemption(
    *,
    tg_id: int,
    email: str,
    credits_cost: float,
    redeem_date: str | None = None,
    created_at: int | None = None,
) -> VaultwardenRedeemRecords:
    """Record a Vaultwarden redemption in a dedicated standalone transaction."""
    if redeem_date is None:
        redeem_date = datetime.now(settings.TZ).strftime("%Y-%m-%d %H:%M:%S")
    if created_at is None:
        created_at = int(time())

    with get_session() as session:
        record = record_redemption_tx(
            session,
            tg_id=tg_id,
            email=email,
            credits_cost=credits_cost,
            redeem_date=redeem_date,
            created_at=created_at,
        )
        session.commit()
        session.refresh(record)
        session.expunge(record)
        return record


def count_redemptions_tx(session: Session) -> int:
    """Count total Vaultwarden redemptions inside caller transaction."""
    stmt = select(func.count(VaultwardenRedeemRecords.id))
    return int(session.execute(stmt).scalar() or 0)


def count_redemptions() -> int:
    """Count total Vaultwarden redemptions in a standalone transaction."""
    with get_session() as session:
        return count_redemptions_tx(session)


def list_records_by_tg_id_tx(
    session: Session, tg_id: int
) -> list[VaultwardenRedeemRecords]:
    """List redemption records for a user inside caller transaction."""
    stmt = (
        select(VaultwardenRedeemRecords)
        .where(VaultwardenRedeemRecords.tg_id == tg_id)
        .order_by(VaultwardenRedeemRecords.created_at.desc())
    )
    return list(session.execute(stmt).scalars().all())


def list_records_by_tg_id(tg_id: int) -> list[VaultwardenRedeemRecords]:
    """List redemption records for a user in a standalone transaction."""
    with get_session() as session:
        records = list_records_by_tg_id_tx(session, tg_id)
        session.expunge_all()
        return records


__all__ = [
    "count_redemptions",
    "count_redemptions_tx",
    "list_records_by_tg_id",
    "list_records_by_tg_id_tx",
    "record_redemption",
    "record_redemption_tx",
]
