"""Cash-game activity events; timeout and tournament paths do not emit these."""

from dataclasses import dataclass

from app.core.events import DomainEvent


@dataclass(frozen=True, slots=True)
class CashHandPlayed(DomainEvent):
    tg_id: int
