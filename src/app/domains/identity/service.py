"""Identity read operations and identity-owned cache APIs."""

import json
from typing import Any

from app.domains.identity import repository as identity_repository
from app.domains.identity import rules as identity_rules
from app.domains.identity.cache import user_info_cache


def publish_user_info_snapshot(cache_key: str, snapshot: dict[str, Any]) -> None:
    """Publish a serialized identity snapshot without exposing the cache instance."""
    user_info_cache.put(cache_key, json.dumps(snapshot))


def get_service_label(service: str) -> tuple[str, str]:
    """Expose pure identity-owned media display labels to other domains."""
    return identity_rules.get_service_label(service)


def write_user_info_cache() -> None:
    identity_repository.IdentityRepository().write_user_info_cache()


def get_plex_info_by_tg_id(tg_id: int) -> tuple | None:
    """Keep the independent legacy lookup session and tuple layout."""
    return identity_repository.IdentityRepository().get_plex_info_by_tg_id(tg_id)


def get_emby_info_by_tg_id(tg_id: int) -> tuple | None:
    """Keep the independent legacy lookup session and tuple layout."""
    return identity_repository.IdentityRepository().get_emby_info_by_tg_id(tg_id)


def list_statistics_tg_ids() -> list[int]:
    """List Telegram IDs for profile synchronization jobs."""
    return identity_repository.IdentityRepository()._list_statistics_tg_ids()
