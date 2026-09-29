"""Pure treasure-domain random-seed rules."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

SIGNED_BIGINT_MAX = (1 << 63) - 1


def normalize_external_random_b(
    value: int | None, *, default: int | None = None
) -> int | None:
    """Map an external integer to PostgreSQL signed BIGINT-safe range."""
    if value is None:
        return default
    return int(value) & SIGNED_BIGINT_MAX


def fallback_external_random_b(
    *,
    issue_id: int,
    issue: dict[str, Any] | None,
    quantity: int,
    tg_id: int,
    timestamp_ms: int,
    secret: str,
) -> int | None:
    """Derive a deterministic fallback seed without reading configuration."""
    if not issue:
        return None
    total_shares = int(issue.get("total_shares", 0))
    shares_sold = int(issue.get("shares_sold", 0))
    remaining = total_shares - shares_sold
    if remaining <= 0 or int(quantity) < remaining:
        return None
    if not secret:
        raise RuntimeError("TG_API_TOKEN not configured")
    message = (
        f"treasure|fallback_b|issue_id={int(issue_id)}|"
        f"total={total_shares}|sold={shares_sold}|qty={int(quantity)}|"
        f"tg_id={int(tg_id)}|ts_ms={int(timestamp_ms)}"
    ).encode()
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return normalize_external_random_b(int.from_bytes(digest[:8], "big", signed=False))
