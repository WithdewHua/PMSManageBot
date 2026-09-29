"""Pure custom-line business rules."""

from __future__ import annotations

from datetime import datetime, tzinfo


def month_key(now: datetime, tz: tzinfo) -> str:
    """Return the local calendar month for an aware or naive datetime."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)
    return now.strftime("%Y-%m")
