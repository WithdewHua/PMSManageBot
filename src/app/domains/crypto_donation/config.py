"""Crypto donation business configuration."""

from pydantic import BaseModel, ConfigDict, Field

from app.core.domain_config import DomainConfig, FieldRows, LegacySource

_DEFAULT_CRYPTO_TYPES = [
    "USDC-Polygon",
    "USDC-ArbitrumOne",
    "USDC-BSC",
    "USDC-ERC20",
    "USDT-Polygon",
    "USDT-ArbitrumOne",
    "USDT-BSC",
    "USDT-ERC20",
]


class CryptoDonationConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    upay_crypto_types: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_CRYPTO_TYPES)
    )


CRYPTO_DONATION_CONFIG = DomainConfig(
    "crypto_donation",
    CryptoDonationConfigModel,
    FieldRows("config.crypto_donation"),
    legacy={
        "upay_crypto_types": LegacySource(
            "UPAY_CRYPTO_TYPES", default=_DEFAULT_CRYPTO_TYPES
        )
    },
)

__all__ = ["CRYPTO_DONATION_CONFIG", "CryptoDonationConfigModel"]
