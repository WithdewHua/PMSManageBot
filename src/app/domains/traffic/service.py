"""Traffic workflows and read-model APIs."""

from __future__ import annotations

from datetime import datetime

from app.core.log import logger
from app.domains.traffic import repository as traffic_repository
from app.domains.traffic.cache import stream_traffic_cache
from app.domains.traffic.config import TRAFFIC_CONFIG

SOURCE_QUEUE = "filebeat_nginx_stream_logs"
PROCESSING_QUEUE = "filebeat_nginx_stream_logs_processing"


def daily_usage(
    username: str | None = None,
    user_id: str | None = None,
    service: str | None = None,
    date: datetime | None = None,
    premium_only: bool = False,
    premium_lines: list[str] | None = None,
) -> int:
    if premium_only and premium_lines is None:
        from app.domains.lines import service as lines_service

        premium_lines = lines_service.get_premium_lines()
    return traffic_repository.get_user_daily_traffic(
        username=username,
        user_id=user_id,
        service=service,
        date=date,
        premium_only=premium_only,
        premium_lines=premium_lines,
    )


def premium_line_statistics() -> list:
    from app.domains.lines import service as lines_service

    premium_lines = lines_service.get_premium_lines()
    return traffic_repository.get_premium_line_traffic_statistics(
        premium_lines=premium_lines
    )


def traffic_rank(service: str, start_date=None, end_date=None) -> list:
    if service == "plex":
        return traffic_repository.get_plex_traffic_rank(start_date, end_date)
    if service == "emby":
        return traffic_repository.get_emby_traffic_rank(start_date, end_date)
    raise ValueError(f"Unsupported traffic service: {service}")


def rename_user(old_username: str, new_username: str) -> bool:
    """Update raw and monthly traffic rows after an account rename."""
    return traffic_repository.update_traffic_username(
        old_username=old_username,
        new_username=new_username,
    )


def aggregate_monthly_traffic_data(target_month: str | None = None) -> tuple:
    return traffic_repository.aggregate_monthly_traffic_data(target_month)


def cleanup_monthly_traffic_data(target_month: str) -> tuple:
    return traffic_repository.cleanup_monthly_traffic_data(target_month)


def store_traffic_batch(rows: list[dict], **kwargs) -> dict[str, str]:
    return traffic_repository.bulk_create_line_traffic_entries(rows, **kwargs)


def get_user_daily_traffic(*args, **kwargs) -> int:
    return daily_usage(*args, **kwargs)


def get_username_to_id_mappings() -> tuple[dict[str, int], dict[str, str]]:
    return traffic_repository.get_media_username_to_id_maps()


async def _get_line_monthly_traffic(
    session,
    line_domain: str,
    year_month: str,
    owner_tg_id: int | None = None,
    from_raw_table: bool = False,
) -> float:
    """Compatibility coroutine around the caller-owned transaction helper."""
    from app.domains.identity import service as identity_service

    owner_usernames: set[str] = set()
    if owner_tg_id is not None:
        try:
            plex_user = identity_service.get_plex_info_by_tg_id(owner_tg_id)
            if plex_user and plex_user[4]:
                owner_usernames.add(plex_user[4].lower())
            emby_user = identity_service.get_emby_info_by_tg_id(owner_tg_id)
            if emby_user and emby_user[0]:
                owner_usernames.add(emby_user[0].lower())
        except Exception:
            logger.exception(
                "Failed to read line owner information, returning 0 traffic by legacy behavior"
            )
            return 0.0
    traffic_repository.execute(session)
    return traffic_repository.get_line_monthly_traffic_tx(
        session,
        line_domain,
        year_month,
        owner_tg_id=None,
        from_raw_table=from_raw_table,
        owner_usernames=owner_usernames,
    )


def get_premium_line_traffic_statistics() -> list:
    return premium_line_statistics()


def get_plex_traffic_rank(start_date=None, end_date=None) -> list:
    return traffic_rank("plex", start_date, end_date)


def get_emby_traffic_rank(start_date=None, end_date=None) -> list:
    return traffic_rank("emby", start_date, end_date)


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


def move_source_logs_to_processing_queue(fetch_count: int) -> list:
    """Atomically move at most ``fetch_count`` source entries for processing."""
    if fetch_count <= 0:
        return []
    script = """
local source_queue = KEYS[1]
local processing_queue = KEYS[2]
local fetch_count = tonumber(ARGV[1]) or 0
local moved = {}
if fetch_count <= 0 then return moved end
for i = 1, fetch_count do
    local value = redis.call('LPOP', source_queue)
    if not value then break end
    moved[#moved + 1] = value
    redis.call('RPUSH', processing_queue, value)
end
return moved
"""
    return (
        stream_traffic_cache.redis_client.eval(
            script, 2, SOURCE_QUEUE, PROCESSING_QUEUE, fetch_count
        )
        or []
    )


def finalize_processing_logs(
    processed_log_count: int, failed_positions: list[int]
) -> None:
    """Acknowledge processed entries while pushing transient failures back."""
    if processed_log_count <= 0:
        return
    script = """
local processing_queue = KEYS[1]
local processed_log_count = tonumber(ARGV[1]) or 0
local failed_positions = {}
local failed_values = {}
for i = 2, #ARGV do failed_positions[tonumber(ARGV[i])] = true end
for i = 1, processed_log_count do
    local value = redis.call('LPOP', processing_queue)
    if not value then break end
    if failed_positions[i] then failed_values[#failed_values + 1] = value end
end
for i = 1, #failed_values do redis.call('RPUSH', processing_queue, failed_values[i]) end
return #failed_values
"""
    stream_traffic_cache.redis_client.eval(
        script, 1, PROCESSING_QUEUE, processed_log_count, *failed_positions
    )


__all__ = [
    "PROCESSING_QUEUE",
    "SOURCE_QUEUE",
    "aggregate_monthly_traffic_data",
    "cleanup_monthly_traffic_data",
    "daily_usage",
    "finalize_processing_logs",
    "get_emby_traffic_rank",
    "get_plex_traffic_rank",
    "get_premium_line_traffic_statistics",
    "get_premium_user_traffic_limit",
    "get_traffic_config",
    "get_user_daily_traffic",
    "get_user_traffic_limit",
    "move_source_logs_to_processing_queue",
    "premium_line_statistics",
    "rename_user",
    "set_premium_user_traffic_limit",
    "set_user_traffic_limit",
    "store_traffic_batch",
    "traffic_rank",
]
