import time
from typing import Optional

from app.log import logger
from app.redis import Redis


class RedisCache:
    def __init__(
        self,
        db: int = 0,
        capacity: int = 0,
        ttl_seconds: int = None,
        cache_key_prefix: str = "cache:",
        cache_usage_track: bool = False,
    ):
        """
        初始化基于Redis的缓存

        Args:
            capacity: 缓存容量
            ttl_seconds: 缓存条目的存活时间（秒）
        """
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        self.redis_client = Redis(db=db).get_connection()
        self._cache_key_prefix = cache_key_prefix  # Redis键的前缀
        self._cache_usage_key = (
            f"{self._cache_key_prefix.removesuffix(':')}_usage"
            if cache_usage_track
            else None
        )

    def _get_cache_key(self, key: str) -> str:
        """获取缓存键的完整Redis键名"""
        return f"{self._cache_key_prefix}{key}"

    def get_all(self) -> list:
        """
        获取所有缓存值
        """
        values = []
        pipeline = self.redis_client.pipeline()
        for key in self.redis_client.scan_iter(match=f"{self._cache_key_prefix}*"):
            pipeline.get(key)
        results = pipeline.execute()
        values = [val for val in results if val is not None]
        return values

    def get_all_key_values(self) -> dict:
        """
        获取所有缓存键值对

        Returns:
            包含所有缓存键值对的字典
        """
        key_values = {}
        pipeline = self.redis_client.pipeline()
        for key in self.redis_client.scan_iter(match=f"{self._cache_key_prefix}*"):
            pipeline.get(key)
        results = pipeline.execute()

        for key, value in zip(
            self.redis_client.scan_iter(match=f"{self._cache_key_prefix}*"), results
        ):
            if value is not None:
                key_values[key.removeprefix(self._cache_key_prefix)] = value.decode(
                    "utf-8"
                )

        return key_values

    def get(self, key: str) -> Optional[str]:
        """
        获取缓存值

        Args:
            key: 缓存键

        Returns:
            缓存的值，如果不存在或已过期则返回 None
        """
        cache_key = self._get_cache_key(key)
        value = self.redis_client.get(cache_key)

        if value is not None:
            # 更新访问时间
            pipeline = self.redis_client.pipeline()
            if self._cache_usage_key:
                pipeline.zadd(self._cache_usage_key, {key: time.time()})
            if self.ttl_seconds:
                pipeline.expire(cache_key, self.ttl_seconds)  # 重置过期时间
            pipeline.execute()

        return value

    def put(self, key: str, value: str):
        """
        添加或更新缓存条目

        Args:
            key: 缓存键
            value: 缓存值
        """
        # 检查容量并清理过期项
        if self.capacity > 0 and self._cache_usage_key:
            current_size = self.redis_client.zcard(self._cache_usage_key)
            if current_size >= self.capacity:
                # 获取最旧的项并删除
                oldest_items = self.redis_client.zrange(
                    self._cache_usage_key, 0, current_size - self.capacity
                )
                if oldest_items:
                    pipeline = self.redis_client.pipeline()
                    for old_key in oldest_items:
                        pipeline.delete(self._get_cache_key(old_key))
                        pipeline.zrem(self._cache_usage_key, old_key)
                    pipeline.execute()

        # 添加新项
        cache_key = self._get_cache_key(key)
        pipeline = self.redis_client.pipeline()
        pipeline.set(cache_key, value, ex=self.ttl_seconds)
        if self._cache_usage_key:
            pipeline.zadd(self._cache_usage_key, {key: time.time()})
        pipeline.execute()

        logger.info(f"Added key to cache: {key}")

    def delete(self, key: str):
        """删除缓存条目"""
        cache_key = self._get_cache_key(key)

        if self.redis_client.exists(cache_key):
            pipeline = self.redis_client.pipeline()
            pipeline.delete(cache_key)

            if self._cache_usage_key:
                pipeline.zrem(self._cache_usage_key, key)

            pipeline.execute()

            logger.info(f"Deleted key from cache: {key}")
        else:
            logger.info(f"Key not found in cache: {key}")

    def clear(self):
        """清空缓存"""
        # 获取所有缓存键
        keys_pattern = f"{self._cache_key_prefix}*"

        pipeline = self.redis_client.pipeline()
        # 删除所有缓存键
        for key in self.redis_client.scan_iter(match=keys_pattern):
            pipeline.delete(key)
        # 清除使用记录
        if self._cache_usage_key:
            pipeline.delete(self._cache_usage_key)
        pipeline.execute()

        logger.info("Cache cleared")

    def get_stats(self) -> dict:
        """
        获取缓存统计信息

        Returns:
            包含缓存统计信息的字典
        """
        # 获取未过期的键数量
        active_keys = sum(
            1 for _ in self.redis_client.scan_iter(match=f"{self._cache_key_prefix}*")
        )
        # 获取当前缓存大小
        current_size = (
            self.redis_client.zcard(self._cache_usage_key)
            if self._cache_usage_key
            else active_keys
        )

        return {
            "total_entries": current_size,
            "active_entries": active_keys,
            "capacity": self.capacity,
        }


# Emby Line Cache
emby_user_defined_line_cache = RedisCache(
    db=2,
    cache_key_prefix="emby_user_defined_line:",
)
emby_last_user_defined_line_cache = RedisCache(
    db=2, cache_key_prefix="emby_last_user_defined_line:"
)
# Plex line cache
plex_user_defined_line_cache = RedisCache(
    db=2,
    cache_key_prefix="plex_user_defined_line:",
)
plex_last_user_defined_line_cache = RedisCache(
    db=2, cache_key_prefix="plex_last_user_defined_line:"
)

# 高级线路管理
free_premium_lines_cache = RedisCache(
    db=2,
    cache_key_prefix="emby_free_premium_lines:",
    ttl_seconds=None,  # 持久化存储
)

# 线路标签管理
line_tags_cache = RedisCache(
    db=2,
    cache_key_prefix="emby_line_tags:",
    ttl_seconds=None,  # 持久化存储标签数据
)


def get_line_tags(line_name: str) -> list[str]:
    """从Redis获取线路的标签信息"""
    try:
        from app.cache import line_tags_cache

        # 从Redis获取线路标签
        tags_str = line_tags_cache.get(line_name)
        if tags_str:
            # Redis中存储的是逗号分隔的字符串
            tags = tags_str.split(",")
            return [tag.strip() for tag in tags if tag.strip()]
        else:
            # 如果Redis中没有该线路的标签，返回空列表
            return []
    except Exception as e:
        logger.error(f"获取线路 {line_name} 的标签失败: {str(e)}")
        return []


# 幸运大转盘缓存
lucky_wheel_config_cache = RedisCache(
    db=0,
    cache_key_prefix="luckywheel:",
    ttl_seconds=None,  # 持久化存储配置数据
)

# nginx stream url-based traffic
stream_traffic_cache = RedisCache(
    db=15,
    cache_key_prefix="",
)

# Emby API Key cache
emby_api_key_cache = RedisCache(
    db=3,
    cache_key_prefix="emby_api_key:",
)

# Plex token cache
plex_token_cache = RedisCache(
    db=3,
    cache_key_prefix="plex_token_cache:",
)

# 存储用户积分信息
user_credits_cache = RedisCache(
    db=0,
    cache_key_prefix="user_credits:",
)
