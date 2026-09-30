"""Pure rules for interpreting identity wide-table membership fields."""

from __future__ import annotations

from datetime import datetime
from typing import Any

_INVALID_EXPIRY_RAISE = object()


def _field(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def get_service_label(service: str) -> tuple[str, str]:
    """Return the stable display label and emoji for a media service."""
    return service.upper(), "🎬" if service == "plex" else "📺"


def premium_flag_set(row: Any) -> bool:
    """Return whether the persisted Premium flag is set, ignoring expiry."""
    return int(_field(row, "is_premium", 0) or 0) == 1


def premium_active(
    row: Any,
    now: datetime,
    *,
    invalid_expiry: bool | None = False,
) -> bool:
    """Return whether Premium is active at ``now``.

    A missing expiry means permanent membership.  Callers may select the
    historical fallback for malformed expiry values with ``invalid_expiry``;
    the default is conservative and treats malformed values as inactive.
    """
    if not premium_flag_set(row):
        return False
    raw_expiry = _field(row, "premium_expiry_time")
    if not raw_expiry:
        return True
    try:
        expiry = (
            raw_expiry
            if isinstance(raw_expiry, datetime)
            else datetime.fromisoformat(str(raw_expiry))
        )
        if expiry.tzinfo is None and now.tzinfo is not None:
            expiry = expiry.replace(tzinfo=now.tzinfo)
        return expiry > now
    except (TypeError, ValueError, OverflowError):
        if invalid_expiry is None:
            raise
        return bool(invalid_expiry)


__all__ = ["get_service_label", "premium_active", "premium_flag_set"]
