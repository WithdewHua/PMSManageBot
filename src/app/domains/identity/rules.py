"""Pure rules for interpreting identity wide-table membership fields."""

from __future__ import annotations

from app.domains.identity.types import (
    premium_active,
    premium_flag_set,
)

_INVALID_EXPIRY_RAISE = object()


def get_service_label(service: str) -> tuple[str, str]:
    """Return the stable display label and emoji for a media service."""
    return service.upper(), "🎬" if service == "plex" else "📺"


__all__ = ["get_service_label", "premium_active", "premium_flag_set"]
