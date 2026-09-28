"""大预言家现行行为：下注、投稿与审核、截止、开奖的三种派奖分支。

提升之前固定当前实现的结果（`promote-activity-domains` 任务 1.3）。三种
派奖分支分别记录每位用户的派奖额与荣耀奖池的变化；通知用替身。
"""

from __future__ import annotations

import time

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import event, select
from starlette.requests import Request

from app.core.db import get_session
from app.core.kv import SystemConfig
from app.core.schemas import TelegramUser
from app.domains.identity.models import Statistics
from app.domains.prediction import repository as prediction_repository
from app.domains.prediction import router as pred
from app.domains.prediction.models import (
    PredictionBet,
    PredictionMarket,
    PredictionMarketSubmission,
)
from app.domains.prediction.schemas import (
    PredictionBetRequest,
    PredictionCreateMarketRequest,
    PredictionResolveRequest,
    PredictionSubmissionReviewRequest,
)
from tests.conftest import add_user, next_id

ADMIN = TelegramUser(id=123456789, first_name="admin", username="admin")
FUTURE = int(time.time()) + 86_400


def _assign_row_id(mapper, connection, target) -> None:  # pragma: no cover - hook
    if target.id is None:
        target.id = next_id()


# SQLite 上 BIGINT 主键不自增
for _model in (
    PredictionMarket,
    PredictionBet,
    PredictionMarketSubmission,
    SystemConfig,
):
    event.listen(_model, "before_insert", _assign_row_id)


def _user(tg_id: int) -> TelegramUser:
    return TelegramUser(id=tg_id, first_name=f"u{tg_id}", username=f"u{tg_id}")


def _request() -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/api", "headers": []})
    request.state.telegram_data = {}
    return request


def _credits(tg_id: int) -> float:
    with get_session() as session:
        row = session.get(Statistics, int(tg_id))
        assert row is not None
        return float(row.credits)


def _glory_fund() -> str | None:
    with get_session() as session:
        return session.execute(
            select(SystemConfig.config_value).where(
                SystemConfig.config_type == "prediction_market",
                SystemConfig.config_key == "glory_fund",
            )
        ).scalar_one_or_none()


def _seed_glory_fund(value: str) -> None:
    now = int(time.time())
    with get_session() as session:
        session.add(
            SystemConfig(
                config_type="prediction_market",
                config_key="glory_fund",
                config_value=value,
                created_at=now,
                updated_at=now,
            )
        )


def _market(market_id: int) -> dict:
    with get_session() as session:
        row = session.get(PredictionMarket, int(market_id))
        assert row is not None
        return {
            "status": int(row.status),
            "result_option": row.result_option,
            "real_yes_pool": int(row.real_yes_pool),
            "real_no_pool": int(row.real_no_pool),
            "winner_id": None,
            "total_fee_collected": int(row.total_fee_collected),
            "fee_burned": int(row.fee_burned),
            "fee_to_glory": int(row.fee_to_glory),
        }


@pytest.fixture
def prediction_env(monkeypatch):
    """通知替身：记录调用，不触网。"""
    calls: dict[str, list] = {"notified": []}

    def _notify_spy(name: str):
        async def _spy(**kwargs):
            calls["notified"].append({"name": name, **kwargs})

        return _spy

    for name in (
        "notify_prediction_bet_placed",
        "notify_prediction_market_created",
        "notify_prediction_market_resolved",
        "notify_prediction_submission_created",
        "notify_prediction_submission_reviewed",
        "notify_prediction_user_settlement",
    ):
        monkeypatch.setattr(
            pred.prediction_service.prediction_notifications, name, _notify_spy(name)
        )
    return calls


# --------------------------------------------------------------------------- #
# 下注
# --------------------------------------------------------------------------- #


async def test_place_bet_deducts_credits_and_updates_pools(orm, prediction_env) -> None:
    market_id = prediction_repository.create_prediction_market(
        title="m", betting_deadline=FUTURE
    )
    add_user(orm, 1, credits=100.0)

    result = await pred.place_bet(
        request=_request(),
        market_id=market_id,
        background_tasks=BackgroundTasks(),
        data=PredictionBetRequest(option=1, amount=10),
        current_user=_user(1),
    )

    assert result["success"] is True
    assert result["bet"]["option"] == 1 and result["bet"]["amount"] == 10
    assert result["user_credits"] == 90.0
    assert _credits(1) == 90.0
    market = _market(market_id)
    assert market["real_yes_pool"] == 10 and market["real_no_pool"] == 0
    # 赔率按（真实 + 虚拟）池重算
    assert result["market"]["yes_odds"] == round(1010 / 510, 4)
    assert result["market"]["no_odds"] == round(1010 / 500, 4)


