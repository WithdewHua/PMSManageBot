"""Profile aggregation workflows."""

from app.core.config import settings
from app.domains.identity import service as identity_service
from app.integrations.telegram import profiles as telegram_profiles


async def refresh_tg_user_info(
    tg_id: int | None = None, token: str = settings.TG_API_TOKEN
) -> None:
    """Refresh Telegram profile cache for one user or all known users."""
    stats_users = (
        identity_service.list_statistics_tg_ids() if tg_id is None else [tg_id]
    )
    await telegram_profiles.refresh_tg_user_info(stats_users, token=token)


__all__ = ["refresh_tg_user_info"]
