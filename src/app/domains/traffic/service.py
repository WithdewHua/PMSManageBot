"""Traffic quota and account-name workflows."""

from app.domains.traffic import repository as traffic_repository
from app.domains.traffic.config import TRAFFIC_CONFIG


def rename_user(old_username: str, new_username: str) -> bool:
    """Update raw and monthly traffic rows after an account rename."""
    return traffic_repository.TrafficRepository().update_traffic_username(
        old_username=old_username,
        new_username=new_username,
    )


def get_traffic_config():
    return TRAFFIC_CONFIG.get()


def get_user_traffic_limit() -> int:
    return int(TRAFFIC_CONFIG.get().user_traffic_limit)


def get_premium_user_traffic_limit() -> int:
    return int(TRAFFIC_CONFIG.get().premium_user_traffic_limit)


def set_user_traffic_limit(limit: int) -> int:
    return int(TRAFFIC_CONFIG.update(user_traffic_limit=limit).user_traffic_limit)


def set_premium_user_traffic_limit(limit: int) -> int:
    return int(
        TRAFFIC_CONFIG.update(
            premium_user_traffic_limit=limit
        ).premium_user_traffic_limit
    )


__all__ = [
    "get_premium_user_traffic_limit",
    "get_traffic_config",
    "get_user_traffic_limit",
    "rename_user",
    "set_premium_user_traffic_limit",
    "set_user_traffic_limit",
]
