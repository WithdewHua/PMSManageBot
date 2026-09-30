"""Source-owned wheel events, one per successful request."""

from dataclasses import dataclass

from app.core.events import DomainEvent


@dataclass(frozen=True, slots=True)
class WheelSpun(DomainEvent):
    tg_id: int
