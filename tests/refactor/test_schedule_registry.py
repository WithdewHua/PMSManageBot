"""The declarative schedule preserves the legacy 32-job surface and order."""

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app import schedule
from app.core import scheduler as scheduler_module


class RecordingScheduler:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, str, str, dict]] = []
        self.named_enabled = False

    def add_async_job(self, *, func, trigger, id, **kwargs):
        self.jobs.append(("async", func.__name__, id, {"trigger": trigger, **kwargs}))

    def add_sync_job(self, *, func, trigger, id, **kwargs):
        self.jobs.append(("sync", func.__name__, id, {"trigger": trigger, **kwargs}))

    def enable_named_persistent_tasks(self) -> None:
        self.named_enabled = True


@pytest.fixture
def isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler_module, "TASK_REGISTRY", {})
    monkeypatch.setattr(schedule, "ON_STARTUP", [lambda: None, lambda: None])


def test_register_all_has_32_jobs_and_two_startup_hooks(isolated_registry) -> None:
    recorder = RecordingScheduler()
    schedule.register_all(recorder)  # type: ignore[arg-type]
    assert len(recorder.jobs) == 32
    assert [job[2] for job in recorder.jobs] == [
        job.id for job in schedule._jobs(datetime.now(UTC))
    ]
    assert recorder.jobs[0][2] == "update_credits"
    assert recorder.jobs[-1][2] == "check_and_award_game_king_badge"
    assert recorder.named_enabled
    assert set(scheduler_module.TASK_REGISTRY) == {
        "blackjack.hand_timeout",
        "treasure.open_next_issue",
    }
    assert schedule.TASKS["treasure.open_next_issue"] is not None


def test_named_tasks_register_before_api_thread_is_started(isolated_registry) -> None:
    from app import main

    main_path = Path(main.__file__)
    tree = ast.parse(main_path.read_text(encoding="utf-8"))
    boot = next(
        node
        for node in tree.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
    )
    names = [
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for stmt in boot.body
        for node in ast.walk(stmt)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    ]
    assert names.index("register_tasks") < names.index("start")
    assert names.index("register_tasks") < names.index("start_bot")

    schedule.register_tasks()
    assert set(scheduler_module.TASK_REGISTRY) == {
        "blackjack.hand_timeout",
        "treasure.open_next_issue",
    }


@pytest.mark.asyncio
async def test_main_starts_scheduler_only_after_registration_and_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    events: list[str] = []

    class FakeScheduler:
        def start(self) -> None:
            events.append("start")

    async def no_commands(_application) -> None:
        return None

    monkeypatch.setattr(main, "Scheduler", FakeScheduler)
    monkeypatch.setattr(main, "set_bot_commands", no_commands)
    monkeypatch.setattr(
        schedule, "register_all", lambda scheduler: events.append("register")
    )
    monkeypatch.setattr(
        schedule,
        "migrate_persisted_jobs",
        lambda scheduler: events.append("migrate") or 0,
    )
    await main.post_init_services(object())
    assert events == ["register", "migrate", "start"]


def test_schedule_options_keep_legacy_executor_and_offsets() -> None:
    jobs = {job.id: job for job in schedule._jobs(datetime(2026, 1, 1, tzinfo=UTC))}
    assert jobs["update_users_credits"].runner == "sync"
    assert jobs["write_user_info_cache"].trigger_args["next_run_time"] == datetime(
        2026, 1, 1, 0, 0, 30, tzinfo=UTC
    )
    assert jobs["check_prediction_markets_closing_soon_job"].trigger_args[
        "next_run_time"
    ] == datetime(2026, 1, 1, 0, 2, tzinfo=UTC)
    assert jobs["check_expired_crypto_donation_orders"].trigger_args[
        "next_run_time"
    ] == datetime(2026, 1, 1, 0, 0, 45, tzinfo=UTC)
