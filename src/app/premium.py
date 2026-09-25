"""Compatibility entry point for scheduled Premium tasks.

Business implementations live in ``app.domains.premium.service``. These
wrappers retain the persisted APScheduler import paths while the job-reference
migration is deferred to the dedicated scheduling task.
"""

from __future__ import annotations

from app.domains.premium import service as _service
from app.domains.premium.service import (
    apply_download_unlock_to_media,
    format_premium_statistics_message,
    sync_media_permission,
    unbind_premium_line,
    update_premium_status,
)


async def check_premium_expiry():
    return await _service.check_premium_expiry()


async def check_premium_expiring_soon(days: int = 3):
    return await _service.check_premium_expiring_soon(days)


async def get_and_send_premium_statistics():
    return await _service.get_and_send_premium_statistics()


__all__ = [
    "apply_download_unlock_to_media",
    "check_premium_expiring_soon",
    "check_premium_expiry",
    "format_premium_statistics_message",
    "get_and_send_premium_statistics",
    "sync_media_permission",
    "unbind_premium_line",
    "update_premium_status",
]
