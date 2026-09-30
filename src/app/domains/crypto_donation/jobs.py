"""Scheduled crypto payment expiry entry point."""

from app.core.log import logger
from app.domains.crypto_donation import service


async def check_expired_crypto_donation_orders() -> None:
    """定时任务：检查并更新过期的 crypto 捐赠订单状态"""
    try:
        await service.process_expired_orders()
    except Exception:
        logger.exception("检查过期 crypto 捐赠订单失败")
