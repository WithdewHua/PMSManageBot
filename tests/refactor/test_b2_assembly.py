"""B2 API and Bot assembly equivalence checks."""

from app.api.app import app as current_app
from app.bot.app import HANDLERS
from app.handlers import rank, start, status, user
from app.webapp import app as legacy_app


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


def _legacy_handlers():
    return [
        handler
        for module in (rank, start, status, user)
        for name, handler in vars(module).items()
        if name.endswith("_handler")
    ]


def test_api_route_and_openapi_surfaces_are_unchanged():
    assert _route_surface(current_app) == _route_surface(legacy_app)
    assert current_app.openapi() == legacy_app.openapi()
    assert [type(item).__name__ for item in current_app.user_middleware] == [
        type(item).__name__ for item in legacy_app.user_middleware
    ]


def test_bot_handler_registration_surface_is_unchanged():
    def signature(handler):
        return (
            tuple(sorted(handler.commands)),
            handler.callback.__name__,
            type(handler).__name__,
        )

    assert [signature(handler) for handler in HANDLERS] == [
        signature(handler) for handler in _legacy_handlers()
    ]


def test_migrated_empty_pydantic_list_defaults_are_equivalent():
    from app.domains.profile import schemas as current
    from app.webapp.schemas import user as legacy

    for name, field in (
        ("CustomLineListResponse", "lines"),
        ("LineScheduleListResponse", "schedules"),
    ):
        old = getattr(legacy, name)
        new = getattr(current, name)
        original = old(success=True)
        relocated = new(success=True)
        assert getattr(original, field) == getattr(relocated, field) == []
        assert original.model_dump() == relocated.model_dump()
        assert old.model_json_schema() == new.model_json_schema()


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


def test_blackjack_timeout_keeps_b1_persisted_job_reference(monkeypatch):
    from app.core import scheduler as scheduler_module
    from app.domains.blackjack.jobs import cash as cash_jobs

    recorded = []

    class Recorder:
        def add_async_job(self, **kwargs):
            recorded.append(kwargs)

    monkeypatch.setattr(scheduler_module, "Scheduler", Recorder)
    cash_jobs._schedule_blackjack_timeout(hand_id=17, timeout_minutes=0.5)
    assert len(recorded) == 1
    assert recorded[0]["func"] == (
        "app.webapp.routers.activities.blackjack:_settle_blackjack_hand_on_timeout"
    )
    from apscheduler.util import ref_to_obj

    assert ref_to_obj(recorded[0]["func"]).__module__ == (
        "app.webapp.routers.activities.blackjack"
    )
    assert recorded[0]["jobstore"] == "sqlalchemy"
    assert recorded[0]["kwargs"] == {"hand_id": 17}
    assert recorded[0]["id"] == "blackjack_timeout_17"


def test_treasure_auto_reopen_keeps_b1_persisted_job_reference(monkeypatch):
    from apscheduler.util import ref_to_obj

    from app.core import scheduler as scheduler_module
    from app.domains.treasure import jobs as treasure_jobs

    recorded = []

    class Recorder:
        def add_async_job(self, **kwargs):
            recorded.append(kwargs)

    monkeypatch.setattr(scheduler_module, "Scheduler", Recorder)
    treasure_jobs.schedule_auto_reopen_treasure_issue(source_issue_id=23)
    assert len(recorded) == 1
    assert recorded[0]["func"] == (
        "app.webapp.routers.activities.treasure:_auto_create_next_treasure_issue_from"
    )
    assert ref_to_obj(recorded[0]["func"]).__module__ == (
        "app.webapp.routers.activities.treasure"
    )
    assert recorded[0]["jobstore"] == "sqlalchemy"
    assert recorded[0]["kwargs"] == {"source_issue_id": 23}
    assert recorded[0]["id"] == "treasure_auto_reopen_23"
