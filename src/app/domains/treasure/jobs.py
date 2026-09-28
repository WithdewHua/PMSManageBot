"""Treasure auto-reopen jobs; callable paths here are persisted by APScheduler."""

from datetime import datetime

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.domains.treasure import service as treasure_service
from app.domains.treasure.service import schedule_auto_reopen_treasure_issue


async def _auto_create_next_treasure_issue_from(*, source_issue_id: int) -> None:
    """在指定期数开奖后，自动创建“同规格”的下一期。"""
    try:
        source = treasure_service.get_treasure_issue(int(source_issue_id))
        if not source:
            logger.warning(
                f"Treasure auto reopen: source issue not found: {source_issue_id}"
            )
            return
        if int(source.get("status") or 0) != 2:
            logger.info(
                f"Treasure auto reopen: source issue not settled; skip: {source_issue_id}"
            )
            return

        now = datetime.now(settings.TZ).strftime("%Y-%m-%d-%H:%M:%S")
        await treasure_service.create_treasure_issue(
            title=f"夺宝奇兵 {now}",
            description=source.get("description"),
            prize_credits=int(source.get("prize_credits") or 0),
            total_credits_required=int(source.get("total_credits_required") or 0),
            credits_per_share=int(source.get("credits_per_share") or 10),
            start_number=None,
            created_by=(
                int(source["created_by"])
                if source.get("created_by") is not None
                else None
            ),
        )
        logger.info(f"Treasure auto reopen: created next issue from {source_issue_id}")
    except Exception as error:
        logger.error(f"Treasure auto reopen failed (source={source_issue_id}): {error}")


__all__ = [
    "_auto_create_next_treasure_issue_from",
    "schedule_auto_reopen_treasure_issue",
]
