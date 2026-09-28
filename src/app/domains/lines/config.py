"""Line-selection business configuration."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.core.domain_config import DomainConfig, FieldRows, LegacySource
from app.core.legacy_env import LEGACY_ENV


class LinesConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    premium_free: bool = False
    line_schedule_unlock_credits: StrictInt = Field(264, ge=0)


LINES_CONFIG = DomainConfig(
    "lines",
    LinesConfigModel,
    FieldRows("config.lines"),
    legacy={
        "premium_free": LegacySource("PREMIUM_FREE", LEGACY_ENV.read),
        "line_schedule_unlock_credits": LegacySource(
            "LINE_SCHEDULE_UNLOCK_CREDITS", LEGACY_ENV.read
        ),
    },
)

__all__ = ["LINES_CONFIG", "LinesConfigModel"]
