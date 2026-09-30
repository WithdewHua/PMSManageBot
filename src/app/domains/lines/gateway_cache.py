"""Redis caches for gateway/user-defined line selection."""

from app.core.cache import RedisCache

emby_user_defined_line_cache = RedisCache(
    db=2,
    cache_key_prefix="emby_user_defined_line:",
)
emby_last_user_defined_line_cache = RedisCache(
    db=2,
    cache_key_prefix="emby_last_user_defined_line:",
)
plex_user_defined_line_cache = RedisCache(
    db=2,
    cache_key_prefix="plex_user_defined_line:",
)
plex_last_user_defined_line_cache = RedisCache(
    db=2,
    cache_key_prefix="plex_last_user_defined_line:",
)

__all__ = [
    "emby_last_user_defined_line_cache",
    "emby_user_defined_line_cache",
    "plex_last_user_defined_line_cache",
    "plex_user_defined_line_cache",
]
