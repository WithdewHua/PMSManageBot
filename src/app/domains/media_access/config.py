"""Media-access business configuration."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.core.domain_config import DomainConfig, FieldRows, LegacySource
from app.core.legacy_env import LEGACY_ENV


class MediaAccessConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    unlock_credits: StrictInt = Field(100, ge=0)
    download_unlock_credits: StrictInt = Field(368, ge=0)
    nsfw_libs: list[str] = Field(
        default_factory=lambda: ["NSFW", "NC17 Movies", "Hentai"]
    )


MEDIA_ACCESS_CONFIG = DomainConfig(
    "media_access",
    MediaAccessConfigModel,
    FieldRows("config.media_access"),
    legacy={
        "unlock_credits": LegacySource("UNLOCK_CREDITS", LEGACY_ENV.read),
        "download_unlock_credits": LegacySource(
            "DOWNLOAD_UNLOCK_CREDITS", LEGACY_ENV.read
        ),
        "nsfw_libs": LegacySource("NSFW_LIBS", LEGACY_ENV.read),
    },
)

__all__ = ["MEDIA_ACCESS_CONFIG", "MediaAccessConfigModel"]
