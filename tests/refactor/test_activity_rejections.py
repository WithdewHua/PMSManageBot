"""四个活动领域的拒绝分支契约：逐接口冻结请求到响应的映射。

`promote-activity-domains` 要保留的不只是正常路径，还有每条拒绝分支实际
返回的状态码与 detail——包括被前面分支遮蔽的分支、英文原文兜底，以及被
兜底 `except Exception` 吞成 500 的情况。这些细节只存在于代码里，所以本
用例把当前行为写成夹具，改造后逐项比对。

重新生成快照：

    UPDATE_ACTIVITY_REJECTIONS=1 .venv/bin/python -m pytest \
      tests/refactor/test_activity_rejections.py

外部副作用（TG 通知、调度提交、勋章检查、ETH RPC）在本用例内全部替换成
no-op：契约只描述 HTTP 层可见的行为。行 id 与时间戳都用固定常量，用例
自身不写库，因此可以连续生成两次比对一致。
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import event
from starlette.requests import Request
from starlette.responses import Response

from app.core.db import get_session
from app.core.kv import SystemConfig
from app.core.schemas import TelegramUser
from app.databases.db import DatabaseORM
from app.domains.auction import router as auc
from app.domains.auction.models import Auctions
from app.domains.auction.schemas import CreateAuctionRequest, PlaceBidRequest
from app.domains.luckywheel import notifications as luckywheel_notifications
from app.domains.luckywheel import router as lw
from app.domains.luckywheel.schemas import (
    LuckyWheelConfigUpdateRequest,
    LuckyWheelItem,
)
from app.domains.prediction import router as pred
from app.domains.prediction.models import PredictionMarket
from app.domains.prediction.schemas import (
    PredictionBetRequest,
    PredictionCreateMarketRequest,
    PredictionResolveRequest,
    PredictionSubmissionReviewRequest,
    PredictionSubmitRequest,
)
from app.domains.treasure import exceptions as treasure_exceptions
from app.domains.treasure import router as tr
from app.domains.treasure import service as treasure_service
from app.domains.treasure.models import TreasureIssue, TreasureParticipation
from app.domains.treasure.schemas import (
    TreasureCreateIssueRequest,
    TreasureJoinRequest,
)
from app.integrations import eth_rpc
from tests.conftest import add_user, next_id

FIXTURE = Path(__file__).parent / "fixtures/activity_rejections.json"

PAST = 1_700_000_000
FUTURE = 4_100_000_000

# 固定行 id：快照与执行顺序无关
TREASURE_ACTIVE = 101
TREASURE_CLOSED = 102
TREASURE_FULL = 103
TREASURE_LIMIT = 104
MARKET_OPEN = 201
MARKET_CLOSED = 202
MARKET_MAXBET = 203
AUCTION_ACTIVE = 301
AUCTION_INACTIVE = 302
AUCTION_EXPIRED = 303
AUCTION_OWN = 304
MISSING = 999_999

_USER1 = TelegramUser(id=1, first_name="u1", username="u1")
_USER2 = TelegramUser(id=2, first_name="u2", username="u2")
_GHOST = TelegramUser(id=3, first_name="u3", username="u3")
_ADMIN = TelegramUser(id=123456789, first_name="admin", username="admin")

_MODULES = {"luckywheel": lw, "treasure": tr, "prediction": pred, "auction": auc}


# --------------------------------------------------------------------------- #
# 夹具工具
# --------------------------------------------------------------------------- #


async def _async_none(*args: Any, **kwargs: Any) -> None:
    return None


async def _async_empty_list(*args: Any, **kwargs: Any) -> list:
    return []


def _raise(exc: Exception):
    def _stub(*args: Any, **kwargs: Any):
        raise exc

    return _stub


def _async_raise(exc: Exception):
    async def _stub(*args: Any, **kwargs: Any):
        raise exc

    return _stub


class _StubScheduler:
    """APScheduler 替身：拒绝分支里只要求它接受调用。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def add_async_job(self, *args: Any, **kwargs: Any) -> None:
        pass

    def add_job(self, *args: Any, **kwargs: Any) -> None:
        pass

    def remove_job(self, *args: Any, **kwargs: Any) -> None:
        pass


@contextmanager
def _patched(target: Any, name: str, value: Any) -> Iterator[None]:
    """临时替换属性；只回退这一处，不动 monkeypatch 的全局替换。"""
    missing = object()
    previous = getattr(target, name, missing)
    setattr(target, name, value)
    try:
        yield
    finally:
        if previous is missing:
            delattr(target, name)
        else:
            setattr(target, name, previous)


def _request() -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/api", "headers": []})
    request.state.telegram_data = {}
    return request


def _bare_request() -> Request:
    """没有 telegram_data 的请求：认证装饰器会在此拒绝。"""
    return Request({"type": "http", "method": "POST", "path": "/api", "headers": []})


