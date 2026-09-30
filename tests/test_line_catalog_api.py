"""Regression tests for line management, tags, free premium lines, and user lines API."""

from __future__ import annotations

import pytest
from fastapi import BackgroundTasks
from starlette.requests import Request

from app.domains.identity.models import EmbyUser, Statistics
from app.domains.lines import admin_router as lines_admin
from app.domains.lines import catalog
from app.domains.lines import router as lines_user
from app.domains.lines.gateway_cache import (
    emby_last_user_defined_line_cache,
    emby_user_defined_line_cache,
)
from app.domains.lines.schemas import LineTagRequest
from app.domains.premium import admin_router as premium_admin
from app.transport.http.schemas import TelegramUser


def _request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/admin",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
            "client": ("test", 1),
        }
    )
    request.state.telegram_data = {"id": 123456789}
    return request


@pytest.fixture(autouse=True)
def clean_catalog(session_env):
    catalog.invalidate_cache()
    yield
    catalog.invalidate_cache()


@pytest.mark.asyncio
async def test_admin_lines_add_delete_and_list() -> None:
    req = _request()
    bg = BackgroundTasks()
    admin = TelegramUser(id=123456789, first_name="Admin")

    # Add normal lines
    res = await lines_admin.add_normal_line_generic.__wrapped__(
        request=req, background_tasks=bg, data={"line_name": "normal-1"}, user=admin
    )
    assert res.success is True

    # Add premium lines
    res = await premium_admin.add_premium_line_generic.__wrapped__(
        request=req, background_tasks=bg, data={"line_name": "prem-1"}, user=admin
    )
    assert res.success is True

    # Get lines config
    config = await lines_admin.get_lines_config.__wrapped__(request=req, user=admin)
    assert config["normal_lines"] == ["normal-1"]
    assert config["premium_lines"] == ["prem-1"]

    # Emby compatibility route
    compat_config = await lines_admin.get_emby_lines.__wrapped__(
        request=req, user=admin
    )
    assert compat_config["normal_lines"] == ["normal-1"]
    assert compat_config["premium_lines"] == ["prem-1"]

    # Delete lines
    del_res = await lines_admin.delete_normal_line_generic.__wrapped__(
        line_name="normal-1", request=req, user=admin
    )
    assert del_res.success is True

    del_prem = await premium_admin.delete_premium_line_generic.__wrapped__(
        line_name="prem-1", request=req, user=admin
    )
    assert del_prem.success is True

    config_after = await lines_admin.get_lines_config.__wrapped__(
        request=req, user=admin
    )
    assert config_after["normal_lines"] == []
    assert config_after["premium_lines"] == []


@pytest.mark.asyncio
async def test_d2_difference_illegal_characters_rejected() -> None:
    req = _request()
    bg = BackgroundTasks()
    admin = TelegramUser(id=123456789, first_name="Admin")

    res_slash = await lines_admin.add_normal_line_generic.__wrapped__(
        request=req, background_tasks=bg, data={"line_name": "bad/line"}, user=admin
    )
    assert res_slash.success is False

    res_comma = await lines_admin.add_normal_line_generic.__wrapped__(
        request=req, background_tasks=bg, data={"line_name": "bad,line"}, user=admin
    )
    assert res_comma.success is False


@pytest.mark.asyncio
async def test_d2_difference_set_tags_on_nonexistent_line_fails() -> None:
    req = _request()
    admin = TelegramUser(id=123456789, first_name="Admin")

    # In legacy it silently succeeded in KV, in D2 it returns success=False
    res = await lines_admin.set_line_tags.__wrapped__(
        request=req,
        data=LineTagRequest(line_name="non-existent", tags=["4K"]),
        user=admin,
    )
    assert res.success is False
    assert res.message == "设置标签失败"


@pytest.mark.asyncio
async def test_d2_difference_tag_order_and_all_line_tags_order() -> None:
    req = _request()
    bg = BackgroundTasks()
    admin = TelegramUser(id=123456789, first_name="Admin")

    await lines_admin.add_normal_line_generic.__wrapped__(
        request=req, background_tasks=bg, data={"line_name": "norm-1"}, user=admin
    )
    await premium_admin.add_premium_line_generic.__wrapped__(
        request=req, background_tasks=bg, data={"line_name": "prem-1"}, user=admin
    )

    # Submission order preserved: "B", "A" (legacy set() produced random order)
    await lines_admin.set_line_tags.__wrapped__(
        request=req,
        data=LineTagRequest(line_name="norm-1", tags=["B", " A ", "B", ""]),
        user=admin,
    )

    tag_res = await lines_admin.get_line_tags_admin.__wrapped__(
        line_name="norm-1", request=req, user=admin
    )
    assert tag_res.tags == ["B", "A"]

    all_tags = await lines_admin.get_all_line_tags.__wrapped__(request=req, user=admin)
    # Keys in catalog order: normal lines first, then premium lines
    assert list(all_tags.lines.keys()) == ["norm-1", "prem-1"]
    assert all_tags.lines["norm-1"] == ["B", "A"]
    assert all_tags.lines["prem-1"] == []


