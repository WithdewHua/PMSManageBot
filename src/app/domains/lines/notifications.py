"""Administrator notifications for line-domain workflows."""

from app.transport.telegram.admin import notify_admins_by_url


async def notify_schedule_unlocked(text: str) -> None:
    await notify_admins_by_url(text)


__all__ = ["notify_schedule_unlocked"]
