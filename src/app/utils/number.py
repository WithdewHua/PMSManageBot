#!/usr/bin/env python3

SIGNED_BIGINT_MAX = (1 << 63) - 1


def normalize_external_random_b(
    value: int | None, *, default: int | None = None
) -> int | None:
    """Normalize value to PostgreSQL signed BIGINT-safe range [0, 2^63-1]."""

    if value is None:
        return default
    return int(value) & SIGNED_BIGINT_MAX
