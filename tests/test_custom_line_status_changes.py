"""fix-live-defects D7（状态变更部分）：上线、续期、提交申请。

修复前：上线和续期在提交后导入不存在的 ``config``，提交申请读取不存在
的 ``settings.TG_ADMIN_IDS``——数据已提交、接口报失败，并跳过通知；错
误响应回显异常原文。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import event, select
from starlette.requests import Request

from app.core.db import get_session
from app.domains.custom_lines import router as cl_router
from app.domains.custom_lines.models import CustomLine
from app.domains.profile.schemas import (
    CustomLineOnlineRequest,
    CustomLineRenewRequest,
    CustomLineSubmitRequest,
)
from tests.conftest import next_id

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"


def _assign_row_id(mapper, connection, target) -> None:  # pragma: no cover - hook
    if target.id is None:
        target.id = next_id()


event.listen(CustomLine, "before_insert", _assign_row_id)


class TelegramUserStub:
    def __init__(self, tg_id: int):
        self.id = tg_id
        self.first_name = "u"
        self.username = "u"


def _request(method: str = "POST") -> Request:
    request = Request({"type": "http", "method": method, "path": "/api", "headers": []})
    request.state.telegram_data = {}
    return request


def _seed_line(domain: str, status: str, owner: int = 1) -> int:
    with get_session() as session:
        session.add(
            CustomLine(
                tg_id=owner,
                domain=domain,
                network_info="info",
                price_monthly=10.0,
                traffic_type="one_way",
                total_traffic=100,
                valid_days=30,
                is_permanent=0,
                status=status,
                expires_at=4_102_244_800,
                created_at=0,
                updated_at=0,
            )
        )
        session.flush()
        return session.execute(
            select(CustomLine.id).where(CustomLine.domain == domain)
        ).scalar_one()


def _line_status(line_id: int) -> str:
    with get_session() as session:
        return session.get(CustomLine, int(line_id)).status


@pytest.fixture
def capture_notifications(monkeypatch):
    sent: list[tuple] = []

    async def _fake_send(*args, **kwargs):
        sent.append((args, kwargs))

    monkeypatch.setattr(cl_router, "send_message_by_url", _fake_send)
    return sent


async def test_online_custom_line_succeeds(session_env, capture_notifications):

    # get_user_name_from_tg_id 在测试里会走网络；固定为替身
    capture_get_name = lambda tg_id: f"user{tg_id}"
    import app.domains.custom_lines.router as router_module

    orig = router_module.get_user_name_from_tg_id
    router_module.get_user_name_from_tg_id = capture_get_name
    try:
        line_id = _seed_line("online.example.com", "offline")

        response = await cl_router.online_custom_line.__wrapped__(
            _request(),
            line_id,
            CustomLineOnlineRequest(),
            BackgroundTasks(),
            user=TelegramUserStub(1),
        )
    finally:
        router_module.get_user_name_from_tg_id = orig

    assert response.success is True, response.message
    assert "失败" not in response.message
    assert _line_status(line_id) == "approved"


async def test_renew_custom_line_succeeds(session_env, capture_notifications):
    line_id = _seed_line("renew.example.com", "approved")

    response = await cl_router.renew_custom_line.__wrapped__(
        _request(),
        line_id,
        CustomLineRenewRequest(valid_days=30),
        user=TelegramUserStub(1),
    )

    assert response.success is True, response.message
    assert "续期成功" in response.message


async def test_submit_custom_line_succeeds(session_env, capture_notifications):
    import app.domains.custom_lines.router as router_module

    orig = router_module.get_user_name_from_tg_id
    router_module.get_user_name_from_tg_id = lambda tg_id: f"user{tg_id}"
    try:
        response = await cl_router.submit_custom_line.__wrapped__(
            _request(),
            BackgroundTasks(),
            CustomLineSubmitRequest(
                domain="fresh.example.com",
                network_info="info",
                price_monthly=10.0,
                traffic_type="one_way",
                total_traffic=100,
                valid_days=30,
                is_permanent=False,
            ),
            user=TelegramUserStub(1),
        )
    finally:
        router_module.get_user_name_from_tg_id = orig

    assert response.success is True, response.message
    with get_session() as session:
        assert (
            session.execute(
                select(CustomLine).where(CustomLine.domain == "fresh.example.com")
            ).scalar_one()
            is not None
        )


def test_all_app_imports_resolve():
    """src 中所有 ``from app.… import X``（含函数内延迟导入）必须可解析。"""
    import importlib

    unresolved = []
    for path in sorted(SRC_ROOT.glob("app/**/*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("app"):
                continue
            try:
                module = importlib.import_module(node.module)
            except Exception:
                unresolved.append(f"{path}:{node.lineno} module {node.module}")
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                if hasattr(module, alias.name):
                    continue
                # from package import submodule 也是合法导入
                try:
                    importlib.import_module(f"{node.module}.{alias.name}")
                    continue
                except ImportError:
                    pass
                unresolved.append(f"{path}:{node.lineno} {node.module}.{alias.name}")
    assert unresolved == []
