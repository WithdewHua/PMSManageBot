"""Vaultwarden business configuration."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.core.domain_config import DomainConfig, FieldRows, LegacySource


class VaultwardenConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    redeem_credits: StrictInt = Field(500, ge=0)


VAULTWARDEN_CONFIG = DomainConfig(
    "vaultwarden",
    VaultwardenConfigModel,
    FieldRows("config.vaultwarden"),
    legacy={
        "enabled": LegacySource("VAULTWARDEN_ENABLED", default=False),
        "redeem_credits": LegacySource("VAULTWARDEN_REDEEM_CREDITS", default=500),
    },
)

__all__ = ["VAULTWARDEN_CONFIG", "VaultwardenConfigModel"]
