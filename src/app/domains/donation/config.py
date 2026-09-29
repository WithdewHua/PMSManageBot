"""Donation business configuration."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.core.domain_config import DomainConfig, FieldRows, LegacySource


class DonationConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    donation_multiplier: StrictInt = Field(5, ge=0)


DONATION_CONFIG = DomainConfig(
    "donation",
    DonationConfigModel,
    FieldRows("config.donation"),
    legacy={"donation_multiplier": LegacySource("DONATION_MULTIPLIER", default=5)},
)

__all__ = ["DONATION_CONFIG", "DonationConfigModel"]
