"""Accounts business configuration."""

from pydantic import BaseModel, ConfigDict

from app.core.domain_config import DomainConfig, FieldRows, LegacySource


class AccountsConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    plex_register: bool = False
    emby_register: bool = True


ACCOUNTS_CONFIG = DomainConfig(
    "accounts",
    AccountsConfigModel,
    FieldRows("config.accounts"),
    legacy={
        "plex_register": LegacySource("PLEX_REGISTER", default=False),
        "emby_register": LegacySource("EMBY_REGISTER", default=True),
    },
)

__all__ = ["ACCOUNTS_CONFIG", "AccountsConfigModel"]
