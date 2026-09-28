"""Export database-backed business settings as a legacy ``.env`` fragment.

The command is intentionally read-only.  It queries existing ``SystemConfig``
rows directly and never calls ``DomainConfig.get``/``seed`` because those APIs
may insert missing defaults.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.core.db import get_session
from app.core.kv import SystemConfig

LEGACY_KEYS: dict[tuple[str, str], str] = {
    ("config.accounts", "plex_register"): "PLEX_REGISTER",
    ("config.accounts", "emby_register"): "EMBY_REGISTER",
    ("config.invitation", "invitation_credits"): "INVITATION_CREDITS",
    ("config.premium", "premium_unlock_enabled"): "PREMIUM_UNLOCK_ENABLED",
    ("config.premium", "premium_daily_credits"): "PREMIUM_DAILY_CREDITS",
    ("config.premium", "credits_cost_per_10gb"): "CREDITS_COST_PER_10GB",
    ("config.donation", "donation_multiplier"): "DONATION_MULTIPLIER",
    ("config.crypto_donation", "upay_crypto_types"): "UPAY_CRYPTO_TYPES",
    ("config.lines", "premium_free"): "PREMIUM_FREE",
    ("config.lines", "line_schedule_unlock_credits"): "LINE_SCHEDULE_UNLOCK_CREDITS",
    ("config.traffic", "user_traffic_limit"): "USER_TRAFFIC_LIMIT",
    ("config.traffic", "premium_user_traffic_limit"): "PREMIUM_USER_TRAFFIC_LIMIT",
    ("config.media_access", "unlock_credits"): "UNLOCK_CREDITS",
    ("config.media_access", "download_unlock_credits"): "DOWNLOAD_UNLOCK_CREDITS",
    ("config.media_access", "nsfw_libs"): "NSFW_LIBS",
    ("config.vaultwarden", "enabled"): "VAULTWARDEN_ENABLED",
    ("config.vaultwarden", "redeem_credits"): "VAULTWARDEN_REDEEM_CREDITS",
    ("config.credits", "transfer_enabled"): "CREDITS_TRANSFER_ENABLED",
}


def _format_value(raw: str) -> str:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def export_lines() -> list[str]:
    """Return sorted legacy ``KEY=value`` lines for rows that exist."""
    with get_session() as session:
        rows = session.execute(
            select(
                SystemConfig.config_type,
                SystemConfig.config_key,
                SystemConfig.config_value,
            )
        ).all()
    values = {
        LEGACY_KEYS[(config_type, config_key)]: _format_value(config_value)
        for config_type, config_key, config_value in rows
        if (config_type, config_key) in LEGACY_KEYS
    }
    return [f"{key}={values[key]}" for key in sorted(values)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write the fragment to this file")
    args = parser.parse_args()
    content = "\n".join(export_lines()) + "\n"
    if args.output:
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
