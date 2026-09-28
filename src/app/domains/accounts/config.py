"""Accounts business configuration."""

from pydantic import BaseModel, ConfigDict

from app.core.domain_config import DomainConfig, FieldRows, LegacySource
from app.core.legacy_env import LEGACY_ENV


class AccountsConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    plex_register: bool = False
    emby_register: bool = True


ACCOUNTS_CONFIG = DomainConfig(
    "accounts",
    AccountsConfigModel,
    FieldRows("config.accounts"),
    legacy={
        "plex_register": LegacySource("PLEX_REGISTER", LEGACY_ENV.read),
        "emby_register": LegacySource("EMBY_REGISTER", LEGACY_ENV.read),
    },
)

__all__ = ["ACCOUNTS_CONFIG", "AccountsConfigModel"]
