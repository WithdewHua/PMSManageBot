"""Rehearse business-config migration, restart persistence, and legacy export."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    if not args.url.startswith("postgresql"):
        raise SystemExit("business config rehearsal requires a PostgreSQL URL")

    os.environ.update(
        {
            "DATABASE_URL": args.url,
            "DATABASE_TYPE": "postgresql",
            "DATA_DIR": tempfile.mkdtemp(prefix="pms-business-config-"),
            "INVITATION_CREDITS": "321",
            "PREMIUM_UNLOCK_ENABLED": "true",
            "PREMIUM_DAILY_CREDITS": "19",
            "CREDITS_COST_PER_10GB": "7",
            "DONATION_MULTIPLIER": "6",
            "UPAY_CRYPTO_TYPES": "USDT-BSC,USDC-Polygon",
            "PREMIUM_FREE": "true",
            "LINE_SCHEDULE_UNLOCK_CREDITS": "275",
            "USER_TRAFFIC_LIMIT": "111",
            "PREMIUM_USER_TRAFFIC_LIMIT": "222",
            "UNLOCK_CREDITS": "123",
            "DOWNLOAD_UNLOCK_CREDITS": "456",
            "NSFW_LIBS": "Private,Kids",
            "VAULTWARDEN_ENABLED": "true",
            "VAULTWARDEN_REDEEM_CREDITS": "789",
            "CREDITS_TRANSFER_ENABLED": "false",
        }
    )

    from sqlalchemy.orm import sessionmaker

    import app.core.db as db_module
    from app.business_config import LEGACY_ENV, seed_all
    from app.domains.donation import service as donation_service
    from app.domains.donation.config import DONATION_CONFIG
    from app.domains.invitation import service as invitation_service
    from app.domains.invitation.config import INVITATION_CONFIG
    from app.domains.media_access import service as media_access_service
    from app.domains.media_access.config import MEDIA_ACCESS_CONFIG
    from app.domains.premium import service as premium_service
    from app.domains.premium.config import PREMIUM_CONFIG
    from app.domains.vaultwarden import service as vaultwarden_service
    from app.domains.vaultwarden.config import VAULTWARDEN_CONFIG
    from app.model_registry import metadata
    from scripts.export_business_config import export_lines

    engine = db_module.create_engine(
        args.url, pool_size=10, max_overflow=10, pool_pre_ping=True
    )
    metadata.drop_all(engine)
    metadata.create_all(engine)
    db_module.engine = engine
    db_module.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )

    reports = seed_all()
    assert reports and all(report.inserted >= 0 for report in reports)
    assert invitation_service.get_invitation_credits() == 321
    assert premium_service.get_premium_daily_credits() == 19
    assert donation_service.get_donation_multiplier() == 6
    assert media_access_service.get_nsfw_libs() == ["Private", "Kids"]
    assert vaultwarden_service.get_redeem_credits() == 789

    premium_service.set_premium_daily_credits(31)
    donation_service.set_donation_multiplier(11)
    for config in (
        INVITATION_CONFIG,
        PREMIUM_CONFIG,
        DONATION_CONFIG,
        MEDIA_ACCESS_CONFIG,
        VAULTWARDEN_CONFIG,
    ):
        config.invalidate()
    assert premium_service.get_premium_daily_credits() == 31
    assert donation_service.get_donation_multiplier() == 11

    exported = "\n".join(export_lines()) + "\n"
    env_path = Path(os.environ["DATA_DIR"]) / ".env"
    env_path.write_text(exported, encoding="utf-8")
    assert LEGACY_ENV.read("PREMIUM_DAILY_CREDITS") == 31
    assert LEGACY_ENV.read("DONATION_MULTIPLIER") == 11

    print(
        {
            "ok": True,
            "seeded": len(reports),
            "exported_keys": len(export_lines()),
            "premium_daily_credits": premium_service.get_premium_daily_credits(),
            "donation_multiplier": donation_service.get_donation_multiplier(),
        }
    )
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
