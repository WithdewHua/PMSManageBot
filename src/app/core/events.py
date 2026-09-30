"""Post-commit domain events with isolated synchronous and async handlers."""

from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from dataclasses import dataclass
from threading import Lock
from typing import Any

from app.core.db import register_post_commit
from app.core.log import logger


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Base class for immutable domain events."""


Handler = Callable[[DomainEvent], Any]
_HANDLERS: dict[type[DomainEvent], list[Handler]] = defaultdict(list)
_ASYNC_HANDLERS: dict[
    type[DomainEvent], list[Callable[[DomainEvent], Awaitable[None]]]
] = defaultdict(list)
_MAIN_LOOP: asyncio.AbstractEventLoop | None = None
_PENDING: set[asyncio.Task | Future] = set()
_PENDING_LOCK = Lock()


def bind_main_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Bind the application's PTB loop; None resets the binding for tests."""
    global _MAIN_LOOP
    _MAIN_LOOP = loop


def subscribe_async(
    event_type: type[DomainEvent], handler: Callable[[DomainEvent], Awaitable[None]]
) -> None:
    """Register an async handler from application composition."""
    if not isinstance(event_type, type) or not issubclass(event_type, DomainEvent):
        raise TypeError("event_type must be a DomainEvent subclass")
    if not callable(handler):
        raise TypeError("event handler must be callable")
    if handler not in _ASYNC_HANDLERS[event_type]:
        _ASYNC_HANDLERS[event_type].append(handler)


async def _invoke_async(handler, event: DomainEvent) -> None:
    try:
        await handler(event)
    except Exception:
        logger.exception(
            "Async domain event handler failed: event=%s handler=%s",
            type(event).__name__,
            handler,
        )


def _retain(pending: asyncio.Task | Future) -> None:
    with _PENDING_LOCK:
        _PENDING.add(pending)

    def completed(_future) -> None:
        with _PENDING_LOCK:
            _PENDING.discard(pending)

    pending.add_done_callback(completed)


def _schedule_async(handler, event: DomainEvent) -> None:
    coroutine = _invoke_async(handler, event)
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            _retain(loop.create_task(coroutine))
        elif (
            _MAIN_LOOP is not None
            and _MAIN_LOOP.is_running()
            and not _MAIN_LOOP.is_closed()
        ):
            _retain(asyncio.run_coroutine_threadsafe(coroutine, _MAIN_LOOP))
        else:
            asyncio.run(coroutine)
    except Exception:
        coroutine.close()
        logger.exception("Failed scheduling domain event: %s", type(event).__name__)


async def drain() -> None:
    """Wait for retained dispatch work, including work on another event loop."""
    loop = asyncio.get_running_loop()
    while True:
        with _PENDING_LOCK:
            pending = tuple(_PENDING)
        if not pending:
            return
        waiters = []
        for future in pending:
            if isinstance(future, Future):
                waiters.append(asyncio.wrap_future(future))
            elif future.get_loop() is loop:
                if future is not asyncio.current_task():
                    waiters.append(asyncio.shield(future))
            elif not future.done():

                async def wait_foreign(task=future):
                    await asyncio.shield(task)

                waiter = asyncio.run_coroutine_threadsafe(
                    wait_foreign(), future.get_loop()
                )
                waiters.append(asyncio.wrap_future(waiter))
        if waiters:
            await asyncio.gather(*waiters, return_exceptions=True)
        else:
            await asyncio.sleep(0)


def emit(event: DomainEvent) -> None:
    """Dispatch immediately when the owning transaction has already committed."""
    _dispatch([event])


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
                    if inspect.iscoroutine(result):
                        result.close()
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
        for event_type, handlers in tuple(_ASYNC_HANDLERS.items()):
            if isinstance(event, event_type):
                for handler in tuple(handlers):
                    _schedule_async(handler, event)


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
    _ASYNC_HANDLERS.clear()


__all__ = [
    "DomainEvent",
    "bind_main_loop",
    "clear_subscriptions",
    "drain",
    "emit",
    "publish",
    "subscribe",
    "subscribe_async",
]
