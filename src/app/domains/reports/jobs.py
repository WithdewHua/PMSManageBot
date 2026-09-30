from __future__ import annotations

from app.core.config import settings
from app.domains.reports import service as reports_service


async def send_weekly_report(channel_id: str = settings.TG_CHANNEL_ID) -> None:
    """Scheduled task entry point for weekly statistics report."""
    await reports_service.send_weekly_report(channel_id=channel_id)


__all__ = ["send_weekly_report"]
