"""Typed identity query APIs and identity-owned cache workflows."""

import json
from typing import Any

from app.domains.identity import repository as identity_repository
from app.domains.identity import rules as identity_rules
from app.domains.identity.cache import user_info_cache
from app.domains.identity.types import (
    EmbyAccount,
    OverseerrAccount,
    PlexAccount,
    UserStatistics,
    emby_legacy_tuple,
    overseerr_legacy_tuple,
    plex_legacy_tuple,
    statistics_legacy_tuple,
)


def publish_user_info_snapshot(cache_key: str, snapshot: dict[str, Any]) -> None:
    """Publish a serialized identity snapshot without exposing the cache instance."""
    user_info_cache.put(cache_key, json.dumps(snapshot))


def get_service_label(service: str) -> tuple[str, str]:
    """Expose pure identity-owned media display labels to other domains."""
    return identity_rules.get_service_label(service)


def write_user_info_cache() -> None:
    identity_repository.write_user_info_cache()


def find_plex_by_tg(tg_id: int) -> PlexAccount | None:
    return identity_repository.find_plex_by_tg(tg_id)


def find_plex_by_id(plex_id: int) -> PlexAccount | None:
    return identity_repository.find_plex_by_id(plex_id)


def find_plex_by_email(plex_email: str) -> PlexAccount | None:
    return identity_repository.find_plex_by_email(plex_email)


def find_unresolved_plex_by_email(plex_email: str) -> PlexAccount | None:
    return identity_repository.find_unresolved_plex_by_email(plex_email)


def find_emby_by_tg(tg_id: int) -> EmbyAccount | None:
    return identity_repository.find_emby_by_tg(tg_id)


def find_emby_by_username(username: str) -> EmbyAccount | None:
    return identity_repository.find_emby_by_username(username)


def find_overseerr_by_tg(tg_id: int) -> OverseerrAccount | None:
    return identity_repository.find_overseerr_by_tg(tg_id)


def find_overseerr_by_email(email: str) -> OverseerrAccount | None:
    return identity_repository.find_overseerr_by_email(email)


def get_statistics(tg_id: int) -> UserStatistics | None:
    return identity_repository.get_statistics(tg_id)


def count_bound_plex_users() -> int:
    return identity_repository.count_bound_plex_users()


def add_plex_user(**kwargs) -> bool:
    return identity_repository.add_plex_user(**kwargs)


def add_emby_user(
    emby_username: str, emby_id: str | None = None, tg_id: int | None = None, **kwargs
) -> bool:
    return identity_repository.add_emby_user(
        emby_username=emby_username,
        emby_id=emby_id,
        tg_id=tg_id,
        **kwargs,
    )


def add_user_data(tg_id: int, credits: float = 0, donation: float = 0) -> bool:
    return identity_repository.add_user_data(tg_id, credits, donation)


def add_overseerr_user(user_id: int, user_email: str, tg_id: int) -> bool:
    return identity_repository.add_overseerr_user(user_id, user_email, tg_id)


def delete_plex_user(plex_email: str) -> bool:
    return identity_repository.delete_plex_user(plex_email)


def list_statistics_tg_ids() -> list[int]:
    return identity_repository.list_statistics_tg_ids()


def list_plex_ids() -> set[int]:
    return identity_repository.list_plex_ids()


def list_unresolved_plex_emails(target_email: str | None = None) -> list[str]:
    return identity_repository.list_unresolved_plex_emails(target_email)


def update_plex_identity(
    *, plex_id: int, plex_username: str, plex_email: str | None
) -> str | None:
    return identity_repository.update_plex_identity(
        plex_id=plex_id,
        plex_username=plex_username,
        plex_email=plex_email,
    )


def update_plex_last_viewed(values: dict[int, int]) -> int:
    return identity_repository.update_plex_last_viewed(values)


def update_emby_last_viewed(values: dict[str, int | None]) -> int:
    return identity_repository.update_emby_last_viewed(values)


def list_emby_usernames() -> list[str]:
    return identity_repository.list_emby_usernames()


def get_plex_info_by_tg_id(tg_id: int) -> tuple | None:
    account = find_plex_by_tg(tg_id)
    return plex_legacy_tuple(account) if account else None


def get_plex_info_by_plex_id(plex_id: int) -> tuple | None:
    account = find_plex_by_id(plex_id)
    return plex_legacy_tuple(account) if account else None


def get_plex_info_by_plex_email(plex_email: str) -> tuple | None:
    account = find_plex_by_email(plex_email)
    return plex_legacy_tuple(account) if account else None


def get_emby_info_by_tg_id(tg_id: int) -> tuple | None:
    account = find_emby_by_tg(tg_id)
    return emby_legacy_tuple(account) if account else None


def get_emby_info_by_emby_username(username: str) -> tuple | None:
    account = find_emby_by_username(username)
    return emby_legacy_tuple(account) if account else None


def get_stats_by_tg_id(tg_id: int) -> tuple | None:
    stats = get_statistics(tg_id)
    return statistics_legacy_tuple(stats) if stats else None


def get_overseerr_info_by_tg_id(tg_id: int) -> tuple | None:
    account = find_overseerr_by_tg(tg_id)
    return overseerr_legacy_tuple(account) if account else None


def get_overseerr_info_by_email(email: str) -> tuple | None:
    account = find_overseerr_by_email(email)
    return overseerr_legacy_tuple(account) if account else None


__all__ = [
    "add_emby_user",
    "add_overseerr_user",
    "add_plex_user",
    "add_user_data",
    "count_bound_plex_users",
    "delete_plex_user",
    "find_emby_by_tg",
    "find_emby_by_username",
    "find_overseerr_by_email",
    "find_overseerr_by_tg",
    "find_plex_by_email",
    "find_plex_by_id",
    "find_plex_by_tg",
    "find_unresolved_plex_by_email",
    "get_emby_info_by_emby_username",
    "get_emby_info_by_tg_id",
    "get_overseerr_info_by_email",
    "get_overseerr_info_by_tg_id",
    "get_plex_info_by_plex_email",
    "get_plex_info_by_plex_id",
    "get_plex_info_by_tg_id",
    "get_service_label",
    "get_statistics",
    "get_stats_by_tg_id",
    "list_emby_usernames",
    "list_plex_ids",
    "list_statistics_tg_ids",
    "list_unresolved_plex_emails",
    "publish_user_info_snapshot",
    "update_emby_last_viewed",
    "update_plex_identity",
    "update_plex_last_viewed",
    "write_user_info_cache",
]
