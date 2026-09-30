"""Source-owned treasure activity events."""

from dataclasses import dataclass

from app.core.events import DomainEvent


@dataclass(frozen=True, slots=True)
class TreasureJoined(DomainEvent):
    tg_id: int
