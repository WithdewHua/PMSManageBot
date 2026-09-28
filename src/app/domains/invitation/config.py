"""Invitation business configuration."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.core.domain_config import DomainConfig, FieldRows, LegacySource
from app.core.legacy_env import LEGACY_ENV


class InvitationConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    invitation_credits: StrictInt = Field(288, ge=0)


INVITATION_CONFIG = DomainConfig(
    "invitation",
    InvitationConfigModel,
    FieldRows("config.invitation"),
    legacy={"invitation_credits": LegacySource("INVITATION_CREDITS", LEGACY_ENV.read)},
)

__all__ = ["INVITATION_CONFIG", "InvitationConfigModel"]
