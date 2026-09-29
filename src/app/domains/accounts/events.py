"""Events emitted by account synchronization."""

from dataclasses import dataclass

from app.core.events import DomainEvent


@dataclass(frozen=True, slots=True)
class PlexUserIdResolved(DomainEvent):
    email: str
    plex_id: int


__all__ = ["PlexUserIdResolved"]
