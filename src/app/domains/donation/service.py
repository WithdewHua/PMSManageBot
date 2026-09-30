from app.core.log import logger
from app.domains.donation import repository as donation_repository
from app.domains.donation.config import DONATION_CONFIG
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
    return donation_repository.DonationRepository().create_donation_registration(
        int(user_id),
        payment_method,
        float(amount),
        note,
        bool(is_donation_registration),
    )


def get_donation_registration_by_id(registration_id: int) -> dict | None:
    return _enrich_registration(
        donation_repository.DonationRepository().get_donation_registration_by_id(
            int(registration_id)
        )
    )


def get_donation_registrations_by_user(user_id: int, limit: int = 20) -> list[dict]:
    return [
        _enrich_registration(registration) or {}
        for registration in donation_repository.DonationRepository().get_donation_registrations_by_user(
            int(user_id), limit=int(limit)
        )
    ]


def get_pending_donation_registrations(limit: int = 50) -> list[dict]:
    return [
        _enrich_registration(registration) or {}
        for registration in donation_repository.DonationRepository().get_pending_donation_registrations(
            limit=int(limit)
        )
    ]


def update_donation_credits(old_multiplier, new_multiplier):
    """
    更新捐赠积分

    Args:
        old_multiplier: 旧的积分倍数
        new_multiplier: 新的积分倍数
    """
    try:
        donation_repository.update_donation_credits(old_multiplier, new_multiplier)
    except Exception as e:
        logger.error(str(e))


def list_badge_eligible_donors(
    threshold: float, tg_id: int | None = None
) -> list[tuple[int, float]]:
    from app.domains.donation import repository

    return repository.list_badge_eligible_donors(threshold, tg_id)
