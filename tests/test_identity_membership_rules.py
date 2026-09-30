from datetime import UTC, datetime
from types import SimpleNamespace

from app.domains.identity.rules import premium_active, premium_flag_set


def test_premium_flag_set_ignores_expiry() -> None:
    assert premium_flag_set(SimpleNamespace(is_premium=1, premium_expiry_time="bad"))
    assert not premium_flag_set(SimpleNamespace(is_premium=0, premium_expiry_time=None))


def test_premium_active_supports_permanent_and_expired_members() -> None:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    assert premium_active(SimpleNamespace(is_premium=1, premium_expiry_time=None), now)
    assert premium_active(
        SimpleNamespace(is_premium=1, premium_expiry_time="2026-10-01T00:00:00+00:00"),
        now,
    )
    assert not premium_active(
        SimpleNamespace(is_premium=1, premium_expiry_time="2026-09-29T00:00:00+00:00"),
        now,
    )


def test_premium_active_invalid_expiry_uses_explicit_fallback() -> None:
    row = SimpleNamespace(is_premium=1, premium_expiry_time="not-a-date")
    now = datetime(2026, 9, 30, tzinfo=UTC)
    assert not premium_active(row, now)
    assert premium_active(row, now, invalid_expiry=True)
