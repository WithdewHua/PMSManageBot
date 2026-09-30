"""Source-owned prediction activity events."""

from dataclasses import dataclass

from app.core.events import DomainEvent


@dataclass(frozen=True, slots=True)
class PredictionBetPlaced(DomainEvent):
    tg_id: int
