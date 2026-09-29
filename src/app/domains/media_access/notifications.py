"""Administrator notifications for media-access workflows."""

from app.transport.telegram.admin import notify_admins_by_url


async def notify_nsfw_unlocked(text: str) -> None:
    await notify_admins_by_url(text)


async def notify_download_unlocked(text: str) -> None:
    await notify_admins_by_url(text)


async def notify_nsfw_compensation_failed(
    tg_id: int, service: str, operation: str, error: Exception
) -> None:
    await notify_admins_by_url(
        f"NSFW {operation} compensation failed: tg_id={tg_id}, service={service}, error={error}"
    )


__all__ = [
    "notify_download_unlocked",
    "notify_nsfw_compensation_failed",
    "notify_nsfw_unlocked",
]