@pytest.mark.asyncio
async def test_d2_difference_free_premium_lines_order_and_validation() -> None:
    req = _request()
    bg = BackgroundTasks()
    admin = TelegramUser(id=123456789, first_name="Admin")

    await premium_admin.add_premium_line_generic.__wrapped__(
        request=req, background_tasks=bg, data={"line_name": "prem-z"}, user=admin
    )
    await premium_admin.add_premium_line_generic.__wrapped__(
        request=req, background_tasks=bg, data={"line_name": "prem-a"}, user=admin
    )

    # Valid free premium lines setting
    res = await premium_admin.set_free_premium_lines.__wrapped__(
        request=req,
        background_tasks=bg,
        data={"free_lines": ["prem-a", "prem-z"]},
        user=admin,
    )
    assert res.success is True

    # Output order follows catalog position (prem-z was added first)
    assert catalog.free_premium_lines() == ["prem-z", "prem-a"]

    # Reject non-premium line
    res_bad = await premium_admin.set_free_premium_lines.__wrapped__(
        request=req,
        background_tasks=bg,
        data={"free_lines": ["prem-z", "not-a-line"]},
        user=admin,
    )
    assert res_bad.success is False
    assert "不在高级线路列表中" in res_bad.message


@pytest.mark.asyncio
async def test_user_lines_endpoint_order(session_env) -> None:
    from app.core.db import get_session
    from app.domains.lines import service as lines_service

    # Create user in DB
    with get_session() as session:
        session.add(Statistics(tg_id=9999, credits=100))
        session.add(
            EmbyUser(
                emby_username="test_user",
                emby_id="emby-id-1",
                tg_id=9999,
                is_premium=0,
            )
        )

    req = _request()
    user = TelegramUser(id=9999, first_name="RegularUser")

    catalog.add_line("norm-1", premium=False)
    catalog.add_line("norm-2", premium=False)
    catalog.add_line("prem-1", premium=True)
    catalog.add_line("prem-2", premium=True)
    catalog.set_free_premium_lines(["prem-2"])

    # 1. Non-premium user without premium_free: only normal lines
    lines_service.set_premium_free(False)
    resp = await lines_user.get_emby_lines.__wrapped__(request=req, telegram_user=user)
    assert resp.success is True
    assert [line.name for line in resp.lines] == ["norm-1", "norm-2"]

    # 2. Non-premium user with premium_free: normal lines + free premium lines
    lines_service.set_premium_free(True)
    resp_free = await lines_user.get_emby_lines.__wrapped__(
        request=req, telegram_user=user
    )
    assert resp_free.success is True
    assert [line.name for line in resp_free.lines] == ["norm-1", "norm-2", "prem-2"]

    # 3. Premium user: all normal lines + all premium lines
    with get_session() as session:
        emby_u = session.query(EmbyUser).filter_by(tg_id=9999).first()
        emby_u.is_premium = 1

    resp_prem = await lines_user.get_emby_lines.__wrapped__(
        request=req, telegram_user=user
    )
    assert resp_prem.success is True
    assert [line.name for line in resp_prem.lines] == [
        "norm-1",
        "norm-2",
        "prem-1",
        "prem-2",
    ]


def test_gateway_cache_preserved(fake_gateway_redis, monkeypatch) -> None:
    monkeypatch.setattr(
        emby_user_defined_line_cache, "redis_client", fake_gateway_redis
    )
    monkeypatch.setattr(
        emby_last_user_defined_line_cache, "redis_client", fake_gateway_redis
    )

    from app.domains.lines import service as lines_service

    lines_service.put_cached_line("emby", "TestUser", "line-foo")
    assert fake_gateway_redis.get("emby_user_defined_line:testuser") == "line-foo"
    assert lines_service.get_cached_line("emby", "testuser") == "line-foo"

    lines_service.delete_cached_line("emby", "testuser")
    assert fake_gateway_redis.get("emby_user_defined_line:testuser") is None
