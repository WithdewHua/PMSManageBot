from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core.errors import DomainError
from app.domains.blackjack import exceptions
from app.domains.blackjack.router import cash, tournament


def test_blackjack_errors_are_structured_and_legacy_compatible() -> None:
    error = exceptions.blackjack_error("insufficient credits to double: need 10")

    assert isinstance(error, DomainError)
    assert isinstance(error, ValueError)
    assert error.code == "blackjack_insufficient_credits_to_double"
    assert error.payload["detail"] == "积分不足，无法加倍"


def test_cash_error_adapter_preserves_existing_http_detail() -> None:
    with pytest.raises(HTTPException) as caught:
        cash._raise_for_value_error(exceptions.blackjack_error("hand already finished"))

    assert caught.value.status_code == 400
    assert caught.value.detail == "该手牌已结束"


@pytest.mark.parametrize(
    ("adapter", "message", "status_code", "detail"),
    [
        (cash._raise_for_value_error, "hand not found", 404, "手牌不存在"),
        (
            cash._raise_for_value_error,
            "deal too frequent",
            429,
            "操作过于频繁，请稍后再试",
        ),
        (
            cash._raise_for_value_error,
            "invalid bet: must be one of [5, 10]",
            400,
            "注额不合法，可选档位为 5、10",
        ),
        (
            tournament._raise_for_value_error,
            "tournament not found",
            404,
            "赛事不存在",
        ),
        (
            tournament._raise_for_value_error,
            "insufficient credits: need 30",
            400,
            "争霸赛余额与积分合计不足，报名需 30 积分（报名时优先扣争霸赛余额）",
        ),
        (
            tournament._raise_for_value_error,
            "bet must be a multiple of 10",
            400,
            "注额须为 10 的整数倍",
        ),
    ],
)
def test_typed_errors_preserve_status_and_detail(
    adapter, message, status_code, detail
) -> None:
    with pytest.raises(HTTPException) as caught:
        adapter(exceptions.blackjack_error(message))
    assert caught.value.status_code == status_code
    assert caught.value.detail == detail


def test_blackjack_routers_do_not_match_error_messages() -> None:
    root = Path(__file__).parents[1] / "src/app/domains/blackjack/router"
    for path in (root / "cash.py", root / "tournament.py"):
        source = path.read_text(encoding="utf-8")
        assert "msg_l" not in source
        assert 'if "' not in source


def test_tournament_error_adapter_preserves_existing_http_detail() -> None:
    with pytest.raises(HTTPException) as caught:
        tournament._raise_for_value_error(
            exceptions.blackjack_error("registration closed")
        )

    assert caught.value.status_code == 400
    assert caught.value.detail == "报名已截止"
