"""Premium business configuration."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.core.domain_config import DomainConfig, FieldRows, LegacySource


class PremiumConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    premium_unlock_enabled: bool = False
    premium_daily_credits: StrictInt = Field(15, ge=0)
    credits_cost_per_10gb: StrictInt = Field(5, ge=0)


PREMIUM_CONFIG = DomainConfig(
    "premium",
    PremiumConfigModel,
    FieldRows("config.premium"),
    legacy={
        "premium_unlock_enabled": LegacySource("PREMIUM_UNLOCK_ENABLED", default=False),
        "premium_daily_credits": LegacySource("PREMIUM_DAILY_CREDITS", default=15),
        "credits_cost_per_10gb": LegacySource("CREDITS_COST_PER_10GB", default=5),
    },
)

__all__ = ["PREMIUM_CONFIG", "PremiumConfigModel"]
