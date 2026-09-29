"""Media-access business configuration."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.core.domain_config import DomainConfig, FieldRows, LegacySource


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
        "unlock_credits": LegacySource("UNLOCK_CREDITS", default=100),
        "download_unlock_credits": LegacySource("DOWNLOAD_UNLOCK_CREDITS", default=368),
        "nsfw_libs": LegacySource(
            "NSFW_LIBS", default=["NSFW", "NC17 Movies", "Hentai"]
        ),
    },
)

__all__ = ["MEDIA_ACCESS_CONFIG", "MediaAccessConfigModel"]
