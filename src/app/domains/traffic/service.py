"""Traffic quota configuration workflows."""

from app.domains.traffic.config import TRAFFIC_CONFIG


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
    "set_premium_user_traffic_limit",
    "set_user_traffic_limit",
]
