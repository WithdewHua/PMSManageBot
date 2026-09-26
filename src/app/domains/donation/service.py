from app.core.log import logger
from app.domains.donation import repository as donation_repository


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
