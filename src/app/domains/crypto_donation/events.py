"""Source-owned completed crypto donation events."""

from dataclasses import dataclass

from app.core.events import DomainEvent


@dataclass(frozen=True, slots=True)
class CryptoDonationCompleted(DomainEvent):
    tg_id: int
