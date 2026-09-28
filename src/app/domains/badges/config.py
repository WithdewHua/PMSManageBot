"""Badge-center runtime configuration stored under its legacy SystemConfig keys."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.core.domain_config import DomainConfig, FieldRows, FieldSpec


def _encode_enabled(value: bool) -> str:
    return "1" if value else "0"


def _decode_enabled(value: str) -> bool:
    return value == "1"


def _encode_message(value: str | None) -> str:
    return value or ""


def _decode_message(value: str) -> str | None:
    return value or None


class BadgeCenterConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    message: str | None = None


BADGE_CENTER_CONFIG = DomainConfig(
    "badges.center",
    BadgeCenterConfigModel,
    FieldRows(
        "badge_center",
        fields={
            "enabled": FieldSpec(
                key="enabled",
                encode=_encode_enabled,
                decode=_decode_enabled,
            ),
            "message": FieldSpec(
                key="message",
                encode=_encode_message,
                decode=_decode_message,
            ),
        },
    ),
)


__all__ = ["BADGE_CENTER_CONFIG", "BadgeCenterConfigModel"]
