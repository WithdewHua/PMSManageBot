"""Scheduled custom-line workflows."""

from datetime import UTC, datetime

from app.core.log import logger
from app.domains.custom_lines import service


async def check_expired_custom_lines() -> None:
    try:
        now = int(datetime.now(tz=UTC).timestamp())
        expiring = service.repository.expiring_lines(now)
        if expiring:
            await service._send_expiring_soon_notifications(expiring, now)
        expired = await service.process_expired_lines(now)
        logger.info("自定义线路过期检查完成: %s 条过期", len(expired))
    except Exception:
        logger.exception("检查过期自定义线路失败")


async def check_custom_line_traffic() -> None:
    try:
        results = await service.check_custom_line_traffic()
        logger.info(
            "流量检查完成: %s 条线路变更",
            len(results),
        )
    except Exception:
        logger.exception("检查自定义线路流量失败")


# The scheduler keeps importing this symbol by name.
settle_custom_line_traffic = service.settle_custom_line_traffic

__all__ = [
    "check_custom_line_traffic",
    "check_expired_custom_lines",
    "settle_custom_line_traffic",
]
