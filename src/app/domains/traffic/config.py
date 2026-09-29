"""Traffic quota business configuration."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.core.domain_config import DomainConfig, FieldRows, LegacySource


class TrafficConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_traffic_limit: StrictInt = Field(12 * 1024 * 1024 * 1024, ge=0)
    premium_user_traffic_limit: StrictInt = Field(24 * 1024 * 1024 * 1024, ge=0)


TRAFFIC_CONFIG = DomainConfig(
    "traffic",
    TrafficConfigModel,
    FieldRows("config.traffic"),
    legacy={
        "user_traffic_limit": LegacySource(
            "USER_TRAFFIC_LIMIT", default=12 * 1024 * 1024 * 1024
        ),
        "premium_user_traffic_limit": LegacySource(
            "PREMIUM_USER_TRAFFIC_LIMIT", default=24 * 1024 * 1024 * 1024
        ),
    },
)

__all__ = ["TRAFFIC_CONFIG", "TrafficConfigModel"]
