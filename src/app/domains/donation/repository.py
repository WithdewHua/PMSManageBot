"""Donation domain repository."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.donation import exceptions as donation_exceptions
from app.domains.donation.models import DonationRegistrations
from app.domains.identity import repository as identity_repository
from app.domains.identity.models import Statistics


def _registration_to_dict(
    result: DonationRegistrations | None,
) -> dict[str, Any] | None:
    if result is None:
        return None
    user_id = result.user_id
    processed_by = result.processed_by
    return {
        "id": result.id,
        "user_id": user_id,
        "payment_method": result.payment_method,
        "amount": result.amount,
        "note": result.note,
        "status": result.status,
        "admin_note": result.admin_note,
        "created_at": result.created_at,
        "processed_at": result.processed_at,
        "processed_by": processed_by,
        "is_donation_registration": bool(result.is_donation_registration),
        "username": str(user_id),
        "processed_by_username": str(processed_by) if processed_by else None,
    }


def add_donation_tx(session: Session, tg_id: int, amount: float) -> float:
    """Atomically increment a user's cumulative donation under row lock.

    Ensures the Statistics row exists via identity repository helper.
    Returns the updated cumulative donation amount.
    """
    amount_val = float(amount)
    if amount_val <= 0:
        raise ValueError("Donation amount must be positive")
    stats = identity_repository.ensure_statistics_tx(session, int(tg_id))
    before = float(stats.donation or 0.0)
    after = round(before + amount_val, 2)
    session.execute(
        update(Statistics)
        .where(Statistics.tg_id == int(tg_id))
        .values(donation=Statistics.donation + (after - before))
    )
    session.flush()
    return after


def create_donation_registration_tx(
    session: Session,
    user_id: int,
    payment_method: str,
    amount: float,
    note: str | None = None,
    is_donation_registration: bool = False,
) -> DonationRegistrations:
    """Create a donation registration inside caller's transaction."""
    created_at = datetime.now(settings.TZ).isoformat()
    # 确保统计信息存在以通过外键校验（通过 identity 领域 helper，不直接构造）
    identity_repository.ensure_statistics_tx(session, int(user_id))

    donation = DonationRegistrations(
        user_id=int(user_id),
        payment_method=payment_method,
        amount=round(float(amount), 2),
        note=note,
        created_at=created_at,
        is_donation_registration=int(is_donation_registration),
    )
    session.add(donation)
    session.flush()
    return donation


def create_donation_registration(
    user_id: int,
    payment_method: str,
    amount: float,
    note: str | None = None,
    is_donation_registration: bool = False,
) -> int | None:
    """Create a donation registration and return its committed row id."""
    try:
        with get_session() as session:
            donation = create_donation_registration_tx(
                session,
                user_id=int(user_id),
                payment_method=payment_method,
                amount=float(amount),
                note=note,
                is_donation_registration=bool(is_donation_registration),
            )
            return int(donation.id)
    except Exception as e:
        logger.error(f"创建捐赠登记失败: {e}")
        return None


def get_donation_registration_by_id(registration_id: int) -> dict | None:
    """根据ID获取捐赠登记信息"""
    try:
        with get_session() as session:
            stmt = select(DonationRegistrations).where(
                DonationRegistrations.id == int(registration_id)
            )
            result = session.execute(stmt).scalar_one_or_none()
            return _registration_to_dict(result)
    except Exception as e:
        logger.error(f"获取捐赠登记信息失败: {e}")
        return None


def get_donation_registrations_by_user(user_id: int, limit: int = 20) -> list[dict]:
    """获取用户的捐赠登记历史"""
    try:
        with get_session() as session:
            stmt = (
                select(DonationRegistrations)
                .where(DonationRegistrations.user_id == int(user_id))
                .order_by(DonationRegistrations.created_at.desc())
                .limit(int(limit))
            )
            results = session.execute(stmt).scalars().all()
            return [_registration_to_dict(r) for r in results if r is not None]
    except Exception as e:
        logger.error(f"获取用户捐赠登记历史失败: {e}")
        return []


def get_pending_donation_registrations(limit: int = 50) -> list[dict]:
    """获取待处理的捐赠登记列表"""
    try:
        with get_session() as session:
            stmt = (
                select(DonationRegistrations)
                .where(DonationRegistrations.status == "pending")
                .order_by(DonationRegistrations.created_at.asc())
                .limit(int(limit))
            )
            results = session.execute(stmt).scalars().all()
            return [_registration_to_dict(r) for r in results if r is not None]
    except Exception as e:
        logger.error(f"获取待处理捐赠登记失败: {e}")
        return []


