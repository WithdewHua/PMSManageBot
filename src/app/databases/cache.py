import random
import time
import traceback
from typing import Optional

from app.databases.redis import Redis
from app.log import logger

GET_ALL_KEY_VALUES_SCRIPT = """
local cursor = "0"
local pattern = ARGV[1]
local count = tonumber(ARGV[2]) or 100
local result = {}

repeat
    local scan_result = redis.call("SCAN", cursor, "MATCH", pattern, "COUNT", count)
    cursor = scan_result[1]
    local keys = scan_result[2]

    for _, key in ipairs(keys) do
        local value = redis.call("GET", key)
        if value then
            table.insert(result, key)
            table.insert(result, value)
        end
    end
until cursor == "0"

return result
"""

GET_STATS_SCRIPT = """
local cursor = "0"
local pattern = ARGV[1]
local count = tonumber(ARGV[2]) or 100
local active_keys = 0

repeat
    local scan_result = redis.call("SCAN", cursor, "MATCH", pattern, "COUNT", count)
    cursor = scan_result[1]
    active_keys = active_keys + #scan_result[2]
until cursor == "0"

return active_keys
"""

try:
    from redis.exceptions import RedisError

    _REDIS_RETRY_EXCEPTIONS = (RedisError,)
except Exception:  # pragma: no cover
    # Fallback: if redis isn't importable for any reason, keep runtime from crashing.
    # In normal production this path should never be used.
    _REDIS_RETRY_EXCEPTIONS = (Exception,)


