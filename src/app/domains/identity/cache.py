"""Redis cache owned by the identity domain."""

from app.core.cache import RedisCache

user_info_cache = RedisCache(
    db=2,
    cache_key_prefix="user_info:",
)

__all__ = ["user_info_cache"]