def claim_and_confirm_registration_tx(
    session: Session,
    registration_id: int,
    approved: bool,
    admin_note: str | None = None,
    processed_by: int | None = None,
) -> DonationRegistrations:
    """Atomically claim and transition registration from pending to approved/rejected."""
    processed_at = datetime.now(settings.TZ).isoformat()
    status = "approved" if approved else "rejected"

    stmt = (
        update(DonationRegistrations)
        .where(
            DonationRegistrations.id == int(registration_id),
            DonationRegistrations.status == "pending",
        )
        .values(
            status=status,
            admin_note=admin_note,
            processed_at=processed_at,
            processed_by=processed_by,
        )
    )
    result = session.execute(stmt)
    if result.rowcount == 0:
        existing = session.execute(
            select(DonationRegistrations).where(
                DonationRegistrations.id == int(registration_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            raise donation_exceptions.DonationRegistrationNotFound()
        raise donation_exceptions.DonationRegistrationNotPending(existing.status)

    reg = session.execute(
        select(DonationRegistrations).where(
            DonationRegistrations.id == int(registration_id)
        )
    ).scalar_one()
    session.flush()
    return reg


def confirm_registration_tx(
    session: Session,
    registration_id: int,
    admin_id: int,
    approved: bool,
    admin_note: str | None = None,
    multiplier: int = 5,
) -> dict:
    """Execute status update, donation update, and credits addition in one transaction."""
    from app.domains.credits import repository as credits_repository
    from app.domains.credits.types import CreditAccount

    reg = claim_and_confirm_registration_tx(
        session,
        registration_id=registration_id,
        approved=approved,
        admin_note=admin_note,
        processed_by=admin_id,
    )
    user_id = int(reg.user_id)
    amount = float(reg.amount)
    is_donation_registration = bool(reg.is_donation_registration)
    cumulative = None

    if approved:
        cumulative = add_donation_tx(session, user_id, amount)
        if not is_donation_registration:
            credits_to_add = round(amount * multiplier, 2)
            credits_repository.add_tx(
                session, CreditAccount.tg(user_id), credits_to_add
            )

    return {
        "id": reg.id,
        "user_id": user_id,
        "payment_method": reg.payment_method,
        "amount": amount,
        "note": reg.note,
        "status": reg.status,
        "admin_note": reg.admin_note,
        "created_at": reg.created_at,
        "processed_at": reg.processed_at,
        "processed_by": reg.processed_by,
        "is_donation_registration": is_donation_registration,
        "cumulative_donation": cumulative,
    }


def confirm_registration(
    registration_id: int,
    admin_id: int,
    approved: bool,
    admin_note: str | None = None,
    multiplier: int = 5,
) -> dict:
    """Confirm registration in a single managed database transaction."""
    with get_session() as session:
        return confirm_registration_tx(
            session,
            registration_id=registration_id,
            admin_id=admin_id,
            approved=approved,
            admin_note=admin_note,
            multiplier=multiplier,
        )


def admin_record_donation_tx(
    session: Session,
    tg_id: int,
    amount: float,
    multiplier: int = 5,
) -> tuple[float, float]:
    """Record an admin donation and credit addition in one transaction."""
    from app.domains.credits import repository as credits_repository
    from app.domains.credits.types import CreditAccount

    stats = session.execute(
        select(Statistics).where(Statistics.tg_id == int(tg_id)).with_for_update()
    ).scalar_one_or_none()
    if stats is None:
        raise donation_exceptions.DonationUserNotFound()

    cumulative = add_donation_tx(session, int(tg_id), float(amount))
    credits_to_add = round(float(amount) * multiplier, 2)
    mutation = credits_repository.add_tx(
        session, CreditAccount.tg(int(tg_id)), credits_to_add
    )
    return cumulative, mutation.delta


def admin_record_donation(
    tg_id: int,
    amount: float,
    multiplier: int = 5,
) -> tuple[float, float]:
    """Record an admin donation in a single managed transaction."""
    with get_session() as session:
        return admin_record_donation_tx(
            session, tg_id=tg_id, amount=amount, multiplier=multiplier
        )


def bot_record_donation_tx(
    session: Session,
    tg_id: int,
    amount: float,
    add_credits: bool = True,
    multiplier: int = 5,
) -> tuple[float, float | None]:
    """Record a bot manual donation in one transaction (without badge event)."""
    from app.domains.credits import repository as credits_repository
    from app.domains.credits.types import CreditAccount

    stats = session.execute(
        select(Statistics).where(Statistics.tg_id == int(tg_id)).with_for_update()
    ).scalar_one_or_none()
    if stats is None:
        raise donation_exceptions.DonationUserNotFound()

    cumulative = add_donation_tx(session, int(tg_id), float(amount))
    credits_delta = None
    if add_credits:
        credits_to_add = round(float(amount) * multiplier, 2)
        mutation = credits_repository.add_tx(
            session, CreditAccount.tg(int(tg_id)), credits_to_add
        )
        credits_delta = mutation.delta

    # NOTE: Bot manual path intentionally does NOT publish DonationApproved!
    return cumulative, credits_delta


def bot_record_donation(
    tg_id: int,
    amount: float,
    add_credits: bool = True,
    multiplier: int = 5,
) -> tuple[float, float | None]:
    """Record a bot manual donation in a single managed transaction."""
    with get_session() as session:
        return bot_record_donation_tx(
            session,
            tg_id=tg_id,
            amount=amount,
            add_credits=add_credits,
            multiplier=multiplier,
        )


def delete_donation_registration(registration_id: int) -> bool:
    """删除捐赠登记记录"""
    try:
        with get_session() as session:
            session.execute(
                delete(DonationRegistrations).where(
                    DonationRegistrations.id == int(registration_id)
                )
            )
            return True
    except Exception as e:
        logger.error(f"删除捐赠登记失败: {e}")
        return False


def get_donation_statistics() -> dict:
    """获取捐赠统计信息"""
    try:
        with get_session() as session:
            total_registrations = (
                session.execute(select(func.count(DonationRegistrations.id))).scalar()
                or 0
            )

            pending_registrations = (
                session.execute(
                    select(func.count(DonationRegistrations.id)).where(
                        DonationRegistrations.status == "pending"
                    )
                ).scalar()
                or 0
            )

            approved_registrations = (
                session.execute(
                    select(func.count(DonationRegistrations.id)).where(
                        DonationRegistrations.status == "approved"
                    )
                ).scalar()
                or 0
            )

            rejected_registrations = (
                session.execute(
                    select(func.count(DonationRegistrations.id)).where(
                        DonationRegistrations.status == "rejected"
                    )
                ).scalar()
                or 0
            )

            total_amount = session.execute(
                select(func.sum(DonationRegistrations.amount)).where(
                    DonationRegistrations.status == "approved"
                )
            ).scalar()
            total_amount = float(total_amount) if total_amount else 0.0

            return {
                "total_registrations": total_registrations,
                "pending_registrations": pending_registrations,
                "approved_registrations": approved_registrations,
                "rejected_registrations": rejected_registrations,
                "total_approved_amount": total_amount,
            }
    except Exception as e:
        logger.error(f"获取捐赠统计信息失败: {e}")
        return {
            "total_registrations": 0,
            "pending_registrations": 0,
            "approved_registrations": 0,
            "rejected_registrations": 0,
            "total_approved_amount": 0.0,
        }


def update_donation_credits(old_multiplier: float, new_multiplier: float) -> None:
    """Reprice all donation credits in one caller-owned transaction."""
    from app.domains.credits import repository as credits_repository
    from app.domains.credits.types import CreditAccount

    with get_session() as session:
        donations = session.execute(
            select(Statistics.tg_id, Statistics.donation, Statistics.credits)
            .where(Statistics.donation > 0)
            .with_for_update()
        ).all()
        for tg_id, donation, credits in donations:
            delta = round(float(donation) * (new_multiplier - old_multiplier), 2)
            if delta > 0:
                mutation = credits_repository.add_tx(
                    session, CreditAccount.tg(int(tg_id)), delta
                )
            elif delta < 0:
                mutation = credits_repository.deduct_tx(
                    session, CreditAccount.tg(int(tg_id)), -delta
                )
            else:
                continue
            logger.info(
                f"用户 {tg_id} 捐赠：{donation}, 更新积分: {credits} -> {mutation.after}"
            )


def list_badge_eligible_donors(
    threshold: float, tg_id: int | None = None
) -> list[tuple[int, float]]:
    """Return strict-above-threshold donors without opening a session in callers."""
    stmt = select(Statistics.tg_id, Statistics.donation).where(
        Statistics.donation > threshold
    )
    if tg_id:
        stmt = stmt.where(Statistics.tg_id == tg_id)
    with get_session() as session:
        return [(int(row[0]), float(row[1])) for row in session.execute(stmt)]


__all__ = [
    "add_donation_tx",
    "admin_record_donation",
    "admin_record_donation_tx",
    "bot_record_donation",
    "bot_record_donation_tx",
    "claim_and_confirm_registration_tx",
    "confirm_registration",
    "confirm_registration_tx",
    "create_donation_registration",
    "create_donation_registration_tx",
    "delete_donation_registration",
    "get_donation_registration_by_id",
    "get_donation_registrations_by_user",
    "get_donation_statistics",
    "get_pending_donation_registrations",
    "list_badge_eligible_donors",
    "update_donation_credits",
]
