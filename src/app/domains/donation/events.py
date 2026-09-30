"""Source-owned donation events; manual bot changes intentionally do not emit."""

from dataclasses import dataclass

from app.core.events import DomainEvent


@dataclass(frozen=True, slots=True)
class DonationApproved(DomainEvent):
    tg_id: int
