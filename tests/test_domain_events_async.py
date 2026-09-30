import asyncio
import gc
from dataclasses import dataclass

import pytest

from app.core import events
from app.core.db import get_session


@dataclass(frozen=True, slots=True)
class AsyncExample(events.DomainEvent):
    value: str


@pytest.fixture
def clean_events():
    events.clear_subscriptions()
    events.bind_main_loop(None)
    yield
    events.clear_subscriptions()
    events.bind_main_loop(None)
    from app.subscriptions import register_all

    register_all()


@pytest.mark.asyncio
async def test_current_loop_retains_tasks_and_isolates_errors(clean_events):
    received = []
    gate = asyncio.Event()

    async def broken(event):
        raise RuntimeError("injected")

    async def record(event):
        await gate.wait()
        received.append(event.value)

    events.subscribe_async(AsyncExample, broken)
    events.subscribe_async(AsyncExample, record)
    events.emit(AsyncExample("one"))
    gc.collect()
    assert received == []
    assert events._PENDING
    gate.set()
    await events.drain()
    assert received == ["one"]
    assert not events._PENDING


@pytest.mark.asyncio
async def test_worker_thread_dispatches_on_bound_main_loop(clean_events):
    loop = asyncio.get_running_loop()
    received = []

    async def record(event):
        received.append((event.value, asyncio.get_running_loop()))

    events.bind_main_loop(loop)
    events.subscribe_async(AsyncExample, record)
    await asyncio.to_thread(events.emit, AsyncExample("thread"))
    await events.drain()
    assert received == [("thread", loop)]


def test_cli_without_loop_executes_async_handler(clean_events):
    received = []

    async def record(event):
        await asyncio.sleep(0)
        received.append(event.value)

    events.subscribe_async(AsyncExample, record)
    events.emit(AsyncExample("cli"))
    assert received == ["cli"]


@pytest.mark.asyncio
async def test_async_publish_waits_for_commit_and_rollback_discards(
    session_env, clean_events
):
    received = []

    async def record(event):
        received.append(event.value)

    events.subscribe_async(AsyncExample, record)
    with get_session() as session:
        events.publish(session, AsyncExample("committed"))
        assert received == []
    await events.drain()
    assert received == ["committed"]
    with pytest.raises(RuntimeError), get_session() as session:
        events.publish(session, AsyncExample("rollback"))
        raise RuntimeError("rollback")
    await events.drain()
    assert received == ["committed"]


@pytest.mark.asyncio
async def test_current_request_loop_wins_over_bound_loop(clean_events):
    from threading import Event, Thread

    bound_loop = asyncio.new_event_loop()
    started = Event()

    def run_bound_loop():
        asyncio.set_event_loop(bound_loop)
        bound_loop.call_soon(started.set)
        bound_loop.run_forever()

    thread = Thread(target=run_bound_loop)
    thread.start()
    assert started.wait(timeout=5)
    seen = []

    async def record(event):
        seen.append(asyncio.get_running_loop())

    try:
        events.bind_main_loop(bound_loop)
        events.subscribe_async(AsyncExample, record)
        events.emit(AsyncExample("request"))
        await events.drain()
        assert seen == [asyncio.get_running_loop()]
    finally:
        bound_loop.call_soon_threadsafe(bound_loop.stop)
        thread.join(timeout=5)
        assert not thread.is_alive()
        bound_loop.close()
        events.bind_main_loop(None)


@pytest.mark.asyncio
async def test_drain_includes_events_emitted_by_handlers(clean_events):
    seen = []

    async def record(event):
        seen.append(event.value)
        if event.value == "parent":
            events.emit(AsyncExample("child"))

    events.subscribe_async(AsyncExample, record)
    events.emit(AsyncExample("parent"))
    await events.drain()
    assert seen == ["parent", "child"]
    assert not events._PENDING
