"""fix-live-defects D7（结算部分）：自建线路月度结算。

修复前：没有结算记录，重跑会重复发积分；排除线路所有者时区分大小写；
流量查询失败被吞成 0；删除线路只结算当月，1 日前删除丢失上月结算；
月份口径混用本地时区。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, select

from app.core.config import settings
from app.core.db import get_session
from app.domains.custom_lines import service as cl_service
from app.domains.custom_lines.models import CustomLine
from app.domains.identity.models import PlexUser, Statistics
from app.domains.traffic.models import LineTrafficMonthlyStats
from tests.conftest import next_id


def _assign_row_id(mapper, connection, target) -> None:  # pragma: no cover - hook
    if target.id is None:
        target.id = next_id()


for _model in (CustomLine, LineTrafficMonthlyStats):
    event.listen(_model, "before_insert", _assign_row_id)


GB = 1024**3


def _last_month() -> str:
    now = datetime.now(tz=settings.TZ)
    first = datetime(now.year, now.month, 1, tzinfo=settings.TZ)
    return (first - timedelta(days=1)).strftime("%Y-%m")


def _seed_line(domain: str, owner_tg: int) -> None:
    with get_session() as session:
        session.add(
            CustomLine(
                tg_id=owner_tg,
                domain=domain,
                network_info="info",
                price_monthly=10.0,
                traffic_limit=None,
                traffic_type="one_way",
                total_traffic=100,
                valid_days=30,
                is_permanent=0,
                status="approved",
                expires_at=int(datetime.now(tz=settings.TZ).timestamp()) + 86400,
                created_at=0,
                updated_at=0,
            )
        )


def _seed_monthly_traffic(line: str, month: str, username: str, gb: float) -> None:
    with get_session() as session:
        session.add(
            LineTrafficMonthlyStats(
                line=line,
                service="emby",
                username=username,
                year_month=month,
                total_bytes=int(gb * GB),
                created_at="2026-01-01T00:00:00+00:00",
            )
        )


def _seed_owner(tg_id: int, plex_username: str) -> None:
    with get_session() as session:
        session.add(Statistics(tg_id=tg_id, credits=0.0, donation=0.0))
        session.add(
            PlexUser(
                plex_id=tg_id * 10,
                tg_id=tg_id,
                plex_email=f"{tg_id}@example.com",
                plex_username=plex_username,
            )
        )


def _credits(tg_id: int) -> float:
    with get_session() as session:
        return float(session.get(Statistics, int(tg_id)).credits)


@pytest.fixture
def silent_notifications(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(cl_service, "send_message_by_url", _noop)
    monkeypatch.setattr(cl_service, "_send_admin_settlement_summary", _noop)


async def test_monthly_settlement_is_idempotent(
    session_env, monkeypatch, silent_notifications
):
    month = _last_month()
    _seed_owner(1, "owner")
    _seed_line("line.example.com", 1)
    _seed_monthly_traffic("line.example.com", month, "viewer", 10.0)

    await cl_service.settle_custom_line_traffic()
    first = _credits(1)
    assert first > 0

    await cl_service.settle_custom_line_traffic()
    assert _credits(1) == first  # 重跑不得再发


async def test_owner_traffic_excluded_case_insensitively(
    session_env, monkeypatch, silent_notifications
):
    month = _last_month()
    # 所有者用户名在库中是大写，流量表里也是大写
    _seed_owner(1, "Owner")
    _seed_line("line.example.com", 1)
    _seed_monthly_traffic("line.example.com", month, "Owner", 50.0)
    _seed_monthly_traffic("line.example.com", month, "viewer", 10.0)

    await cl_service.settle_custom_line_traffic()

    # 只有 viewer 的 10 GB 参与结算：10 GB * (10 元 / 100 GB) * 5 * 0.8 = 4.0
    assert _credits(1) == pytest.approx(4.0)


async def test_traffic_query_failure_propagates(session_env, monkeypatch):
    from app.domains.traffic import repository as traffic_repository

    class BrokenSession:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("injected query failure")

    with pytest.raises(RuntimeError):
        await traffic_repository._get_line_monthly_traffic(
            BrokenSession(), "line.example.com", "2026-09", from_raw_table=False
        )


def test_month_key_uses_configured_timezone():
    from app.domains.custom_lines import rules as cl_rules

    # 2026-09-30T16:30Z 在 UTC 下仍是 9 月，在东八区已是 10 月
    moment = datetime(2026, 9, 30, 16, 30, tzinfo=UTC)
    assert cl_rules.month_key(moment, tz=UTC) == "2026-09"
    assert cl_rules.month_key(moment, tz=ZoneInfo("Asia/Shanghai")) == "2026-10"


async def test_delete_settles_previous_month(session_env, monkeypatch):
    from fastapi import BackgroundTasks
    from starlette.requests import Request

    from app.domains.custom_lines import router as cl_router
    from app.domains.lines import service as lines_service

    async def _fake_unbind(domain, reason):
        return True, 0

    async def _fake_disable(domain, reason):
        return None

    monkeypatch.setattr(
        lines_service, "unbind_specified_line_for_all_users", _fake_unbind
    )
    monkeypatch.setattr(
        lines_service, "disable_line_schedules_and_notify", _fake_disable
    )
    monkeypatch.setattr(
        "app.domains.custom_lines.router.send_message_by_url", _async_noop
    )
    monkeypatch.setattr(
        "app.domains.custom_lines.service.send_message_by_url", _async_noop
    )
    monkeypatch.setattr(
        "app.domains.custom_lines.service._send_admin_settlement_summary", _async_noop
    )

    # 时间冻结在 10 月 1 日：上月（9 月）还没结算就被删除
    real_datetime = datetime

    class FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 1, 12, 0, tzinfo=tz or UTC)

    monkeypatch.setattr(cl_service, "datetime", FrozenDatetime)

    month = "2026-09"
    _seed_owner(1, "owner")
    _seed_line("gone.example.com", 1)
    with get_session() as session:
        row = session.execute(
            select(CustomLine).where(CustomLine.domain == "gone.example.com")
        ).scalar_one()
        row.status = "offline"
    _seed_monthly_traffic("gone.example.com", month, "viewer", 10.0)

    with get_session() as session:
        line_id = session.execute(
            select(CustomLine.id).where(CustomLine.domain == "gone.example.com")
        ).scalar_one()

    request = Request(
        {"type": "http", "method": "DELETE", "path": "/api", "headers": []}
    )
    request.state.telegram_data = {}
    response = await cl_router.delete_custom_line.__wrapped__(
        request, line_id, BackgroundTasks(), user=TelegramUserStub(1)
    )
    assert response.success is True, response.message

    # 上个月的结算没有丢失
    assert _credits(1) == pytest.approx(4.0)


async def _async_noop(*args, **kwargs):
    return None


class TelegramUserStub:
    def __init__(self, tg_id: int):
        self.id = tg_id
        self.first_name = "u"
        self.username = "u"
