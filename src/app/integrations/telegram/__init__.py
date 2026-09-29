"""Telegram outbound integration and local profile cache adapters."""

from app.integrations.telegram.messaging import send_message, send_message_by_url
from app.integrations.telegram.profiles import (
    get_user_avatar_from_tg_id,
    get_user_info_from_tg_id,
    get_user_name_from_tg_id,
    get_user_names_from_tg_ids,
    refresh_tg_user_info,
    refresh_tg_user_profile,
)

__all__ = [
    "get_user_avatar_from_tg_id",
    "get_user_info_from_tg_id",
    "get_user_name_from_tg_id",
    "get_user_names_from_tg_ids",
    "refresh_tg_user_info",
    "refresh_tg_user_profile",
    "send_message",
    "send_message_by_url",
]
