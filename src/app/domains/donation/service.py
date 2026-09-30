"""Donation domain service orchestrating donation use cases."""

from __future__ import annotations

from app.core import events
from app.core.log import logger
from app.domains.donation import (
    exceptions as donation_exceptions,
)
from app.domains.donation import (
    notifications,
)
from app.domains.donation import (
    repository as donation_repository,
)
from app.domains.donation.config import DONATION_CONFIG
from app.domains.donation.events import DonationApproved
from app.integrations.telegram import profiles as telegram_profiles


def get_donation_multiplier() -> int:
    return int(DONATION_CONFIG.get().donation_multiplier)


def set_donation_multiplier(multiplier: int) -> int:
    return int(
        DONATION_CONFIG.update(donation_multiplier=multiplier).donation_multiplier
    )


def _enrich_registration(registration: dict | None) -> dict | None:
    if registration is None:
        return None
    result = dict(registration)
    user_id = int(result["user_id"])
    processed_by = result.get("processed_by")
    result["username"] = telegram_profiles.get_user_name_from_tg_id(user_id)
    result["processed_by_username"] = (
        telegram_profiles.get_user_name_from_tg_id(int(processed_by))
        if processed_by
        else None
    )
    return result


def create_donation_registration(
    user_id: int,
    payment_method: str,
    amount: float,
    note: str | None = None,
    is_donation_registration: bool = False,
) -> int | None:
    return donation_repository.create_donation_registration(
        int(user_id),
        payment_method,
        float(amount),
        note,
        bool(is_donation_registration),
    )


def get_donation_registration_by_id(registration_id: int) -> dict | None:
    return _enrich_registration(
        donation_repository.get_donation_registration_by_id(int(registration_id))
    )


def get_donation_registrations_by_user(user_id: int, limit: int = 20) -> list[dict]:
    return [
        _enrich_registration(registration) or {}
        for registration in donation_repository.get_donation_registrations_by_user(
            int(user_id), limit=int(limit)
        )
    ]


def get_pending_donation_registrations(limit: int = 50) -> list[dict]:
    return [
        _enrich_registration(registration) or {}
        for registration in donation_repository.get_pending_donation_registrations(
            limit=int(limit)
        )
    ]


def get_donation_statistics() -> dict:
    return donation_repository.get_donation_statistics()


async def confirm_donation_registration(
    registration_id: int,
    admin_id: int,
    approved: bool,
    admin_note: str | None = None,
) -> dict:
    """Confirm a donation registration atomically and execute post-commit side effects."""
    multiplier = get_donation_multiplier()
    reg_data = donation_repository.confirm_registration(
        registration_id=int(registration_id),
        admin_id=int(admin_id),
        approved=approved,
        admin_note=admin_note,
        multiplier=multiplier,
    )

    user_id = int(reg_data["user_id"])

    # Post-commit: generate redeem code for account registration donations
    if approved and reg_data.get("is_donation_registration"):
        from app.domains.invitation import service as invitation_service

        try:
            invitation_service.generate_codes(
                owner_tg_id=user_id, count=1, charge=0, privileged=False
            )
            logger.info(f"为捐赠开号用户 {user_id} 生成邀请码成功")
        except Exception as e:
            logger.error(f"为捐赠开号用户 {user_id} 生成邀请码失败: {e}")

    if approved:
        events.emit(DonationApproved(user_id))

    # Guard post-commit name lookups to prevent turning committed crediting into a 500 error
    try:
        user_name = telegram_profiles.get_user_name_from_tg_id(user_id)
    except Exception as e:
        logger.warning(f"Telegram name lookup failed for user {user_id}: {e}")
        user_name = str(user_id)

    try:
        admin_name = (
            telegram_profiles.get_user_name_from_tg_id(int(admin_id))
            if admin_id
            else None
        )
    except Exception as e:
        logger.warning(f"Telegram name lookup failed for admin {admin_id}: {e}")
        admin_name = str(admin_id) if admin_id else None

    enriched = dict(reg_data)
    enriched["username"] = user_name
    enriched["processed_by_username"] = admin_name

    action = "批准" if approved else "拒绝"
    logger.info(f"管理员 {admin_id} {action}了捐赠登记 {registration_id}")

    # Guard post-commit notifications
    try:
        await notifications.send_confirmation_notifications(
            registration_id=int(registration_id),
            user_id=user_id,
            user_name=user_name,
            admin_id=int(admin_id),
            admin_name=admin_name or str(admin_id),
            approved=approved,
            amount=float(enriched["amount"]),
            payment_method=str(enriched["payment_method"]),
            is_donation_registration=bool(enriched["is_donation_registration"]),
            processed_at=enriched.get("processed_at"),
            admin_note=admin_note,
        )
    except Exception as e:
        logger.warning(
            f"Failed to send confirmation notifications for registration {registration_id}: {e}"
        )

    return enriched


