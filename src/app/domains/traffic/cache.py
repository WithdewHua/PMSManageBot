"""Redis stream cache owned by the traffic domain."""

from app.core.cache import RedisCache

stream_traffic_cache = RedisCache(
    db=15,
    cache_key_prefix="",
)

__all__ = ["stream_traffic_cache"]
