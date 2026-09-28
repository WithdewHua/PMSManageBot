"""Credits business configuration."""

from pydantic import BaseModel, ConfigDict

from app.core.domain_config import DomainConfig, FieldRows, LegacySource
from app.core.legacy_env import LEGACY_ENV


class CreditsConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    transfer_enabled: bool = True


CREDITS_CONFIG = DomainConfig(
    "credits",
    CreditsConfigModel,
    FieldRows("config.credits"),
    legacy={
        "transfer_enabled": LegacySource("CREDITS_TRANSFER_ENABLED", LEGACY_ENV.read)
    },
)

__all__ = ["CREDITS_CONFIG", "CreditsConfigModel"]
