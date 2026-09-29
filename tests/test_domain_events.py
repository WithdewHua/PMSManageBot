from dataclasses import dataclass

import pytest

from app.core.db import get_session
from app.core.events import DomainEvent, clear_subscriptions, publish, subscribe
from app.subscriptions import register_all


@dataclass(frozen=True, slots=True)
class ExampleEvent(DomainEvent):
    value: str


def _isolated_handlers():
    clear_subscriptions()


@pytest.fixture
def isolated_events():
    clear_subscriptions()
    try:
        yield
    finally:
        register_all()


def test_events_dispatch_after_commit_in_publish_order(session_env, isolated_events):
    received: list[str] = []
    subscribe(ExampleEvent, lambda event: received.append(event.value))

    with get_session() as session:
        publish(session, ExampleEvent("first"))
        publish(session, ExampleEvent("second"))
        assert received == []

    assert received == ["first", "second"]


def test_events_are_discarded_on_rollback(session_env, isolated_events):
    received: list[str] = []
    subscribe(ExampleEvent, lambda event: received.append(event.value))

    with pytest.raises(RuntimeError), get_session() as session:
        publish(session, ExampleEvent("rolled-back"))
        raise RuntimeError("rollback")

    assert received == []


def test_event_handler_failure_isolated(session_env, isolated_events):
    received: list[str] = []

    def broken(_event: ExampleEvent) -> None:
        raise RuntimeError("injected handler failure")

    subscribe(ExampleEvent, broken)
    subscribe(ExampleEvent, lambda event: received.append(event.value))

    with get_session() as session:
        publish(session, ExampleEvent("committed"))

    assert received == ["committed"]
