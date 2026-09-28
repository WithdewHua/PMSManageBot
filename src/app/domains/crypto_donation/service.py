"""Crypto donation configuration accessors."""

from app.domains.crypto_donation.config import CRYPTO_DONATION_CONFIG


def get_supported_crypto_types() -> list[str]:
    return list(CRYPTO_DONATION_CONFIG.get().upay_crypto_types)


def set_supported_crypto_types(values: list[str]) -> list[str]:
    return list(
        CRYPTO_DONATION_CONFIG.update(upay_crypto_types=values).upay_crypto_types
    )
