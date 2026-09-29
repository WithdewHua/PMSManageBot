"""Small synchronous, post-commit domain event dispatcher."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.db import register_post_commit
from app.core.log import logger


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Base class for immutable domain events."""


Handler = Callable[[DomainEvent], Any]
_HANDLERS: dict[type[DomainEvent], list[Handler]] = defaultdict(list)


def subscribe(event_type: type[DomainEvent], handler: Handler) -> None:
    """Register a handler from the application composition layer."""
    if not isinstance(event_type, type) or not issubclass(event_type, DomainEvent):
        raise TypeError("event_type must be a DomainEvent subclass")
    if not callable(handler):
        raise TypeError("event handler must be callable")
    if handler not in _HANDLERS[event_type]:
        _HANDLERS[event_type].append(handler)


def _dispatch(events: list[DomainEvent]) -> None:
    for event in events:
        for event_type, handlers in tuple(_HANDLERS.items()):
            if not isinstance(event, event_type):
                continue
            for handler in tuple(handlers):
                try:
                    result = handler(event)
                    if hasattr(result, "__await__"):
                        logger.warning(
                            "Async domain event handler ignored by synchronous dispatcher: %s",
                            handler,
                        )
                except Exception:
                    logger.exception(
                        "Domain event handler failed: event=%s handler=%s",
                        type(event).__name__,
                        handler,
                    )


def publish(session, event: DomainEvent) -> None:
    """Queue an event for synchronous dispatch after the caller commits."""
    events: list[DomainEvent] = session.info.setdefault("domain_events", [])
    events.append(event)
    if len(events) != 1:
        return

    def dispatch_events() -> None:
        pending = session.info.pop("domain_events", [])
        _dispatch(pending)

    register_post_commit(session, "domain-events", dispatch_events)


def clear_subscriptions() -> None:
    """Reset registrations for isolated tests and re-registration."""
    _HANDLERS.clear()


__all__ = ["DomainEvent", "clear_subscriptions", "publish", "subscribe"]
