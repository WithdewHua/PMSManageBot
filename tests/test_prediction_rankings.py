"""Prediction ranking service boundaries and HTTP response contract."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from app.domains.prediction import service as prediction_service
from app.domains.rankings import router as rankings_router
from app.domains.rankings import service as rankings_service
from app.transport.http.schemas import TelegramUser


def _request() -> Request:
    request = Request({"type": "http", "method": "GET", "path": "/api", "headers": []})
    request.state.telegram_data = {}
    return request


@pytest.mark.parametrize(
    ("method_name", "expected"),
    (
        ("get_prediction_net_profit_rank", [{"tg_id": 1, "net_profit": 12.5}]),
        ("get_prediction_win_rate_rank", [{"tg_id": 1, "win_rate": 75.0}]),
    ),
)
def test_prediction_service_exposes_repository_rankings(
    monkeypatch, method_name: str, expected: list[dict]
) -> None:
    monkeypatch.setattr(
        prediction_service.prediction_repository,
        method_name,
        lambda expected=expected: expected,
    )

    assert getattr(prediction_service, method_name)() == expected


@pytest.mark.parametrize(
    ("method_name", "expected"),
    (
        ("get_prediction_net_profit_rank", [{"tg_id": 1, "net_profit": 12.5}]),
        ("get_prediction_win_rate_rank", [{"tg_id": 1, "win_rate": 75.0}]),
    ),
)
def test_rankings_service_wraps_prediction_service(
    monkeypatch, method_name: str, expected: list[dict]
) -> None:
    monkeypatch.setattr(
        rankings_service.prediction_service,
        method_name,
        lambda expected=expected: expected,
    )

    assert getattr(rankings_service, method_name)() == expected


async def test_prediction_rankings_route_keeps_response_shape(monkeypatch) -> None:
    calls: list[str] = []
    net_profit = [
        {
            "tg_id": 1,
            "net_profit": 12.5,
            "win_rate": 75,
            "settled_markets": 4,
            "win_markets": 3,
            "total_bet_amount": 40,
            "total_payout_amount": 52.5,
        },
        {"tg_id": 999, "net_profit": 100},
    ]
    win_rate = [
        {
            "tg_id": 1,
            "win_rate": 75,
            "net_profit": 12.5,
            "settled_markets": 4,
            "win_markets": 3,
            "total_bet_amount": 40,
            "total_payout_amount": 52.5,
        },
        {"tg_id": 999, "win_rate": 100},
    ]

    def get_net_profit_rank() -> list[dict]:
        calls.append("net_profit")
        return net_profit

    def get_win_rate_rank() -> list[dict]:
        calls.append("win_rate")
        return win_rate

    monkeypatch.setattr(
        rankings_router.rankings_service,
        "get_prediction_net_profit_rank",
        get_net_profit_rank,
    )
    monkeypatch.setattr(
        rankings_router.rankings_service,
        "get_prediction_win_rate_rank",
        get_win_rate_rank,
    )
    monkeypatch.setattr(rankings_router.settings, "TG_ADMIN_CHAT_ID", [999])
    monkeypatch.setattr(
        rankings_router, "get_user_name_from_tg_id", lambda tg_id: f"user-{tg_id}"
    )
    monkeypatch.setattr(
        rankings_router, "get_user_avatar_from_tg_id", lambda tg_id: f"avatar-{tg_id}"
    )

    result = await rankings_router.get_prediction_game_rankings(
        request=_request(),
        user=TelegramUser(id=1, first_name="user", username="user"),
    )

    assert calls == ["net_profit", "win_rate"]
    assert result == {
        "prediction_net_profit_rank": [
            {
                "tg_id": 1,
                "name": "user-1",
                "net_profit": 12.5,
                "win_rate": 75.0,
                "settled_markets": 4,
                "win_markets": 3,
                "total_bet_amount": 40.0,
                "total_payout_amount": 52.5,
                "avatar": "avatar-1",
                "is_self": True,
            }
        ],
        "prediction_win_rate_rank": [
            {
                "tg_id": 1,
                "name": "user-1",
                "win_rate": 75.0,
                "net_profit": 12.5,
                "settled_markets": 4,
                "win_markets": 3,
                "total_bet_amount": 40.0,
                "total_payout_amount": 52.5,
                "avatar": "avatar-1",
                "is_self": True,
            }
        ],
    }
