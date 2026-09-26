"""Scheduled profile jobs."""

from app.domains.profile.service import refresh_tg_user_info

__all__ = ["refresh_tg_user_info"]