def _details(value: Any) -> Any:
    """把 HTTPException.detail 规范成 JSON 友好的值。"""
    if isinstance(value, dict):
        return {str(key): _details(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_details(item) for item in value]
    return value


async def _capture(cases: dict[str, Any], key: str, coro) -> dict[str, Any]:
    try:
        result = await coro
    except HTTPException as exc:
        cases[key] = {"status": exc.status_code, "detail": _details(exc.detail)}
        return cases[key]
    except Exception as exc:  # 路由没有兜底分支：生产由 ASGI 兜底为 500
        cases[key] = {"status": "unhandled", "type": type(exc).__name__}
        return cases[key]

    if isinstance(result, Response):
        body = json.loads(result.body) if result.body else None
    elif hasattr(result, "model_dump"):
        body = result.model_dump()
    else:
        body = result
    cases[key] = {"status": 200, "body": body}
    return cases[key]


# --------------------------------------------------------------------------- #
# 数据播种
# --------------------------------------------------------------------------- #


def _assign_row_id(mapper, connection, target) -> None:  # pragma: no cover - hook
    if target.id is None:
        target.id = next_id()


# SQLite 上 BIGINT 主键不自增，测试进程内插入的行在 flush 前补 id
for _model in (SystemConfig, TreasureIssue, TreasureParticipation):
    event.listen(_model, "before_insert", _assign_row_id)


def _insert(model: Any, row_id: int, **kwargs: Any) -> int:
    with get_session() as session:
        row = model(id=row_id, **kwargs)
        session.add(row)
        session.flush()
        return int(row.id)


def _seed(orm: DatabaseORM) -> None:
    add_user(orm, 1, credits=100.0)
    add_user(orm, 2, credits=5.0)

    for issue_id, status, shares_sold in (
        (TREASURE_ACTIVE, 1, 0),
        (TREASURE_CLOSED, 2, 10),
        (TREASURE_FULL, 1, 10),
        (TREASURE_LIMIT, 1, 2),
    ):
        _insert(
            TreasureIssue,
            issue_id,
            title=f"issue-{issue_id}",
            description="d",
            prize_credits=50,
            total_credits_required=100,
            credits_per_share=10,
            total_shares=10,
            start_number=10_000_001,
            status=status,
            shares_sold=shares_sold,
        )
    # 单用户购买上限：总份数 10 → 每人最多 2 份；这两行让路由的第 3 份被拒
    for offset in range(2):
        _insert(
            TreasureParticipation,
            500 + offset,
            issue_id=TREASURE_LIMIT,
            tg_id=1,
            lucky_number=10_000_001 + offset,
            cost_credits=10,
            created_at_ms=PAST + offset,
        )

    for market_id, status, max_bet in (
        (MARKET_OPEN, 1, 500),
        (MARKET_CLOSED, 2, 500),
        (MARKET_MAXBET, 1, 5),
    ):
        _insert(
            PredictionMarket,
            market_id,
            title=f"market-{market_id}",
            description="d",
            status=status,
            result_option=None,
            betting_deadline=FUTURE,
            max_bet_per_user=max_bet,
        )

    for auction_id, is_active, end_time, created_by in (
        (AUCTION_ACTIVE, 1, FUTURE, 99),
        (AUCTION_INACTIVE, 0, FUTURE, 99),
        (AUCTION_EXPIRED, 1, PAST, 99),
        (AUCTION_OWN, 1, FUTURE, 1),
    ):
        _insert(
            Auctions,
            auction_id,
            title=f"auction-{auction_id}",
            description="d",
            starting_price=10.0,
            current_price=100.0,
            end_time=end_time,
            created_by=created_by,
            created_at=PAST,
            is_active=is_active,
            winner_id=None,
            bid_count=1,
        )


# --------------------------------------------------------------------------- #
# 共享装饰器分支：认证（401）与管理端权限（403）
# --------------------------------------------------------------------------- #

_CONFIG_UPDATE_OK = LuckyWheelConfigUpdateRequest(
    items=[LuckyWheelItem(name="x", probability=100.0)]
)
_CREATE_ISSUE_OK = TreasureCreateIssueRequest(
    prize_credits=50, total_credits_required=100
)
_CREATE_MARKET_OK = PredictionCreateMarketRequest(title="t", betting_deadline=FUTURE)
_CREATE_AUCTION_OK = CreateAuctionRequest(
    title="t", description="d", starting_price=10.0, duration_hours=1
)

_ENDPOINT_ARGS: dict[str, dict[str, Any]] = {
    # luckywheel
    "luckywheel.update_config": {
        "config_update_request": _CONFIG_UPDATE_OK,
        "current_user": _USER1,
    },
    "luckywheel.get_free_spins": {"current_user": _USER1},
    "luckywheel.spin_wheel": {
        "background_tasks": BackgroundTasks(),
        "current_user": _USER1,
    },
    "luckywheel.spin_wheel_ten_times": {
        "background_tasks": BackgroundTasks(),
        "current_user": _USER1,
    },
    "luckywheel.get_user_status": {"current_user": _USER1},
    "luckywheel.get_randomness_statistics": {
        "iterations": 10,
        "current_user": _USER1,
    },
    "luckywheel.update_randomness_config": {
        "config_data": {},
        "current_user": _USER1,
    },
    "luckywheel.get_randomness_config": {"current_user": _USER1},
    "luckywheel.get_wheel_statistics": {"current_user": _USER1},
    "luckywheel.get_user_activity_stats": {"current_user": _USER1},
    # treasure
    "treasure.get_user_treasure_stats": {"current_user": _USER1},
    "treasure.list_issues": {"current_user": _USER1},
    "treasure.get_issue_detail": {"issue_id": TREASURE_ACTIVE, "current_user": _USER1},
    "treasure.list_participations": {
        "issue_id": TREASURE_ACTIVE,
        "current_user": _USER1,
    },
    "treasure.join_issue": {
        "issue_id": TREASURE_ACTIVE,
        "background_tasks": BackgroundTasks(),
        "data": TreasureJoinRequest(quantity=1),
        "current_user": _USER1,
    },
    "treasure.create_issue": {"data": _CREATE_ISSUE_OK, "current_user": _USER1},
    "treasure.cancel_issue": {"issue_id": TREASURE_ACTIVE, "current_user": _USER1},
    # prediction
    "prediction.list_markets": {"current_user": _USER1},
    "prediction.get_market_detail": {"market_id": MARKET_OPEN, "current_user": _USER1},
    "prediction.list_market_bets": {"market_id": MARKET_OPEN, "current_user": _USER1},
    "prediction.place_bet": {
        "market_id": MARKET_OPEN,
        "background_tasks": BackgroundTasks(),
        "data": PredictionBetRequest(option=1, amount=10),
        "current_user": _USER1,
    },
    "prediction.create_market": {
        "data": _CREATE_MARKET_OK,
        "current_user": _USER1,
    },
    "prediction.submit_market": {
        "data": PredictionSubmitRequest(title="t", betting_deadline=FUTURE),
        "current_user": _USER1,
    },
    "prediction.list_submissions": {"current_user": _USER1},
    "prediction.review_submission": {
        "submission_id": 1,
        "data": PredictionSubmissionReviewRequest(approved=True),
        "current_user": _USER1,
    },
    "prediction.close_market_betting": {
        "market_id": MARKET_OPEN,
        "current_user": _USER1,
    },
    "prediction.resolve_market": {
        "market_id": MARKET_OPEN,
        "background_tasks": BackgroundTasks(),
        "data": PredictionResolveRequest(result_option=1),
        "current_user": _USER1,
    },
    "prediction.get_user_prediction_stats": {"current_user": _USER1},
    # auction
    "auction.get_auction_list": {"current_user": _USER1},
    "auction.get_auction_stats": {"current_user": _USER1},
    "auction.get_auction_detail": {
        "auction_id": AUCTION_ACTIVE,
        "current_user": _USER1,
    },
    "auction.create_auction": {
        "request_data": _CREATE_AUCTION_OK,
        "background_tasks": BackgroundTasks(),
        "current_user": _USER1,
    },
    "auction.place_bid": {
        "bid_request": PlaceBidRequest(auction_id=AUCTION_ACTIVE, bid_amount=150),
        "background_tasks": BackgroundTasks(),
        "current_user": _USER1,
    },
    "auction.finish_expired_auctions": {"current_user": _USER1},
    "auction.get_all_auctions_admin": {"current_user": _USER1},
    "auction.update_auction_admin": {
        "auction_id": AUCTION_ACTIVE,
        "update_data": _CREATE_AUCTION_OK,
        "current_user": _USER1,
    },
    "auction.delete_auction_admin": {
        "auction_id": AUCTION_ACTIVE,
        "current_user": _USER1,
    },
    "auction.finish_auction_admin": {
        "auction_id": AUCTION_ACTIVE,
        "background_tasks": BackgroundTasks(),
        "current_user": _USER1,
    },
    "auction.get_auction_bids_admin": {
        "auction_id": AUCTION_ACTIVE,
        "current_user": _USER1,
    },
    "auction.get_user_auction_history_admin": {"user_id": 1, "current_user": _USER1},
    "auction.get_detailed_auction_stats_admin": {"current_user": _USER1},
}

_ADMIN_KEYS = frozenset(
    {
        "luckywheel.update_config",
        "luckywheel.get_randomness_statistics",
        "luckywheel.update_randomness_config",
        "luckywheel.get_randomness_config",
        "luckywheel.get_wheel_statistics",
        "treasure.create_issue",
        "treasure.cancel_issue",
        "prediction.create_market",
        "prediction.review_submission",
        "prediction.close_market_betting",
        "prediction.resolve_market",
        "auction.get_auction_stats",
        "auction.create_auction",
        "auction.get_all_auctions_admin",
        "auction.update_auction_admin",
        "auction.delete_auction_admin",
        "auction.finish_auction_admin",
        "auction.get_auction_bids_admin",
        "auction.get_user_auction_history_admin",
        "auction.get_detailed_auction_stats_admin",
    }
)


def endpoint_fn(key: str):
    domain, name = key.split(".", 1)
    return getattr(_MODULES[domain], name)


async def _build_shared(cases: dict[str, Any]) -> None:
    """认证装饰器与管理员权限是所有接口共用分支，逐接口确认它没有掉。"""
    for key, kwargs in _ENDPOINT_ARGS.items():
        func = endpoint_fn(key)
        await _capture(
            cases, f"{key}.auth_required", func(request=_bare_request(), **kwargs)
        )
    for key in sorted(_ADMIN_KEYS):
        func = endpoint_fn(key)
        await _capture(
            cases, f"{key}.forbidden", func(request=_request(), **_ENDPOINT_ARGS[key])
        )


# --------------------------------------------------------------------------- #
# 各领域的分支
# --------------------------------------------------------------------------- #


async def _build_luckywheel(cases: dict[str, Any]) -> None:
    d = "luckywheel"

    # GET /config 没有自己的兜底：get_wheel_config 内部吞掉异常，只有替换它才看得到
    with _patched(
        lw.luckywheel_service, "get_wheel_config", _raise(RuntimeError("boom"))
    ):
        await _capture(cases, f"{d}.get_config.load_failure", lw.get_config())

    # PUT /config
    bad_sum = LuckyWheelConfigUpdateRequest(
        items=[LuckyWheelItem(name="x", probability=50.0)]
    )
    await _capture(
        cases,
        f"{d}.update_config.probability_sum",
        lw.update_config(
            request=_request(),
            config_update_request=bad_sum,
            current_user=_ADMIN,
        ),
    )
    with _patched(lw.luckywheel_service, "save_wheel_config", lambda config: False):
        await _capture(
            cases,
            f"{d}.update_config.save_config_failure",
            lw.update_config(
                request=_request(),
                config_update_request=_CONFIG_UPDATE_OK,
                current_user=_ADMIN,
            ),
        )
    with _patched(
        lw.luckywheel_service, "save_wheel_config", _raise(RuntimeError("boom"))
    ):
        await _capture(
            cases,
            f"{d}.update_config.save_failure",
            lw.update_config(
                request=_request(),
                config_update_request=_CONFIG_UPDATE_OK,
                current_user=_ADMIN,
            ),
        )

    # GET /free-spins 没有兜底分支：服务异常直接冒泡（生产由 ASGI 兜底为 500）
    with _patched(
        lw.luckywheel_service,
        "free_spin_summary",
        _raise(RuntimeError("boom")),
    ):
        await _capture(
            cases,
            f"{d}.get_free_spins.unhandled_service_error",
            lw.get_free_spins(request=_request(), current_user=_USER1),
        )

    # POST /spin
    await _capture(
        cases,
        f"{d}.spin_wheel.404_user_not_found",
        lw.spin_wheel(
            request=_request(),
            background_tasks=BackgroundTasks(),
            current_user=_GHOST,
        ),
    )
    await _capture(
        cases,
        f"{d}.spin_wheel.400_min_credits",
        lw.spin_wheel(
            request=_request(),
            background_tasks=BackgroundTasks(),
            current_user=_USER2,
        ),
    )
    with _patched(lw.luckywheel_service, "spin", _async_raise(RuntimeError("boom"))):
        await _capture(
            cases,
            f"{d}.spin_wheel.500_unexpected",
            lw.spin_wheel(
                request=_request(),
                background_tasks=BackgroundTasks(),
                current_user=_USER1,
            ),
        )

    # 免费机会路径：抽奖失败时补偿释放（现状行为，改造后由事务回滚替代）
    released: dict[str, Any] = {}
    with _patched(lw.luckywheel_service, "spin", _async_raise(RuntimeError("boom"))):
        captured = await _capture(
            cases,
            f"{d}.spin_wheel.500_free_spin_released",
            lw.spin_wheel(
                request=_request(),
                background_tasks=BackgroundTasks(),
                current_user=_USER1,
            ),
        )
        captured["effects"] = dict(released)

    # POST /spin-ten
    await _capture(
        cases,
        f"{d}.spin_wheel_ten_times.404_user_not_found",
        lw.spin_wheel_ten_times(
            request=_request(),
            background_tasks=BackgroundTasks(),
            current_user=_GHOST,
        ),
    )
    await _capture(
        cases,
        f"{d}.spin_wheel_ten_times.400_min_credits",
        lw.spin_wheel_ten_times(
            request=_request(),
            background_tasks=BackgroundTasks(),
            current_user=_USER2,
        ),
    )
    await _capture(
        cases,
        f"{d}.spin_wheel_ten_times.500_unexpected",
        lw.spin_wheel_ten_times(
            request=_request(),
            background_tasks=BackgroundTasks(),
            current_user=_USER1,
        ),
    )

    # GET /user-status：404 被兜底 except 吞成 500
    await _capture(
        cases,
        f"{d}.get_user_status.404_swallowed_to_500",
        lw.get_user_status(request=_request(), current_user=_GHOST),
    )

    # GET /randomness-stats
    with _patched(
        lw.luckywheel_service, "get_wheel_config", _raise(RuntimeError("boom"))
    ):
        await _capture(
            cases,
            f"{d}.get_randomness_statistics.500_unexpected",
            lw.get_randomness_statistics(
                request=_request(), iterations=10, current_user=_ADMIN
            ),
        )

    # GET /randomness-config：配置读取内部吞异常，只有替换它才看得到 500
    with _patched(
        lw.luckywheel_service,
        "get_randomness_config",
        _raise(RuntimeError("boom")),
    ):
        await _capture(
            cases,
            f"{d}.get_randomness_config.500_unexpected",
            lw.get_randomness_config(request=_request(), current_user=_ADMIN),
        )

    # PUT /randomness-config
    await _capture(
        cases,
        f"{d}.update_randomness_config.500_invalid_threshold",
        lw.update_randomness_config(
            request=_request(),
            config_data={"protection_threshold": 100},
            current_user=_ADMIN,
        ),
    )
    await _capture(
        cases,
        f"{d}.update_randomness_config.500_invalid_factor",
        lw.update_randomness_config(
            request=_request(),
            config_data={"protection_factor": 5},
            current_user=_ADMIN,
        ),
    )
    with _patched(
        lw.luckywheel_service.wheel_config,
        "save_randomness_config",
        lambda config: False,
    ):
        await _capture(
            cases,
            f"{d}.update_randomness_config.500_write_failure",
            lw.update_randomness_config(
                request=_request(),
                config_data={"protection_threshold": 10},
                current_user=_ADMIN,
            ),
        )
    with _patched(
        lw.luckywheel_service,
        "get_randomness_config",
        _raise(RuntimeError("boom")),
    ):
        await _capture(
            cases,
            f"{d}.update_randomness_config.500_unexpected",
            lw.update_randomness_config(
                request=_request(), config_data={}, current_user=_ADMIN
            ),
        )

    # GET /stats、GET /user-activity-stats
    with _patched(
        lw.luckywheel_service, "get_wheel_stats", _raise(RuntimeError("boom"))
    ):
        await _capture(
            cases,
            f"{d}.get_wheel_statistics.500_unexpected",
            lw.get_wheel_statistics(request=_request(), current_user=_ADMIN),
        )
    with _patched(
        lw.luckywheel_service,
        "get_user_wheel_stats",
        _raise(RuntimeError("boom")),
    ):
        await _capture(
            cases,
            f"{d}.get_user_activity_stats.500_unexpected",
            lw.get_user_activity_stats(request=_request(), current_user=_USER1),
        )


async def _build_treasure(cases: dict[str, Any]) -> None:
    d = "treasure"

    def join(issue_id: int, user: TelegramUser, quantity: int = 1):
        return tr.join_issue(
            request=_request(),
            issue_id=issue_id,
            background_tasks=BackgroundTasks(),
            data=TreasureJoinRequest(quantity=quantity),
            current_user=user,
        )

    await _capture(cases, f"{d}.join_issue.404_issue_not_found", join(MISSING, _USER1))
    await _capture(
        cases, f"{d}.join_issue.400_issue_not_active", join(TREASURE_CLOSED, _USER1)
    )
    await _capture(cases, f"{d}.join_issue.400_issue_full", join(TREASURE_FULL, _USER1))
    await _capture(
        cases, f"{d}.join_issue.400_insufficient_credits", join(TREASURE_ACTIVE, _USER2)
    )
    # 被遮蔽分支：仓储抛 “user stats not found”，但路由先匹配 “not found”
    await _capture(
        cases,
        f"{d}.join_issue.404_shadowed_user_stats_not_found",
        join(TREASURE_ACTIVE, _GHOST),
    )
    await _capture(
        cases, f"{d}.join_issue.400_purchase_limit", join(TREASURE_LIMIT, _USER1)
    )
    for branch, message in (
        ("400_quantity_must_be_positive", "quantity must be > 0"),
        ("400_quantity_too_large", "quantity too large"),
        ("400_english_fallback", "invalid number range"),
    ):
        error_factory = {
            "quantity must be > 0": treasure_exceptions.quantity_invalid,
            "quantity too large": treasure_exceptions.quantity_too_large,
            "invalid number range": treasure_exceptions.invalid_number_range,
        }[message]
        with _patched(treasure_service, "join_treasure_issue", _raise(error_factory())):
            await _capture(
                cases, f"{d}.join_issue.{branch}", join(TREASURE_ACTIVE, _USER1)
            )
    with _patched(
        treasure_service, "join_treasure_issue", _raise(RuntimeError("boom"))
    ):
        await _capture(
            cases, f"{d}.join_issue.500_unexpected", join(TREASURE_ACTIVE, _USER1)
        )

    # POST /create
    for branch, data in (
        (
            "400_total_shares_must_be_positive",
            TreasureCreateIssueRequest(
                prize_credits=1, total_credits_required=5, credits_per_share=10
            ),
        ),
        (
            "400_not_divisible",
            TreasureCreateIssueRequest(
                prize_credits=50, total_credits_required=105, credits_per_share=10
            ),
        ),
        (
            "400_invalid_credits_settings",
            TreasureCreateIssueRequest(
                prize_credits=200, total_credits_required=100, credits_per_share=10
            ),
        ),
    ):
        await _capture(
            cases,
            f"{d}.create_issue.{branch}",
            tr.create_issue(request=_request(), data=data, current_user=_ADMIN),
        )
    with _patched(
        treasure_service,
        "create_treasure_issue",
        _raise(treasure_exceptions.start_number_invalid()),
    ):
        await _capture(
            cases,
            f"{d}.create_issue.400_english_fallback",
            tr.create_issue(
                request=_request(), data=_CREATE_ISSUE_OK, current_user=_ADMIN
            ),
        )
    with _patched(
        treasure_service, "create_treasure_issue", _raise(RuntimeError("boom"))
    ):
        await _capture(
            cases,
            f"{d}.create_issue.500_unexpected",
            tr.create_issue(
                request=_request(), data=_CREATE_ISSUE_OK, current_user=_ADMIN
            ),
        )

    # POST /{issue_id}/cancel
    await _capture(
        cases,
        f"{d}.cancel_issue.404_issue_not_found",
        tr.cancel_issue(request=_request(), issue_id=MISSING, current_user=_ADMIN),
    )
    await _capture(
        cases,
        f"{d}.cancel_issue.400_not_active",
        tr.cancel_issue(
            request=_request(), issue_id=TREASURE_CLOSED, current_user=_ADMIN
        ),
    )
    with _patched(
        treasure_service, "cancel_treasure_issue", _raise(RuntimeError("boom"))
    ):
        await _capture(
            cases,
            f"{d}.cancel_issue.500_unexpected",
            tr.cancel_issue(
                request=_request(), issue_id=TREASURE_ACTIVE, current_user=_ADMIN
            ),
        )

    # 只读接口的兜底 500
    with _patched(
        treasure_service, "get_user_treasure_stats", _raise(RuntimeError("boom"))
    ):
        await _capture(
            cases,
            f"{d}.get_user_treasure_stats.500_unexpected",
            tr.get_user_treasure_stats(request=_request(), current_user=_USER1),
        )
    with _patched(
        treasure_service, "list_treasure_issues", _raise(RuntimeError("boom"))
    ):
        await _capture(
            cases,
            f"{d}.list_issues.500_unexpected",
            tr.list_issues(request=_request(), current_user=_USER1),
        )
    await _capture(
        cases,
        f"{d}.get_issue_detail.404_issue_not_found",
        tr.get_issue_detail(request=_request(), issue_id=MISSING, current_user=_USER1),
    )
    with _patched(
        treasure_service,
        "list_treasure_participations",
        _raise(RuntimeError("boom")),
    ):
        await _capture(
            cases,
            f"{d}.list_participations.500_unexpected",
            tr.list_participations(
                request=_request(), issue_id=TREASURE_ACTIVE, current_user=_USER1
            ),
        )


async def _build_prediction(cases: dict[str, Any]) -> None:
    d = "prediction"

    def bet(market_id: int, user: TelegramUser, amount: int = 10):
        return pred.place_bet(
            request=_request(),
            market_id=market_id,
            background_tasks=BackgroundTasks(),
            data=PredictionBetRequest(option=1, amount=amount),
            current_user=user,
        )

    await _capture(cases, f"{d}.place_bet.404_market_not_found", bet(MISSING, _USER1))
    await _capture(
        cases, f"{d}.place_bet.400_market_not_open", bet(MARKET_CLOSED, _USER1)
    )
    await _capture(
        cases, f"{d}.place_bet.400_insufficient_credits", bet(MARKET_OPEN, _USER2)
    )
    await _capture(
        cases, f"{d}.place_bet.400_max_bet_exceeded", bet(MARKET_MAXBET, _USER1, 10)
    )
    # 被遮蔽分支：仓储抛 “user stats not found”，路由先匹配 “not found”
    await _capture(
        cases,
        f"{d}.place_bet.404_shadowed_user_stats_not_found",
        bet(MARKET_OPEN, _GHOST),
    )
    for branch, message in (
        ("400_english_fallback", "invalid option"),
        ("400_amount_must_be_positive", "amount must be > 0"),
    ):
        with _patched(
            pred.prediction_service, "place_prediction_bet", _raise(ValueError(message))
        ):
            await _capture(cases, f"{d}.place_bet.{branch}", bet(MARKET_OPEN, _USER1))
    with _patched(
        pred.prediction_service, "place_prediction_bet", _raise(RuntimeError("boom"))
    ):
        await _capture(cases, f"{d}.place_bet.500_unexpected", bet(MARKET_OPEN, _USER1))

    # POST /create：截止时间检查抛 400，却先被兜底 except 吞成 500
    await _capture(
        cases,
        f"{d}.create_market.500_deadline_swallowed",
        pred.create_market(
            request=_request(),
            data=PredictionCreateMarketRequest(title="t", betting_deadline=PAST),
            current_user=_ADMIN,
        ),
    )
    for branch, message, deadline in (
        (
            "400_betting_deadline_invalid",
            "betting_deadline is required",
            FUTURE,
        ),
        ("400_english_fallback", "title is required", FUTURE),
    ):
        with _patched(
            pred.prediction_service,
            "create_prediction_market",
            _raise(ValueError(message)),
        ):
            await _capture(
                cases,
                f"{d}.create_market.{branch}",
                pred.create_market(
                    request=_request(),
                    data=PredictionCreateMarketRequest(
                        title="t", betting_deadline=deadline
                    ),
                    current_user=_ADMIN,
                ),
            )
    with _patched(
        pred.prediction_service,
        "create_prediction_market",
        _raise(RuntimeError("boom")),
    ):
        await _capture(
            cases,
            f"{d}.create_market.500_unexpected",
            pred.create_market(
                request=_request(), data=_CREATE_MARKET_OK, current_user=_ADMIN
            ),
        )

    # POST /submit：同样的 400 → 500
    await _capture(
        cases,
        f"{d}.submit_market.500_deadline_swallowed",
        pred.submit_market(
            request=_request(),
            data=PredictionSubmitRequest(title="t", betting_deadline=PAST),
            current_user=_USER1,
        ),
    )
    for branch, message in (
        ("400_betting_deadline_invalid", "betting_deadline must be in the future"),
        ("400_english_fallback", "title is required"),
    ):
        with _patched(
            pred.prediction_service,
            "submit_prediction_market",
            _raise(ValueError(message)),
        ):
            await _capture(
                cases,
                f"{d}.submit_market.{branch}",
                pred.submit_market(
                    request=_request(),
                    data=PredictionSubmitRequest(title="t", betting_deadline=FUTURE),
                    current_user=_USER1,
                ),
            )
    with _patched(
        pred.prediction_service,
        "submit_prediction_market",
        _raise(RuntimeError("boom")),
    ):
        await _capture(
            cases,
            f"{d}.submit_market.500_unexpected",
            pred.submit_market(
                request=_request(),
                data=PredictionSubmitRequest(title="t", betting_deadline=FUTURE),
                current_user=_USER1,
            ),
        )

    # POST /submissions/{id}/review
    for branch, message in (
        ("404_submission_not_found", "submission not found"),
        ("400_already_reviewed", "submission already reviewed"),
        ("400_betting_deadline_invalid", "betting_deadline must be in the future"),
        ("400_english_fallback", "invalid fee split"),
    ):
        with _patched(
            pred.prediction_service,
            "review_prediction_submission",
            _raise(ValueError(message)),
        ):
            await _capture(
                cases,
                f"{d}.review_submission.{branch}",
                pred.review_submission(
                    request=_request(),
                    submission_id=1,
                    data=PredictionSubmissionReviewRequest(approved=True),
                    current_user=_ADMIN,
                ),
            )
    with _patched(
        pred.prediction_service,
        "review_prediction_submission",
        _raise(RuntimeError("boom")),
    ):
        await _capture(
            cases,
            f"{d}.review_submission.500_unexpected",
            pred.review_submission(
                request=_request(),
                submission_id=1,
                data=PredictionSubmissionReviewRequest(approved=True),
                current_user=_ADMIN,
            ),
        )

    # POST /{market_id}/close
    for branch, message in (
        ("404_market_not_found", "market not found"),
        ("400_english_fallback", "market not open"),
    ):
        with _patched(
            pred.prediction_service,
            "close_prediction_market_betting",
            _raise(ValueError(message)),
        ):
            await _capture(
                cases,
                f"{d}.close_market_betting.{branch}",
                pred.close_market_betting(
                    request=_request(), market_id=MARKET_OPEN, current_user=_ADMIN
                ),
            )
    with _patched(
        pred.prediction_service,
        "close_prediction_market_betting",
        _raise(RuntimeError("boom")),
    ):
        await _capture(
            cases,
            f"{d}.close_market_betting.500_unexpected",
            pred.close_market_betting(
                request=_request(), market_id=MARKET_OPEN, current_user=_ADMIN
            ),
        )

    # POST /{market_id}/resolve
    for branch, message in (
        ("404_market_not_found", "market not found"),
        ("400_english_fallback", "invalid result option"),
    ):
        with _patched(
            pred.prediction_service,
            "resolve_prediction_market",
            _raise(ValueError(message)),
        ):
            await _capture(
                cases,
                f"{d}.resolve_market.{branch}",
                pred.resolve_market(
                    request=_request(),
                    market_id=MARKET_OPEN,
                    background_tasks=BackgroundTasks(),
                    data=PredictionResolveRequest(result_option=1),
                    current_user=_ADMIN,
                ),
            )
    with _patched(
        pred.prediction_service,
        "resolve_prediction_market",
        _raise(RuntimeError("boom")),
    ):
        await _capture(
            cases,
            f"{d}.resolve_market.500_unexpected",
            pred.resolve_market(
                request=_request(),
                market_id=MARKET_OPEN,
                background_tasks=BackgroundTasks(),
                data=PredictionResolveRequest(result_option=1),
                current_user=_ADMIN,
            ),
        )

    # 只读接口
    with _patched(
        pred.prediction_service, "list_prediction_markets", _raise(RuntimeError("boom"))
    ):
        await _capture(
            cases,
            f"{d}.list_markets.500_unexpected",
            pred.list_markets(request=_request(), current_user=_USER1),
        )
    await _capture(
        cases,
        f"{d}.get_market_detail.404_market_not_found",
        pred.get_market_detail(
            request=_request(), market_id=MISSING, current_user=_USER1
        ),
    )
    with _patched(
        pred.prediction_service, "list_prediction_bets", _raise(RuntimeError("boom"))
    ):
        await _capture(
            cases,
            f"{d}.list_market_bets.500_unexpected",
            pred.list_market_bets(
                request=_request(), market_id=MARKET_OPEN, current_user=_USER1
            ),
        )
    with _patched(
        pred.prediction_service,
        "list_prediction_submissions",
        _raise(RuntimeError("boom")),
    ):
        await _capture(
            cases,
            f"{d}.list_submissions.500_unexpected",
            pred.list_submissions(request=_request(), current_user=_USER1),
        )
    with _patched(
        pred.prediction_service,
        "get_prediction_user_stats",
        _raise(RuntimeError("boom")),
    ):
        await _capture(
            cases,
            f"{d}.get_user_prediction_stats.500_unexpected",
            pred.get_user_prediction_stats(request=_request(), current_user=_USER1),
        )


async def _build_auction(cases: dict[str, Any]) -> None:
    d = "auction"

    def bid(auction_id: int, user: TelegramUser, amount: float):
        return auc.place_bid(
            request=_request(),
            bid_request=PlaceBidRequest(auction_id=auction_id, bid_amount=amount),
            background_tasks=BackgroundTasks(),
            current_user=user,
        )

    with _patched(DatabaseORM, "get_active_auctions", _raise(RuntimeError("boom"))):
        await _capture(
            cases,
            f"{d}.get_auction_list.500_unexpected",
            auc.get_auction_list(request=_request(), current_user=_USER1),
        )
    with _patched(DatabaseORM, "get_auction_stats", _raise(RuntimeError("boom"))):
        await _capture(
            cases,
            f"{d}.get_auction_stats.500_unexpected",
            auc.get_auction_stats(request=_request(), current_user=_ADMIN),
        )
    await _capture(
        cases,
        f"{d}.get_auction_detail.404_not_found",
        auc.get_auction_detail(
            auction_id=MISSING, request=_request(), current_user=_USER1
        ),
    )
    with _patched(DatabaseORM, "get_auction_by_id", _raise(RuntimeError("boom"))):
        await _capture(
            cases,
            f"{d}.get_auction_detail.500_unexpected",
            auc.get_auction_detail(
                auction_id=AUCTION_ACTIVE, request=_request(), current_user=_USER1
            ),
        )

    # POST /create
    with _patched(DatabaseORM, "create_auction", lambda *a, **k: None):
        await _capture(
            cases,
            f"{d}.create_auction.500_db_returned_false",
            auc.create_auction(
                request_data=_CREATE_AUCTION_OK,
                background_tasks=BackgroundTasks(),
                request=_request(),
                current_user=_ADMIN,
            ),
        )
    with _patched(DatabaseORM, "create_auction", _raise(RuntimeError("boom"))):
        await _capture(
            cases,
            f"{d}.create_auction.500_unexpected",
            auc.create_auction(
                request_data=_CREATE_AUCTION_OK,
                background_tasks=BackgroundTasks(),
                request=_request(),
                current_user=_ADMIN,
            ),
        )

    # POST /bid
    await _capture(cases, f"{d}.place_bid.404_not_found", bid(MISSING, _USER1, 150))
    await _capture(
        cases, f"{d}.place_bid.400_auction_ended", bid(AUCTION_INACTIVE, _USER1, 150)
    )
    await _capture(
        cases, f"{d}.place_bid.400_auction_expired", bid(AUCTION_EXPIRED, _USER1, 150)
    )
    await _capture(
        cases, f"{d}.place_bid.400_own_auction", bid(AUCTION_OWN, _USER1, 150)
    )
    await _capture(
        cases, f"{d}.place_bid.400_bid_too_low", bid(AUCTION_ACTIVE, _USER1, 50)
    )
    await _capture(
        cases, f"{d}.place_bid.400_no_credits_row", bid(AUCTION_ACTIVE, _GHOST, 150)
    )
    await _capture(
        cases,
        f"{d}.place_bid.400_insufficient_credits",
        bid(AUCTION_ACTIVE, _USER2, 150),
    )
    with _patched(DatabaseORM, "place_bid", lambda *a, **k: False):
        await _capture(
            cases,
            f"{d}.place_bid.500_db_returned_false",
            bid(AUCTION_ACTIVE, _USER1, 150),
        )
    with _patched(DatabaseORM, "place_bid", _raise(RuntimeError("boom"))):
        await _capture(
            cases, f"{d}.place_bid.500_unexpected", bid(AUCTION_ACTIVE, _USER1, 150)
        )

    # POST /finish-expired
    with _patched(
        auc, "finish_expired_auctions_job", _async_raise(RuntimeError("boom"))
    ):
        await _capture(
            cases,
            f"{d}.finish_expired_auctions.500_unexpected",
            auc.finish_expired_auctions(request=_request(), current_user=_ADMIN),
        )

    # GET /admin/list
    with _patched(DatabaseORM, "get_all_auctions", _raise(RuntimeError("boom"))):
        await _capture(
            cases,
            f"{d}.get_all_auctions_admin.500_unexpected",
            auc.get_all_auctions_admin(request=_request(), current_user=_ADMIN),
        )

    # PUT /admin/{auction_id}
    await _capture(
        cases,
        f"{d}.update_auction_admin.404_not_found",
        auc.update_auction_admin(
            auction_id=MISSING,
            update_data=_CREATE_AUCTION_OK,
            request=_request(),
            current_user=_ADMIN,
        ),
    )
    with _patched(DatabaseORM, "update_auction", lambda *a, **k: False):
        await _capture(
            cases,
            f"{d}.update_auction_admin.500_db_returned_false",
            auc.update_auction_admin(
                auction_id=AUCTION_ACTIVE,
                update_data=_CREATE_AUCTION_OK,
                request=_request(),
                current_user=_ADMIN,
            ),
        )

    # DELETE /admin/{auction_id}
    await _capture(
        cases,
        f"{d}.delete_auction_admin.404_not_found",
        auc.delete_auction_admin(
            auction_id=MISSING, request=_request(), current_user=_ADMIN
        ),
    )
    with _patched(DatabaseORM, "delete_auction", lambda *a, **k: False):
        await _capture(
            cases,
            f"{d}.delete_auction_admin.500_db_returned_false",
            auc.delete_auction_admin(
                auction_id=AUCTION_ACTIVE, request=_request(), current_user=_ADMIN
            ),
        )

    # POST /admin/{auction_id}/finish
    await _capture(
        cases,
        f"{d}.finish_auction_admin.404_not_found",
        auc.finish_auction_admin(
            auction_id=MISSING,
            background_tasks=BackgroundTasks(),
            request=_request(),
            current_user=_ADMIN,
        ),
    )
    await _capture(
        cases,
        f"{d}.finish_auction_admin.400_already_ended",
        auc.finish_auction_admin(
            auction_id=AUCTION_INACTIVE,
            background_tasks=BackgroundTasks(),
            request=_request(),
            current_user=_ADMIN,
        ),
    )
    with _patched(DatabaseORM, "finish_auction_by_id", lambda *a, **k: (False, None)):
        await _capture(
            cases,
            f"{d}.finish_auction_admin.500_db_returned_false",
            auc.finish_auction_admin(
                auction_id=AUCTION_ACTIVE,
                background_tasks=BackgroundTasks(),
                request=_request(),
                current_user=_ADMIN,
            ),
        )

    # GET /admin/{auction_id}/bids
    await _capture(
        cases,
        f"{d}.get_auction_bids_admin.404_not_found",
        auc.get_auction_bids_admin(
            auction_id=MISSING, request=_request(), current_user=_ADMIN
        ),
    )
    with _patched(DatabaseORM, "get_auction_bids", _raise(RuntimeError("boom"))):
        await _capture(
            cases,
            f"{d}.get_auction_bids_admin.500_unexpected",
            auc.get_auction_bids_admin(
                auction_id=AUCTION_ACTIVE, request=_request(), current_user=_ADMIN
            ),
        )

    # GET /admin/user/{user_id}/history
    with _patched(
        DatabaseORM, "get_user_auction_history", _raise(RuntimeError("boom"))
    ):
        await _capture(
            cases,
            f"{d}.get_user_auction_history_admin.500_unexpected",
            auc.get_user_auction_history_admin(
                user_id=1, request=_request(), current_user=_ADMIN
            ),
        )

    # GET /admin/detailed-stats
    with _patched(
        DatabaseORM, "get_detailed_auction_stats", _raise(RuntimeError("boom"))
    ):
        await _capture(
            cases,
            f"{d}.get_detailed_auction_stats_admin.500_unexpected",
            auc.get_detailed_auction_stats_admin(
                request=_request(), current_user=_ADMIN
            ),
        )


# --------------------------------------------------------------------------- #
# 组装与用例
# --------------------------------------------------------------------------- #


def _install_noops(monkeypatch) -> None:
    """把外部副作用替换成 no-op：契约只关心 HTTP 层可见的行为。"""
    monkeypatch.setattr(lw.luckywheel_service, "consume_free_spin", lambda tg_id: None)
    monkeypatch.setattr(
        lw.luckywheel_service,
        "release_free_spin",
        lambda spin_id, *, claimed_at_ms: True,
    )
    monkeypatch.setattr(
        lw.luckywheel_service,
        "free_spin_summary",
        lambda tg_id: {
            "enabled": True,
            "available": 0,
            "expires_at_ms_list": [],
            "hands_since_freespin": 0,
            "hand_threshold": 20,
        },
    )
    monkeypatch.setattr(lw, "get_user_name_from_tg_id", lambda chat_id: "user")
    monkeypatch.setattr(luckywheel_notifications, "send_message_by_url", _async_none)

    monkeypatch.setattr(eth_rpc, "latest_block_hash_int", _async_none)
    monkeypatch.setattr(
        treasure_service.treasure_notifications,
        "notify_treasure_issue_created",
        _async_none,
    )
    monkeypatch.setattr(
        treasure_service.treasure_notifications,
        "notify_treasure_not_full_after_join",
        _async_none,
    )
    monkeypatch.setattr(
        treasure_service.treasure_notifications,
        "notify_treasure_settled",
        _async_none,
    )
    monkeypatch.setattr(
        treasure_service, "schedule_auto_reopen_treasure_issue", lambda **kw: None
    )

    for name in (
        "notify_prediction_bet_placed",
        "notify_prediction_market_created",
        "notify_prediction_market_resolved",
        "notify_prediction_submission_created",
        "notify_prediction_submission_reviewed",
        "notify_prediction_user_settlement",
    ):
        monkeypatch.setattr(
            pred.prediction_service.prediction_notifications, name, _async_none
        )

    monkeypatch.setattr(auc, "Scheduler", _StubScheduler)
    monkeypatch.setattr(auc, "send_channel_auction_notification", _async_none)
    monkeypatch.setattr(auc, "send_bid_notifications", _async_none)
    monkeypatch.setattr(auc, "get_user_name_from_tg_id", lambda chat_id: "user")
    monkeypatch.setattr(auc, "send_message_by_url", _async_none)
    monkeypatch.setattr(auc, "finish_expired_auctions_job", _async_empty_list)


async def _build() -> dict[str, Any]:
    cases: dict[str, Any] = {}
    await _build_shared(cases)
    await _build_luckywheel(cases)
    await _build_treasure(cases)
    await _build_prediction(cases)
    await _build_auction(cases)
    return cases


def _dump(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


async def test_activity_rejections(orm, monkeypatch) -> None:
    _install_noops(monkeypatch)
    _seed(orm)

    first = await _build()
    second = await _build()
    assert first == second, "快照必须可重复生成"

    if os.environ.get("UPDATE_ACTIVITY_REJECTIONS") == "1":
        FIXTURE.write_text(_dump(first), encoding="utf-8")
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert first == expected


def _covered_endpoints(cases: dict) -> set[tuple[str, str]]:
    covered: set[tuple[str, str]] = set()
    for key in cases:
        domain, endpoint, _branch = key.split(".", 2)
        covered.add((domain, endpoint))
    return covered


def test_rejections_cover_every_activity_endpoint() -> None:
    """面快照里的每个活动接口都必须至少有一条被冻结的拒绝分支。"""
    surface = json.loads(
        (Path(__file__).parent / "fixtures/activity_surface.json").read_text(
            encoding="utf-8"
        )
    )
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    covered = _covered_endpoints(cases)

    ours = {(key.split(".", 1)[0], key.split(".", 1)[1]) for key in _ENDPOINT_ARGS}
    ours.add(("luckywheel", "get_config"))  # 唯一没有认证装饰器的接口

    for domain, section in surface["domains"].items():
        for route in section["routes"]:
            pair = (domain, route["endpoint"])
            if pair in ours:
                assert pair in covered, f"{domain}.{route['endpoint']} 没有拒绝分支夹具"

    assert {domain for domain, _ in covered} == {
        "luckywheel",
        "treasure",
        "prediction",
        "auction",
    }
