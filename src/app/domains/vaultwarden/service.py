"""Vaultwarden business configuration accessors."""

from app.domains.vaultwarden.config import VAULTWARDEN_CONFIG


def get_vaultwarden_config():
    return VAULTWARDEN_CONFIG.get()


def is_enabled() -> bool:
    return bool(VAULTWARDEN_CONFIG.get().enabled)


def get_redeem_credits() -> int:
    return int(VAULTWARDEN_CONFIG.get().redeem_credits)


def set_enabled(enabled: bool):
    return VAULTWARDEN_CONFIG.update(enabled=enabled)


def set_redeem_credits(credits: int) -> int:
    return int(VAULTWARDEN_CONFIG.update(redeem_credits=credits).redeem_credits)
