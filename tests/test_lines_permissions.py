"""Line visibility and binding must share the migrated catalog's free-open flags."""

from collections.abc import Iterator

import pytest
from fakeredis import FakeRedis
from starlette.requests import Request

from app.core import kv as core_kv
from app.core.db import get_session
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
from app.domains.lines import catalog, gateway_cache, repository, router, service
from app.domains.lines.schemas import EmbyLineRequest, PlexLineRequest
from app.transport.http.schemas import TelegramUser

NORMAL_LINE = "normal.example.com"
FREE_LINE = "free.example.com"
PAID_LINE = "paid.example.com"


@pytest.fixture(autouse=True)
def permission_catalog(session_env: object) -> Iterator[None]:
    catalog.invalidate_cache()
    catalog.add_line(NORMAL_LINE, premium=False)
    catalog.add_line(FREE_LINE, premium=True)
    catalog.add_line(PAID_LINE, premium=True)
    assert catalog.set_free_premium_lines([FREE_LINE])
    yield
    catalog.invalidate_cache()


@pytest.fixture(
    autouse=True, params=[False, True], ids=["empty-legacy", "stale-legacy"]
)
def legacy_free_config(request: pytest.FixtureRequest) -> None:
    # Migrated installations have no legacy rows. A leftover row must not grant
    # access to a line that the current catalog no longer marks as free.
    if request.param:
        core_kv.upsert("free_premium_line", PAID_LINE, "1")


@pytest.mark.parametrize(
    ("is_premium", "premium_free", "line", "expected"),
    [
        (False, True, NORMAL_LINE, (True, "")),
        (False, True, FREE_LINE, (True, "")),
        (False, True, PAID_LINE, (False, "该高级线路暂未开放免费使用")),
        (False, False, FREE_LINE, (False, "您不是 premium 用户，无法使用该线路")),
        (False, False, NORMAL_LINE, (True, "")),
        (True, False, FREE_LINE, (True, "")),
        (True, False, PAID_LINE, (True, "")),
        (True, True, PAID_LINE, (True, "")),
    ],
)
def test_line_permission_uses_current_catalog(
    is_premium: bool, premium_free: bool, line: str, expected: tuple[bool, str]
) -> None:
    service.set_premium_free(premium_free)

    assert service.check_line_permission(is_premium, line) == expected


def test_line_permission_follows_catalog_changes() -> None:
    service.set_premium_free(True)
    assert service.check_line_permission(False, FREE_LINE) == (True, "")

    assert catalog.set_free_premium_lines([PAID_LINE])

    assert service.check_line_permission(False, FREE_LINE) == (
        False,
        "该高级线路暂未开放免费使用",
    )
    assert service.check_line_permission(False, PAID_LINE) == (True, "")


@pytest.mark.parametrize("media_service", ["emby", "plex"])
async def test_non_premium_can_bind_listed_free_line(
    media_service: str, fake_gateway_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    tg_id = 9999
    username = "regular_user"
    with get_session() as session:
        session.add(Statistics(tg_id=tg_id, credits=100))
        if media_service == "emby":
            session.add(
                EmbyUser(
                    emby_username=username,
                    emby_id="emby-id-1",
                    tg_id=tg_id,
                    is_premium=0,
                )
            )
        else:
            session.add(
                PlexUser(
                    plex_username=username,
                    plex_id=101,
                    tg_id=tg_id,
                    is_premium=0,
                )
            )

    for cache in (
        gateway_cache.emby_user_defined_line_cache,
        gateway_cache.emby_last_user_defined_line_cache,
        gateway_cache.plex_user_defined_line_cache,
        gateway_cache.plex_last_user_defined_line_cache,
    ):
        monkeypatch.setattr(cache, "redis_client", fake_gateway_redis)
    monkeypatch.setattr(router, "get_user_name_from_tg_id", lambda _: username)

    service.set_premium_free(True)
    request = Request({"type": "http"})
    user = TelegramUser(id=tg_id, first_name="RegularUser")
    list_lines = getattr(router, f"get_{media_service}_lines").__wrapped__
    bind_line = getattr(router, f"bind_{media_service}_line").__wrapped__
    request_model = EmbyLineRequest if media_service == "emby" else PlexLineRequest
    get_bound_line = getattr(repository, f"get_{media_service}_line")

    available = await list_lines(request=request, telegram_user=user)
    assert available.success is True
    assert [line.name for line in available.lines] == [NORMAL_LINE, FREE_LINE]

    bound = await bind_line(
        request=request, data=request_model(line=FREE_LINE), telegram_user=user
    )
    assert bound.success is True, bound.message
    assert get_bound_line(tg_id) == FREE_LINE
    assert service.get_cached_line(media_service, username) == FREE_LINE

    denied = await bind_line(
        request=request, data=request_model(line=PAID_LINE), telegram_user=user
    )
    assert denied.success is False
    assert denied.message == "该高级线路暂未开放免费使用"
    assert get_bound_line(tg_id) == FREE_LINE
    assert service.get_cached_line(media_service, username) == FREE_LINE