async def test_place_bet_rejects_over_personal_cap(orm, prediction_env) -> None:
    market_id = prediction_repository.create_prediction_market(
        title="m", betting_deadline=FUTURE, max_bet_per_user=5
    )
    add_user(orm, 1, credits=100.0)

    with pytest.raises(HTTPException) as excinfo:
        await pred.place_bet(
            request=_request(),
            market_id=market_id,
            background_tasks=BackgroundTasks(),
            data=PredictionBetRequest(option=1, amount=10),
            current_user=_user(1),
        )

    assert (excinfo.value.status_code, excinfo.value.detail) == (
        400,
        "超过该题目个人押注上限",
    )
    assert _credits(1) == 100.0
    with get_session() as session:
        assert session.execute(select(PredictionBet)).scalars().all() == []


async def test_place_bet_rejects_closed_unknown_and_unaffordable(
    orm, prediction_env
) -> None:
    open_market = prediction_repository.create_prediction_market(
        title="open", betting_deadline=FUTURE
    )
    closed_market = prediction_repository.create_prediction_market(
        title="closed", betting_deadline=FUTURE
    )
    prediction_repository.close_prediction_market_betting(market_id=closed_market)
    add_user(orm, 1, credits=100.0)
    add_user(orm, 2, credits=5.0)

    async def _bet(market_id: int, tg_id: int, amount: int = 10):
        return await pred.place_bet(
            request=_request(),
            market_id=market_id,
            background_tasks=BackgroundTasks(),
            data=PredictionBetRequest(option=1, amount=amount),
            current_user=_user(tg_id),
        )

    with pytest.raises(HTTPException) as missing:
        await _bet(999_999, 1)
    assert (missing.value.status_code, missing.value.detail) == (404, "预测题目不存在")

    with pytest.raises(HTTPException) as closed:
        await _bet(closed_market, 1)
    assert (closed.value.status_code, closed.value.detail) == (400, "当前不可押注")

    with pytest.raises(HTTPException) as poor:
        await _bet(open_market, 2, 10)
    assert (poor.value.status_code, poor.value.detail) == (400, "积分不足")


# --------------------------------------------------------------------------- #
# 投稿与审核
# --------------------------------------------------------------------------- #


async def test_submit_and_review_publishes_market_and_rewards_submitter(
    orm, prediction_env
) -> None:
    add_user(orm, 1, credits=100.0)
    submitted = await pred.submit_market(
        request=_request(),
        data=PredictionCreateMarketRequest(title="submitted", betting_deadline=FUTURE),
        current_user=_user(1),
    )
    submission_id = submitted["submission_id"]
    with get_session() as session:
        assert int(session.get(PredictionMarketSubmission, submission_id).status) == 0

    reviewed = await pred.review_submission(
        request=_request(),
        submission_id=submission_id,
        data=PredictionSubmissionReviewRequest(approved=True, review_note="ok"),
        current_user=ADMIN,
    )

    assert reviewed["success"] is True
    assert reviewed["market_id"]
    assert reviewed["submitter_tg_id"] == 1
    assert _credits(1) == 101.0  # 投稿通过 +1
    with get_session() as session:
        market = session.get(PredictionMarket, int(reviewed["market_id"]))
        assert market is not None and market.title == "submitted"
        assert int(session.get(PredictionMarketSubmission, submission_id).status) == 1


async def test_review_rejection_keeps_market_absent(orm, prediction_env) -> None:
    add_user(orm, 1, credits=100.0)
    submitted = await pred.submit_market(
        request=_request(),
        data=PredictionCreateMarketRequest(title="rejected", betting_deadline=FUTURE),
        current_user=_user(1),
    )

    reviewed = await pred.review_submission(
        request=_request(),
        submission_id=submitted["submission_id"],
        data=PredictionSubmissionReviewRequest(approved=False, review_note="no"),
        current_user=ADMIN,
    )

    assert reviewed["market_id"] is None
    assert _credits(1) == 100.0
    with get_session() as session:
        assert session.execute(select(PredictionMarket)).scalars().all() == []


# --------------------------------------------------------------------------- #
# 截止
# --------------------------------------------------------------------------- #


async def test_close_market_betting_marks_status(orm, prediction_env) -> None:
    market_id = prediction_repository.create_prediction_market(
        title="m", betting_deadline=FUTURE
    )

    closed = await pred.close_market_betting(
        request=_request(), market_id=market_id, current_user=ADMIN
    )

    assert closed == {"success": True, "market_id": market_id, "status": 2}
    assert _market(market_id)["status"] == 2

    with pytest.raises(HTTPException) as again:
        await pred.close_market_betting(
            request=_request(), market_id=market_id, current_user=ADMIN
        )
    assert (again.value.status_code, again.value.detail) == (400, "market not open")


