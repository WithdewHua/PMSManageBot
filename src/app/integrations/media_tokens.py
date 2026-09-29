"""Token-to-username caches owned by media-server integrations."""

from collections.abc import Iterable

from app.core.cache import RedisCache

_emby_api_key_cache = RedisCache(
    db=3,
    cache_key_prefix="emby_api_key:",
)
_plex_token_cache = RedisCache(
    db=3,
    cache_key_prefix="plex_token_cache:",
)


def get_emby_username(api_key: str):
    return _emby_api_key_cache.get(api_key)


def put_emby_username(api_key: str, username: str) -> None:
    _emby_api_key_cache.put(api_key, username)


def get_plex_username(token: str):
    return _plex_token_cache.get(token)


def get_all_plex_usernames() -> dict:
    return _plex_token_cache.get_all_key_values()


def put_plex_username(token: str, username: str) -> None:
    _plex_token_cache.put(token, username)


def delete_plex_token(token: str) -> None:
    _plex_token_cache.delete(token)


def clear_plex_tokens_for_usernames(usernames: Iterable[str]) -> list[str]:
    names = set(usernames)
    deleted: list[str] = []
    for token, username in get_all_plex_usernames().items():
        if username in names:
            delete_plex_token(token)
            deleted.append(username)
    return deleted


__all__ = [
    "clear_plex_tokens_for_usernames",
    "delete_plex_token",
    "get_all_plex_usernames",
    "get_emby_username",
    "get_plex_username",
    "put_emby_username",
    "put_plex_username",
]
