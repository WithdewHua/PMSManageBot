from concurrent.futures import ThreadPoolExecutor, wait

from app.domains.accounts import service as accounts_service
from app.integrations.emby import Emby


def update_users_last_viewed() -> None:
    """更新所有用户的最后观看时间."""
    with ThreadPoolExecutor() as executor:
        future_plex = executor.submit(accounts_service.update_plex_users_last_viewed_at)
        future_emby = executor.submit(accounts_service.update_emby_users_last_viewed_at)
        wait([future_plex, future_emby])


def refresh_emby_user_info(emby_username: str | None = None) -> None:
    accounts_service.refresh_emby_user_info(emby_username, emby_factory=Emby)
