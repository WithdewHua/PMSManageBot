"""Auction scheduled entry points and startup restoration."""

from app.core.log import uvicorn_logger as logger
from app.domains.auction import service as auction_service


async def finish_single_auction(auction_id: int) -> None:
    """Named memory-job entry point for ``auction.finish``."""
    await auction_service.finish_single_auction_job(auction_id=int(auction_id))


# Transitional alias retained for existing manual operations and older tests.
finish_single_auction_job = finish_single_auction


def restore_auction_schedules() -> None:
    """Restore at most the first 50 active, not-yet-expired auction tasks."""
    auction_service.restore_auction_schedules()


async def finish_expired_auctions_job() -> list[dict]:
    """Periodic safety-net job for auctions whose in-memory task was missed."""
    try:
        return await auction_service.finish_expired_auctions()
    except Exception as error:
        logger.error(f"自动结束过期竞拍失败: {error}")
        return []


__all__ = [
    "finish_expired_auctions_job",
    "finish_single_auction",
    "finish_single_auction_job",
    "restore_auction_schedules",
]
