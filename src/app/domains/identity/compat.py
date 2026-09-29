"""SQLAlchemy-free compatibility facade for the legacy ``DatabaseORM``."""

from __future__ import annotations

from app.core.log import logger
from app.domains.identity import service as identity_service
from app.domains.identity.types import (
    emby_legacy_tuple,
    overseerr_legacy_tuple,
    plex_legacy_tuple,
    statistics_legacy_tuple,
)


class IdentityRepository:
    """Legacy names and tuple shapes for domains not yet promoted.

    This class deliberately contains no SQL or model access. It is removed with
    the legacy database facade after the remaining domains have migrated.
    """

    def write_user_info_cache(self) -> None:
        identity_service.write_user_info_cache()

    def add_plex_user(self, **kwargs) -> bool:
        try:
            return identity_service.add_plex_user(**kwargs)
        except Exception as error:
            logger.error("Error adding plex user: %s", error)
            return False

    def delete_plex_user(self, plex_email: str) -> bool:
        try:
            return identity_service.delete_plex_user(plex_email)
        except Exception as error:
            logger.error("Error deleting plex user: %s", error)
            return False

    def get_plex_info_by_tg_id(self, tg_id: int) -> tuple | None:
        account = identity_service.find_plex_by_tg(tg_id)
        return plex_legacy_tuple(account) if account else None

    def get_plex_info_by_plex_id(self, plex_id: int) -> tuple | None:
        account = identity_service.find_plex_by_id(plex_id)
        return plex_legacy_tuple(account) if account else None

    def get_plex_info_by_plex_email(self, plex_email: str) -> tuple | None:
        account = identity_service.find_plex_by_email(plex_email)
        return plex_legacy_tuple(account) if account else None

    def add_emby_user(self, emby_username: str, **kwargs) -> bool:
        try:
            return identity_service.add_emby_user(emby_username, **kwargs)
        except Exception as error:
            logger.error("Error adding emby user: %s", error)
            return False

    def get_emby_info_by_emby_username(self, username: str) -> tuple | None:
        account = identity_service.find_emby_by_username(username)
        return emby_legacy_tuple(account) if account else None

    def get_emby_info_by_tg_id(self, tg_id: int) -> tuple | None:
        account = identity_service.find_emby_by_tg(tg_id)
        return emby_legacy_tuple(account) if account else None

    def add_user_data(
        self, tg_id: int, credits: float = 0, donation: float = 0
    ) -> bool:
        try:
            return identity_service.add_user_data(tg_id, credits, donation)
        except Exception as error:
            logger.error("Error adding user data: %s", error)
            return False

    def get_stats_by_tg_id(self, tg_id: int) -> tuple | None:
        stats = identity_service.get_statistics(tg_id)
        return statistics_legacy_tuple(stats) if stats else None

    def add_overseerr_user(self, user_id: int, user_email: str, tg_id: int) -> bool:
        try:
            return identity_service.add_overseerr_user(
                user_id=user_id, user_email=user_email, tg_id=tg_id
            )
        except Exception as error:
            logger.error("Error adding overseerr user: %s", error)
            return False

    def get_overseerr_info_by_tg_id(self, tg_id: int) -> tuple | None:
        account = identity_service.find_overseerr_by_tg(tg_id)
        return overseerr_legacy_tuple(account) if account else None

    def get_overseerr_info_by_email(self, email: str) -> tuple | None:
        account = identity_service.find_overseerr_by_email(email)
        return overseerr_legacy_tuple(account) if account else None

    def _list_statistics_tg_ids(self) -> list[int]:
        return identity_service.list_statistics_tg_ids()


__all__ = ["IdentityRepository"]
