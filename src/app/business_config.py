"""Application assembly for all database-backed business configurations."""

from __future__ import annotations

from app.core.domain_config import DomainConfig, SeedReport
from app.core.legacy_env import LEGACY_ENV
from app.domains.accounts.config import ACCOUNTS_CONFIG
from app.domains.badges.config import BADGE_CENTER_CONFIG
from app.domains.blackjack.config import BLACKJACK_CONFIG
from app.domains.credits.config import CREDITS_CONFIG
from app.domains.crypto_donation.config import CRYPTO_DONATION_CONFIG
from app.domains.donation.config import DONATION_CONFIG
from app.domains.invitation.config import INVITATION_CONFIG
from app.domains.lines.config import LINES_CONFIG
from app.domains.luckywheel.config import RANDOMNESS_CONFIG, WHEEL_CONFIG
from app.domains.media_access.config import MEDIA_ACCESS_CONFIG
from app.domains.premium.config import PREMIUM_CONFIG
from app.domains.traffic.config import TRAFFIC_CONFIG
from app.domains.vaultwarden.config import VAULTWARDEN_CONFIG

CONFIGS: tuple[DomainConfig, ...] = (
    ACCOUNTS_CONFIG,
    INVITATION_CONFIG,
    PREMIUM_CONFIG,
    DONATION_CONFIG,
    CRYPTO_DONATION_CONFIG,
    LINES_CONFIG,
    TRAFFIC_CONFIG,
    MEDIA_ACCESS_CONFIG,
    VAULTWARDEN_CONFIG,
    CREDITS_CONFIG,
    BLACKJACK_CONFIG,
    WHEEL_CONFIG,
    RANDOMNESS_CONFIG,
    BADGE_CENTER_CONFIG,
)


def seed_all() -> list[SeedReport]:
    """Seed missing configuration rows without overwriting existing values."""
    LEGACY_ENV.warn_migrated_keys()
    reports = [config.seed() for config in CONFIGS]
    for report in reports:
        if report.inserted:
            from app.core.log import logger

            logger.info(
                "业务配置初始化: %s inserted=%s existing=%s",
                report.name,
                report.inserted,
                report.existing,
            )
    return reports


__all__ = ["CONFIGS", "seed_all"]
