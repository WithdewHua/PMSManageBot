"""礼包 HTTP 契约：领取各类结果与管理端 8 个接口的响应冻结。

在同一个数据库状态上逐例调用 router 协程，把状态码与响应体写成 JSON。
重新生成快照：

    UPDATE_GIFT_PACK_CONTRACT=1 .venv/bin/python -m pytest \
      tests/refactor/test_gift_pack_http_contract.py

外部副作用（媒体服务器同步、管理员通知、调度提交）在本用例内全部替换为
no-op：契约只描述 HTTP 层可见的行为。行 id 从固定基数开始分配，使快照与
用例执行顺序无关。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import event
from starlette.requests import Request

from app.core.db import get_session
from app.core.kv import SystemConfig
from app.core.schemas import TelegramUser
from app.domains.gift_pack import notifications as gift_pack_notifications
from app.domains.gift_pack import repository as gift_pack_repository
from app.domains.gift_pack import router as gift_pack_router
from app.domains.gift_pack.models import GiftPack, GiftPackUserState
from app.domains.gift_pack.schemas import (
    GiftPackCreateRequest,
    GiftPackSetEnabledRequest,
    GiftPackUpdateRequest,
)
from app.domains.identity.models import PlexUser
from app.domains.luckywheel.models import WheelStats
from tests import conftest
from tests.conftest import add_user, next_id

FIXTURE = Path(__file__).parent / "fixtures/gift_pack_http_contract.json"

PAST = 1_700_000_000
FUTURE = 4_100_000_000
MISSING_PACK = 999_999
ID_BASE = 800_000
ALL_REWARDS = [
    {"type": "credits", "amount": 10},
    {"type": "premium_days", "days": 7},
    {"type": "wheel_free_spins", "count": 2, "expiry_days": 5},
    {"type": "tournament_wallet", "amount": 20},
    {"type": "invite_codes", "count": 1},
]

_HEX32 = re.compile(r"[0-9a-f]{32}")
_ISO_TS = re.compile(r"\d{4}-\d{2}-\d{2}T[0-9:.+]+")
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+")


def _normalize(value: Any) -> Any:
    """抹掉与执行时间相关的值：毫秒/秒时间戳、随机邀请码、到期时间。"""
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return "<ts>" if value >= 10**9 else value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        if _HEX32.fullmatch(value):
            return "<code>"
        if _ISO_TS.fullmatch(value):
            return "<datetime>"
        if _EMAIL.fullmatch(value):
            return "<email>"
        return value
    return value


def _request(method: str = "POST", path: str = "/api/gift-packs") -> Request:
    request = Request({"type": "http", "method": method, "path": path, "headers": []})
    request.state.telegram_data = {}
    return request


def _bind_plex(tg_id: int) -> None:
    with get_session() as session:
        session.add(
            PlexUser(
                plex_id=tg_id * 10,
                tg_id=tg_id,
                plex_email=f"{tg_id}@example.com",
                plex_username=f"plex{tg_id}",
            )
        )


def _assign_row_id(mapper, connection, target) -> None:  # pragma: no cover - hook
    if target.id is None:
        target.id = next_id()


# SQLite 上 BIGINT 主键不自增，测试进程内插入的行在 flush 前补 id
for _model in (GiftPack, GiftPackUserState, SystemConfig, WheelStats):
    event.listen(_model, "before_insert", _assign_row_id)


async def _capture(cases: dict[str, Any], name: str, coro) -> None:
    try:
        result = await coro
    except HTTPException as exc:
        cases[name] = {
            "status": exc.status_code,
            "detail": _normalize(exc.detail),
        }
        return
    body = result.model_dump() if hasattr(result, "model_dump") else result
    cases[name] = {"status": 200, "body": _normalize(body)}


def _seed(orm) -> dict[str, int]:
    """建好契约所需的用户与礼包，并预置“领完”“已领取”两种状态。"""
    for tg_id in (1, 2, 3):
        add_user(orm, tg_id)
    _bind_plex(1)

    packs: dict[str, int] = {}
    packs["full"] = gift_pack_repository.create_gift_pack(
        "full pack", list(ALL_REWARDS), PAST, FUTURE
    )
    packs["disabled"] = gift_pack_repository.create_gift_pack(
        "disabled pack",
        [{"type": "credits", "amount": 1}],
        PAST,
        FUTURE,
        is_enabled=False,
    )
    packs["future"] = gift_pack_repository.create_gift_pack(
        "future pack", [{"type": "credits", "amount": 1}], FUTURE - 10, FUTURE
    )
    packs["ended"] = gift_pack_repository.create_gift_pack(
        "ended pack", [{"type": "credits", "amount": 1}], PAST - 100, PAST - 10
    )
    packs["sold_out"] = gift_pack_repository.create_gift_pack(
        "sold out pack",
        [{"type": "credits", "amount": 1}],
        PAST,
        FUTURE,
        total_quantity=1,
    )
    packs["claimed"] = gift_pack_repository.create_gift_pack(
        "claimed pack", [{"type": "credits", "amount": 1}], PAST, FUTURE
    )
    packs["conditions"] = gift_pack_repository.create_gift_pack(
        "conditions pack",
        [{"type": "credits", "amount": 1}],
        PAST,
        FUTURE,
        requirements=[{"type": "credits", "min": 10_000}],
    )
    packs["needs_binding"] = gift_pack_repository.create_gift_pack(
        "binding pack", [{"type": "premium_days", "days": 3}], PAST, FUTURE
    )

    gift_pack_repository.claim_gift_pack(packs["sold_out"], 3)
    gift_pack_repository.claim_gift_pack(packs["claimed"], 1)
    return packs


async def _build_contract(orm, monkeypatch) -> dict[str, Any]:
    monkeypatch.setattr(conftest, "_next_id", ID_BASE)
    packs = _seed(orm)
    cases: dict[str, Any] = {}

    def tg(tg_id: int) -> TelegramUser:
        return TelegramUser(id=tg_id, first_name="test")

    def claim(pack_id: int, tg_id: int):
        return gift_pack_router.claim_gift_pack(
            request=_request("POST", f"/api/gift-packs/{pack_id}/claim"),
            pack_id=pack_id,
            background_tasks=BackgroundTasks(),
            telegram_user=tg(tg_id),
        )

    # 外部副作用全部置为 no-op：契约只描述 HTTP 层可见行为
    monkeypatch.setattr(
        "app.domains.premium.service.sync_premium_media_access",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app.domains.premium.service.apply_download_unlock_to_media", lambda *args: None
    )
    monkeypatch.setattr(gift_pack_router, "check_admin_permission", lambda user: None)

    # ---- 用户端领取：成功与各类拒绝 ----
    await _capture(cases, "claim_success_all_rewards", claim(packs["full"], 1))
    await _capture(cases, "claim_reject_pack_missing", claim(MISSING_PACK, 1))
    await _capture(cases, "claim_reject_disabled", claim(packs["disabled"], 1))
    await _capture(cases, "claim_reject_not_started", claim(packs["future"], 1))
    await _capture(cases, "claim_reject_ended", claim(packs["ended"], 1))
    await _capture(cases, "claim_reject_sold_out", claim(packs["sold_out"], 1))
    await _capture(cases, "claim_reject_already_claimed", claim(packs["claimed"], 1))
    await _capture(cases, "claim_reject_conditions", claim(packs["conditions"], 1))
    await _capture(
        cases, "claim_reject_needs_binding", claim(packs["needs_binding"], 2)
    )

    # 发放阶段拒绝：奖励发放抛出的 ValueError 原样进 400
    def _reject_reward(*args, **kwargs):
        raise ValueError("发放阶段拒绝：奖励目标不可用")

    with monkeypatch.context() as patcher:
        patcher.setattr(
            gift_pack_repository.GiftPackRepository,
            "_grant_gift_pack_rewards",
            _reject_reward,
        )
        await _capture(
            cases, "claim_reject_reward_stage", claim(packs["needs_binding"], 1)
        )

    # 未知异常：500 + 领取失败通知（通知派发替换为记录器）
    notified: list[Any] = []

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    with monkeypatch.context() as patcher:
        patcher.setattr(
            gift_pack_notifications,
            "_notify_detached",
            lambda coro: notified.append(coro),
        )
        patcher.setattr(
            gift_pack_repository.GiftPackRepository, "claim_gift_pack", _boom
        )
        await _capture(cases, "claim_error_500", claim(packs["full"], 1))
    cases["claim_error_500"]["notifications"] = len(notified)

    # ---- 用户端列表与开屏提醒 ----
    await _capture(
        cases,
        "user_list_packs",
        gift_pack_router.list_gift_packs(request=_request("GET"), telegram_user=tg(1)),
    )
    await _capture(
        cases,
        "user_prompt_check",
        gift_pack_router.prompt_check(request=_request("POST"), telegram_user=tg(1)),
    )

    # ---- 管理端 8 个接口 ----
    await _capture(
        cases,
        "admin_resolve_users_ok",
        gift_pack_router.admin_resolve_gift_pack_users(
            request=_request(), text="1\n2", telegram_user=tg(1)
        ),
    )
    await _capture(
        cases,
        "admin_resolve_users_empty",
        gift_pack_router.admin_resolve_gift_pack_users(
            request=_request(), text="   ", telegram_user=tg(1)
        ),
    )
    await _capture(
        cases,
        "admin_list_packs",
        gift_pack_router.admin_list_gift_packs(
            request=_request("GET"), telegram_user=tg(1)
        ),
    )
    await _capture(
        cases,
        "admin_create_pack",
        gift_pack_router.admin_create_gift_pack(
            request=_request(),
            background_tasks=BackgroundTasks(),
            data=GiftPackCreateRequest(
                title="created pack",
                rewards=[{"type": "credits", "amount": 5}],
                start_at=PAST,
                end_at=FUTURE,
            ),
            telegram_user=tg(1),
        ),
    )
    await _capture(
        cases,
        "admin_create_pack_rejected",
        gift_pack_router.admin_create_gift_pack(
            request=_request(),
            background_tasks=BackgroundTasks(),
            data=GiftPackCreateRequest(
                title="bad pack",
                rewards=[{"type": "credits", "amount": 1}],
                audience=[{"type": "badge", "badge_id": 999}],
                start_at=PAST,
                end_at=FUTURE,
            ),
            telegram_user=tg(1),
        ),
    )
    await _capture(
        cases,
        "admin_update_pack",
        gift_pack_router.admin_update_gift_pack(
            request=_request("PUT"),
            pack_id=packs["full"],
            data=GiftPackUpdateRequest(description="updated"),
            telegram_user=tg(1),
        ),
    )
    await _capture(
        cases,
        "admin_update_pack_missing",
        gift_pack_router.admin_update_gift_pack(
            request=_request("PUT"),
            pack_id=MISSING_PACK,
            data=GiftPackUpdateRequest(description="nope"),
            telegram_user=tg(1),
        ),
    )
    await _capture(
        cases,
        "admin_set_enabled",
        gift_pack_router.admin_set_gift_pack_enabled(
            request=_request(),
            pack_id=packs["disabled"],
            data=GiftPackSetEnabledRequest(is_enabled=True),
            telegram_user=tg(1),
        ),
    )
    await _capture(
        cases,
        "admin_set_enabled_missing",
        gift_pack_router.admin_set_gift_pack_enabled(
            request=_request(),
            pack_id=MISSING_PACK,
            data=GiftPackSetEnabledRequest(is_enabled=True),
            telegram_user=tg(1),
        ),
    )
    await _capture(
        cases,
        "admin_delete_pack_missing",
        gift_pack_router.admin_delete_gift_pack(
            request=_request("DELETE"), pack_id=MISSING_PACK, telegram_user=tg(1)
        ),
    )
    await _capture(
        cases,
        "admin_delete_claimed_pack",
        gift_pack_router.admin_delete_gift_pack(
            request=_request("DELETE"), pack_id=packs["claimed"], telegram_user=tg(1)
        ),
    )
    await _capture(
        cases,
        "admin_delete_pack",
        gift_pack_router.admin_delete_gift_pack(
            request=_request("DELETE"), pack_id=packs["future"], telegram_user=tg(1)
        ),
    )
    await _capture(
        cases,
        "admin_pack_stats",
        gift_pack_router.admin_gift_pack_stats(
            request=_request("GET"), pack_id=packs["claimed"], telegram_user=tg(1)
        ),
    )
    await _capture(
        cases,
        "admin_pack_stats_missing",
        gift_pack_router.admin_gift_pack_stats(
            request=_request("GET"), pack_id=MISSING_PACK, telegram_user=tg(1)
        ),
    )
    await _capture(
        cases,
        "admin_pack_records",
        gift_pack_router.admin_gift_pack_records(
            request=_request("GET"), pack_id=packs["claimed"], telegram_user=tg(1)
        ),
    )
    return cases


async def test_gift_pack_http_contract(orm, monkeypatch) -> None:
    contract = await _build_contract(orm, monkeypatch)

    if os.environ.get("UPDATE_GIFT_PACK_CONTRACT") == "1":
        FIXTURE.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert contract == expected
