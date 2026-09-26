"""Identity read operations used across domain boundaries during B3 relocation."""

from app.domains.identity import repository as identity_repository


def get_plex_info_by_tg_id(tg_id: int) -> tuple | None:
    """Keep the independent legacy lookup session and tuple layout."""
    return identity_repository.IdentityRepository().get_plex_info_by_tg_id(tg_id)


def get_emby_info_by_tg_id(tg_id: int) -> tuple | None:
    """Keep the independent legacy lookup session and tuple layout."""
    return identity_repository.IdentityRepository().get_emby_info_by_tg_id(tg_id)


def list_statistics_tg_ids() -> list[int]:
    """List Telegram IDs for profile synchronization jobs."""
    return identity_repository.IdentityRepository()._list_statistics_tg_ids()
