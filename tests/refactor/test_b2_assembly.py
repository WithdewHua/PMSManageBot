"""B2 API and Bot assembly equivalence checks."""

from app.api.app import app as current_app
from app.bot.app import HANDLERS


def _route_surface(application):
    return [
        (
            route.path,
            tuple(sorted(route.methods or ())),
            route.name,
            getattr(route.endpoint, "__name__", None),
            getattr(getattr(route, "response_model", None), "__name__", None),
        )
        for route in application.routes
    ]


EXPECTED_HANDLER_CALLBACKS = [
    "credits_rank",
    "donation_rank",
    "watched_time_rank",
    "device_rank",
    "rank_24h",
    "start",
    "get_register_status",
    "set_register",
    "get_server_status",
    "info",
    "set_donation",
    "exchange",
    "create_overseerr",
]


def test_api_route_and_openapi_surfaces_are_assembled():
    assert len(_route_surface(current_app)) == 212
    assert current_app.openapi()["paths"]
    assert [type(item).__name__ for item in current_app.user_middleware] == [
        "Middleware",
        "Middleware",
        "Middleware",
    ]


def test_bot_handler_registration_surface_is_unchanged():
    def signature(handler):
        return (
            tuple(sorted(handler.commands)),
            handler.callback.__name__,
            type(handler).__name__,
        )

    assert [signature(handler)[1] for handler in HANDLERS] == EXPECTED_HANDLER_CALLBACKS


def test_migrated_empty_pydantic_list_defaults_are_equivalent():
    from app.domains.profile import schemas as current

    for name, field in (
        ("CustomLineListResponse", "lines"),
        ("LineScheduleListResponse", "schedules"),
    ):
        model = getattr(current, name)
        response = model(success=True)
        assert getattr(response, field) == []
        assert model.model_json_schema()


async def test_custom_line_approval_reaches_validation_after_schema_move():
    """An invalid action must be rejected by validation, not an ImportError."""
    from fastapi import BackgroundTasks
    from starlette.requests import Request

    from app.core.schemas import TelegramUser
    from app.domains.custom_lines.admin_router import approve_custom_line

    request = Request({"type": "http", "headers": []})
    request.state.telegram_data = {"hash": "mock_hash_for_development"}
    response = await approve_custom_line(
        request=request,
        line_id=1,
        background_tasks=BackgroundTasks(),
        data={"action": "invalid"},
        user=TelegramUser(id=123456789, first_name="Admin"),
    )
    assert response.success is False
    assert response.message == "无效的操作"


def test_blackjack_timeout_uses_stable_named_persisted_job(monkeypatch):
    from app.core import scheduler as scheduler_module
    from app.domains.blackjack.jobs import cash as cash_jobs

    recorded = []

    class Recorder:
        def add_async_job(self, **kwargs):
            recorded.append(kwargs)

    monkeypatch.setattr(scheduler_module, "Scheduler", Recorder)
    monkeypatch.setattr(
        scheduler_module,
        "TASK_REGISTRY",
        {"blackjack.hand_timeout": lambda **kwargs: None},
    )
    cash_jobs._schedule_blackjack_timeout(hand_id=17, timeout_minutes=0.5)
    assert len(recorded) == 1
    from app.core.scheduler import run_task

    assert recorded[0]["func"] is run_task
    assert recorded[0]["args"] == ("blackjack.hand_timeout",)
    assert recorded[0]["jobstore"] == "sqlalchemy"
    assert recorded[0]["kwargs"] == {"hand_id": 17}
    assert recorded[0]["id"] == "blackjack_timeout_17"


def test_treasure_auto_reopen_uses_stable_named_persisted_job(monkeypatch):
    from app.core import scheduler as scheduler_module
    from app.domains.treasure import jobs as treasure_jobs

    recorded = []

    class Recorder:
        def add_async_job(self, **kwargs):
            recorded.append(kwargs)

    monkeypatch.setattr(scheduler_module, "Scheduler", Recorder)
    monkeypatch.setattr(
        scheduler_module,
        "TASK_REGISTRY",
        {"treasure.open_next_issue": lambda **kwargs: None},
    )
    treasure_jobs.schedule_auto_reopen_treasure_issue(source_issue_id=23)
    assert len(recorded) == 1
    from app.core.scheduler import run_task

    assert recorded[0]["func"] is run_task
    assert recorded[0]["args"] == ("treasure.open_next_issue",)
    assert recorded[0]["jobstore"] == "sqlalchemy"
    assert recorded[0]["kwargs"] == {"source_issue_id": 23}
    assert recorded[0]["id"] == "treasure_auto_reopen_23"
