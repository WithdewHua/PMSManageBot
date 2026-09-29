"""Pure Telegram WebApp initData verification."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from time import time as current_time
from typing import NamedTuple

MOCK_AUTH_HASH = "mock_hash_for_development"
MAX_FUTURE_AUTH_DATE_SECONDS = 5 * 60


class TelegramVerificationResult(NamedTuple):
    """Result of validating a Telegram WebApp initData mapping."""

    valid: bool
    reason: str | None = None

    def __bool__(self) -> bool:
        return self.valid


def verify_telegram_data(
    data: Mapping[str, object],
    bot_token: str,
    max_age: int,
    *,
    now: int | None = None,
) -> TelegramVerificationResult:
    """Validate signature and replay-protection timestamps without app settings."""
    received_hash = data.get("hash")
    if not received_hash:
        return TelegramVerificationResult(False, "missing_hash")

    auth_date = data.get("auth_date")
    if auth_date is None or str(auth_date).strip() == "":
        return TelegramVerificationResult(False, "missing_auth_date")
    try:
        auth_timestamp = int(auth_date)
    except (TypeError, ValueError):
        return TelegramVerificationResult(False, "invalid_auth_date")

    timestamp = int(current_time() if now is None else now)
    if auth_timestamp < timestamp - max_age:
        return TelegramVerificationResult(False, "expired")
    if auth_timestamp > timestamp + MAX_FUTURE_AUTH_DATE_SECONDS:
        return TelegramVerificationResult(False, "future_auth_date")

    data_check = {key: value for key, value in data.items() if key != "hash"}
    data_check_string = "\n".join(
        f"{key}={data_check[key]}" for key in sorted(data_check)
    )
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode(), digestmod=hashlib.sha256
    ).digest()
    calculated_hash = hmac.new(
        secret_key, data_check_string.encode(), digestmod=hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(calculated_hash, str(received_hash)):
        return TelegramVerificationResult(False, "invalid_signature")
    return TelegramVerificationResult(True)