# --------------------------------------------------------------------------- #
# 开奖的三种派奖分支
# --------------------------------------------------------------------------- #


def _bet(market_id: int, tg_id: int, option: int, amount: int) -> None:
    prediction_repository.place_prediction_bet(
        market_id=market_id, tg_id=tg_id, option=option, amount=amount
    )


def test_resolve_default_branch_splits_pool_among_winners(orm, prediction_env) -> None:
    market_id = prediction_repository.create_prediction_market(
        title="m", betting_deadline=FUTURE
    )
    add_user(orm, 1, credits=100.0)
    add_user(orm, 2, credits=100.0)
    _bet(market_id, 1, 1, 100)  # YES
    _bet(market_id, 2, 0, 100)  # NO

    result = prediction_repository.resolve_prediction_market(
        market_id=market_id, result_option=1, resolved_by=ADMIN.id
    )

    # 真实池 200；烧 6、荣耀 4；可派奖 190 全部给唯一 YES 押注者
    assert result["total_real_pool"] == 200
    assert result["total_fee"] == 10
    assert result["payout_pool"] == 190
    assert result["winner_count"] == 1
    assert _credits(1) == 190.0  # 100 - 100 + 190
    assert _credits(2) == 0.0
    assert _glory_fund() == "4.0"
    market = _market(market_id)
    assert market["status"] == 3 and market["result_option"] == 1
    assert market["total_fee_collected"] == 10


def test_resolve_without_winners_moves_pool_to_glory(orm, prediction_env) -> None:
    market_id = prediction_repository.create_prediction_market(
        title="m", betting_deadline=FUTURE
    )
    add_user(orm, 2, credits=100.0)
    _bet(market_id, 2, 0, 100)  # 只有 NO

    result = prediction_repository.resolve_prediction_market(
        market_id=market_id, result_option=1, resolved_by=ADMIN.id
    )

    # 胜方无人押中：95% 奖池并入荣耀池，无人派奖
    assert result["payout_pool"] == 0
    assert result["winner_count"] == 0
    assert _credits(2) == 0.0
    assert _glory_fund() == "97.0"  # 2（手续费）+ 95（并入）


def test_resolve_when_everyone_wins_compensates_from_glory(orm, prediction_env) -> None:
    market_id = prediction_repository.create_prediction_market(
        title="m", betting_deadline=FUTURE
    )
    add_user(orm, 1, credits=100.0)
    _seed_glory_fund("10")
    _bet(market_id, 1, 1, 100)  # 只有 YES

    result = prediction_repository.resolve_prediction_market(
        market_id=market_id, result_option=1, resolved_by=ADMIN.id
    )

    # 无败方：从荣耀池取 min(1.5 × 手续费, 余额) = 7 补偿，派奖 95 + 7 = 102
    assert result["payout_pool"] == 102
    assert result["winner_count"] == 1
    assert _credits(1) == 102.0  # 100 - 100 + 102
    assert _glory_fund() == "5.0"  # 10 + 2 - 7


def test_resolve_rejected_when_already_settled(orm, prediction_env) -> None:
    market_id = prediction_repository.create_prediction_market(
        title="m", betting_deadline=FUTURE
    )
    add_user(orm, 1, credits=100.0)
    _bet(market_id, 1, 1, 100)
    prediction_repository.resolve_prediction_market(
        market_id=market_id, result_option=1, resolved_by=ADMIN.id
    )

    with pytest.raises(ValueError) as excinfo:
        prediction_repository.resolve_prediction_market(
            market_id=market_id, result_option=1, resolved_by=ADMIN.id
        )

    assert str(excinfo.value) == "market already settled"


async def test_resolve_route_maps_already_settled_to_400(orm, prediction_env) -> None:
    market_id = prediction_repository.create_prediction_market(
        title="m", betting_deadline=FUTURE
    )
    add_user(orm, 1, credits=100.0)
    _bet(market_id, 1, 1, 100)
    prediction_repository.resolve_prediction_market(
        market_id=market_id, result_option=1, resolved_by=ADMIN.id
    )

    with pytest.raises(HTTPException) as excinfo:
        await pred.resolve_market(
            request=_request(),
            market_id=market_id,
            background_tasks=BackgroundTasks(),
            data=PredictionResolveRequest(result_option=1),
            current_user=ADMIN,
        )

    assert (excinfo.value.status_code, excinfo.value.detail) == (
        400,
        "market already settled",
    )
