"""Invitation business configuration."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.core.domain_config import DomainConfig, FieldRows, LegacySource


class InvitationConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    invitation_credits: StrictInt = Field(288, ge=0)


INVITATION_CONFIG = DomainConfig(
    "invitation",
    InvitationConfigModel,
    FieldRows("config.invitation"),
    legacy={"invitation_credits": LegacySource("INVITATION_CREDITS", default=288)},
)

__all__ = ["INVITATION_CONFIG", "InvitationConfigModel"]
