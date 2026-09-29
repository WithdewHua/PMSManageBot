"""Credit-balance cache and post-commit invalidation owned by credits."""

from collections.abc import Iterable

from app.core.cache import RedisCache
from app.core.log import logger

user_credits_cache = RedisCache(
    db=0,
    cache_key_prefix="user_credits:",
)


def invalidate_user_credits(keys: Iterable[str]) -> None:
    """Best-effort deletion of cached credit balances after commit."""
    for key in dict.fromkeys(keys):
        try:
            user_credits_cache.delete(key)
        except Exception as error:  # pragma: no cover - depends on Redis availability
            logger.warning(f"Failed to invalidate credit cache {key}: {error}")


__all__ = ["invalidate_user_credits", "user_credits_cache"]
