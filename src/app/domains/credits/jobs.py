"""Scheduled refresh of gateway credit caches."""

from app.core.log import logger
from app.domains.credits import service


def rewrite_users_credits_to_redis() -> None:
    """将用户积分信息写入 redis 缓存"""
    try:
        service.refresh_balance_cache()
    except Exception as error:
        logger.error(f"检查用户积分时发生错误: {error}")