async def admin_record_donation(
    tg_id: int,
    amount: float,
    admin_id: int,
    note: str | None = None,
) -> dict:
    """Record an admin donation and trigger user notification post-commit."""
    if not tg_id or amount <= 0:
        raise donation_exceptions.DonationInvalidAmount("参数错误")

    multiplier = get_donation_multiplier()
    cumulative, credits_added = donation_repository.admin_record_donation(
        tg_id=int(tg_id),
        amount=float(amount),
        multiplier=multiplier,
    )

    events.emit(DonationApproved(int(tg_id)))

    # Guard post-commit name lookups to prevent turning committed crediting into a 500 error
    try:
        user_name = telegram_profiles.get_user_name_from_tg_id(int(tg_id))
    except Exception as e:
        logger.warning(f"Telegram name lookup failed for user {tg_id}: {e}")
        user_name = str(tg_id)

    try:
        admin_name = telegram_profiles.get_user_name_from_tg_id(int(admin_id))
    except Exception as e:
        logger.warning(f"Telegram name lookup failed for admin {admin_id}: {e}")
        admin_name = str(admin_id)

    logger.info(
        f"管理员 {admin_name}({admin_id}) 为用户 {user_name}({tg_id}) 添加捐赠记录: {amount}元"
        + (f", 备注: {note}" if note else "")
    )

    # Guard post-commit notification
    try:
        await notifications.send_donation_received_notification(
            tg_id=int(tg_id),
            amount=float(amount),
            cumulative_donation=cumulative,
            note=note,
        )
    except Exception as e:
        logger.warning(
            f"Failed to send donation received notification for tg_id={tg_id}: {e}"
        )

    return {
        "success": True,
        "user_name": user_name,
        "amount": float(amount),
        "cumulative": cumulative,
        "credits_added": credits_added,
    }


def bot_record_donation(
    tg_id: int,
    amount: float,
    add_credits: bool = True,
) -> tuple[float, float | None]:
    """Record a bot manual donation under a single database transaction."""
    multiplier = get_donation_multiplier()
    return donation_repository.bot_record_donation(
        tg_id=int(tg_id),
        amount=float(amount),
        add_credits=add_credits,
        multiplier=multiplier,
    )


def update_donation_credits(old_multiplier: float, new_multiplier: float) -> None:
    """更新捐赠积分（手动运维入口）"""
    try:
        donation_repository.update_donation_credits(old_multiplier, new_multiplier)
    except Exception as e:
        logger.error(str(e))


def list_badge_eligible_donors(
    threshold: float, tg_id: int | None = None
) -> list[tuple[int, float]]:
    return donation_repository.list_badge_eligible_donors(threshold, tg_id)


__all__ = [
    "admin_record_donation",
    "bot_record_donation",
    "confirm_donation_registration",
    "create_donation_registration",
    "get_donation_multiplier",
    "get_donation_registration_by_id",
    "get_donation_registrations_by_user",
    "get_donation_statistics",
    "get_pending_donation_registrations",
    "list_badge_eligible_donors",
    "set_donation_multiplier",
    "update_donation_credits",
]
