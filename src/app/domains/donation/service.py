from app.core.log import logger
from app.domains.donation import repository as donation_repository
from app.domains.donation.config import DONATION_CONFIG


def get_donation_multiplier() -> int:
    return int(DONATION_CONFIG.get().donation_multiplier)


def set_donation_multiplier(multiplier: int) -> int:
    return int(
        DONATION_CONFIG.update(donation_multiplier=multiplier).donation_multiplier
    )


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
