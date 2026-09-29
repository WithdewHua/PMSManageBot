"""Administrator notifications for media-access workflows."""

from app.transport.telegram.admin import notify_admins_by_url


async def notify_nsfw_unlocked(text: str) -> None:
    await notify_admins_by_url(text)


async def notify_download_unlocked(text: str) -> None:
    await notify_admins_by_url(text)


__all__ = ["notify_download_unlocked", "notify_nsfw_unlocked"]