class RedisCache:
    _SCAN_COUNT = 100
    _BATCH_SIZE = 100

    def __init__(
        self,
        db: int = 0,
        capacity: int = 0,
        ttl_seconds: int = None,
        cache_key_prefix: str = "cache:",
        cache_usage_track: bool = False,
        retry_attempts: int = 5,
        retry_base_delay: float = 0.05,
        retry_max_delay: float = 1.0,
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

        self._retry_attempts = max(1, int(retry_attempts))
        self._retry_base_delay = max(0.0, float(retry_base_delay))
        self._retry_max_delay = max(0.0, float(retry_max_delay))

    def _call_with_retry(
        self,
        func,
        *,
        op: str,
        key: Optional[str] = None,
        attempts: Optional[int] = None,
        swallow: bool = False,
        default=None,
    ):
        """执行 Redis 操作并在网络波动时自动重试。

        - 指数退避: base_delay * 2^(attempt-1)
        - 抖动: 0 ~ 0.1s
        - 仅对 RedisError（或兜底 Exception）进行重试

        Args:
            func: 无参可调用对象
            op: 操作名，用于日志
            key: 关联 key（可选）
            attempts: 覆盖默认重试次数
            swallow: 失败后是否吞掉异常并返回 default
            default: swallow=True 时最终返回值
        """

        max_attempts = (
            self._retry_attempts if attempts is None else max(1, int(attempts))
        )
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                return func()
            except _REDIS_RETRY_EXCEPTIONS as e:
                last_exc = e
                if attempt >= max_attempts:
                    logger.error(
                        "Redis operation failed after retries: op=%s key=%s error=%s",
                        op,
                        key,
                        e,
                    )
                    if swallow:
                        return default
                    raise

                backoff = self._retry_base_delay * (2 ** (attempt - 1))
                wait_seconds = min(backoff, self._retry_max_delay)
                wait_seconds += random.uniform(0.0, 0.1)
                logger.warning(
                    "Redis operation error, retrying: op=%s key=%s attempt=%s/%s wait=%.3fs error=%s",
                    op,
                    key,
                    attempt,
                    max_attempts,
                    wait_seconds,
                    e,
                )
                time.sleep(wait_seconds)

        # 理论上不会走到这里
        if swallow:
            return default
        if last_exc:
            raise last_exc
        raise RuntimeError("Redis operation failed with unknown error")

    def _get_cache_key(self, key: str) -> str:
        """获取缓存键的完整Redis键名"""
        return f"{self._cache_key_prefix}{key}"

    def _iter_prefixed_keys(self):
        """分批扫描当前缓存前缀下的 keys，避免一次性拉取导致超时。"""
        cursor = 0
        match = f"{self._cache_key_prefix}*"
        while True:
            current_cursor = cursor
            cursor, keys = self._call_with_retry(
                lambda: self.redis_client.scan(
                    cursor=current_cursor,
                    match=match,
                    count=self._SCAN_COUNT,
                ),
                op="scan",
                key=match,
            )
            for key in keys:
                yield key
            if cursor == 0:
                break

    def _batched_prefixed_keys(self):
        batch = []
        for key in self._iter_prefixed_keys():
            batch.append(key)
            if len(batch) >= self._BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch

    def _get_all_key_values_via_lua(self) -> dict:
        result = self._call_with_retry(
            lambda: self.redis_client.eval(
                GET_ALL_KEY_VALUES_SCRIPT,
                0,
                f"{self._cache_key_prefix}*",
                self._SCAN_COUNT,
            ),
            op="eval_get_all_key_values",
            key=f"{self._cache_key_prefix}*",
        )

        key_values = {}
        for index in range(0, len(result), 2):
            key = result[index]
            value = result[index + 1]
            key_values[key.removeprefix(self._cache_key_prefix)] = value
        return key_values

    def _get_all_key_values_via_scan_get(self) -> dict:
        key_values: dict = {}
        for keys in self._batched_prefixed_keys():
            for key in keys:
                value = self._call_with_retry(
                    lambda key=key: self.redis_client.get(key),
                    op="get_batch_item",
                    key=key,
                )
                if value is not None:
                    key_values[key.removeprefix(self._cache_key_prefix)] = value
        return key_values

    def get_all(self) -> list:
        """
        获取所有缓存值
        """

        def _op():
            return list(self.get_all_key_values().values())

        return _op()

    def get_all_key_values(self) -> dict:
        """
        获取所有缓存键值对

        Returns:
            包含所有缓存键值对的字典
        """

        def _op():
            try:
                return self._get_all_key_values_via_lua()
            except Exception as e:
                logger.warning(
                    f"Redis Lua get_all_key_values failed, fallback to SCAN+GET: {e}"
                )
                return self._get_all_key_values_via_scan_get()

        return _op()

    def get(self, key: str) -> Optional[str]:
        """
        获取缓存值

        Args:
            key: 缓存键

        Returns:
            缓存的值，如果不存在或已过期则返回 None
        """
        cache_key = self._get_cache_key(key)

        def _op_get():
            return self.redis_client.get(cache_key)

        value = self._call_with_retry(_op_get, op="get", key=key)

        if value is not None:
            # 更新访问时间
            def _op_touch():
                pipeline = self.redis_client.pipeline()
                if self._cache_usage_key:
                    pipeline.zadd(self._cache_usage_key, {key: time.time()})
                if self.ttl_seconds:
                    pipeline.expire(cache_key, self.ttl_seconds)  # 重置过期时间
                pipeline.execute()

            # touch 失败不应影响 get 的返回
            self._call_with_retry(
                _op_touch,
                op="touch",
                key=key,
                swallow=True,
                default=None,
            )

        return value

    def put(self, key: str, value: str, max_retry: int = 3):
        """
        添加或更新缓存条目

        Args:
            key: 缓存键
            value: 缓存值
            max_retry: 最大重试次数
        """

        def _op():
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

            logger.debug(f"Added key to cache: {key}")

        try:
            # put 的失败历史上是“吞掉异常+日志”，这里保持不改变外部行为
            self._call_with_retry(
                _op,
                op="put",
                key=key,
                attempts=max_retry,
            )
        except Exception as e:
            logger.error(f"Failed to add key to cache: {key}, error: {e}")
            traceback.print_exc()

    def delete(self, key: str):
        """删除缓存条目"""
        cache_key = self._get_cache_key(key)

        def _op_exists():
            return self.redis_client.exists(cache_key)

        if self._call_with_retry(_op_exists, op="exists", key=key):

            def _op_del():
                pipeline = self.redis_client.pipeline()
                pipeline.delete(cache_key)

                if self._cache_usage_key:
                    pipeline.zrem(self._cache_usage_key, key)

                pipeline.execute()

            try:
                self._call_with_retry(_op_del, op="delete", key=key)
            except Exception as e:
                logger.error(f"Failed to delete key from cache: {key}, error: {e}")
                traceback.print_exc()
                return

            logger.info(f"Deleted key from cache: {key}")
        else:
            logger.info(f"Key not found in cache: {key}")

    def clear(self):
        """清空缓存"""

        def _op():
            # 获取所有缓存键
            deleted_count = 0
            for keys in self._batched_prefixed_keys():
                pipeline = self.redis_client.pipeline()
                for k in keys:
                    pipeline.delete(k)
                self._call_with_retry(
                    pipeline.execute,
                    op="delete_batch",
                    key=f"{self._cache_key_prefix}*[{len(keys)}]",
                )
                deleted_count += len(keys)

            # 清除使用记录
            if self._cache_usage_key:
                pipeline = self.redis_client.pipeline()
                pipeline.delete(self._cache_usage_key)
                self._call_with_retry(
                    pipeline.execute,
                    op="delete_usage_key",
                    key=self._cache_usage_key,
                )

            return deleted_count

        try:
            self._call_with_retry(_op, op="clear")
            logger.info("Cache cleared")
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
            traceback.print_exc()

    def get_stats(self) -> dict:
        """
        获取缓存统计信息

        Returns:
            包含缓存统计信息的字典
        """

        def _op():
            # 获取未过期的键数量
            active_keys = self._call_with_retry(
                lambda: self.redis_client.eval(
                    GET_STATS_SCRIPT,
                    0,
                    f"{self._cache_key_prefix}*",
                    self._SCAN_COUNT,
                ),
                op="eval_get_stats",
                key=f"{self._cache_key_prefix}*",
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

        # stats 失败不要影响主流程
        return self._call_with_retry(_op, op="get_stats", swallow=True, default={})


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


# nginx stream url-based traffic
stream_traffic_cache = RedisCache(
    db=15,
    cache_key_prefix="",
)

### API/Token ###
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

### User Info ###
# 存储用户积分信息
user_credits_cache = RedisCache(
    db=0,
    cache_key_prefix="user_credits:",
)
# 存储用户信息
user_info_cache = RedisCache(
    db=2,
    cache_key_prefix="user_info:",
)
